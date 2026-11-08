"""Entrena el clasificador y lo registra en MLflow (seguimiento + Model Registry).

  v1  -> modelo de produccion (mismos hiperparametros que el modelo desplegado)   alias: produccion
  v2  -> modelo candidato (n-gramas 1-2, C=0.5) que pasa por compuertas de calidad alias: candidato (si las pasa)

Los textos del dataset se leen DENTRO del contenedor desde un volumen de solo lectura; a MLflow solo van
metricas, parametros y el modelo, nunca texto de documentos.
"""
import json
import os
import sys
import time

import matplotlib
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

matplotlib.use("Agg")
import matplotlib.pyplot as plt

URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
DATASET = os.getenv("DATASET", "/datos/dataset_700.csv")
SALIDA = os.getenv("SALIDA", "/estado")
MODELO = "clasificador-documentos"
mlflow.set_tracking_uri(URI)
mlflow.set_experiment("clasificador-expedientes")
cliente = MlflowClient()


def margen_top2(pipe, X):
    d = np.sort(pipe.decision_function(X), axis=1)
    return d[:, -1] - d[:, -2]


def entrenar(nombre, version_modelo, vec_params, svc_params, X_tr, X_te, y_tr, y_te, descripcion):
    with mlflow.start_run(run_name=nombre) as run:
        mlflow.set_tags({"modelo": MODELO, "version_modelo": version_modelo, "descripcion": descripcion})
        mlflow.log_params({**{f"tfidf_{k}": v for k, v in vec_params.items()},
                           **{f"svc_{k}": v for k, v in svc_params.items()},
                           "n_entrenamiento": len(X_tr), "n_prueba": len(X_te), "clases": len(set(y_tr))})
        t0 = time.time()
        pipe = Pipeline([("tfidf", TfidfVectorizer(**vec_params)), ("svc", LinearSVC(**svc_params))])
        pipe.fit(X_tr, y_tr)
        mlflow.log_metric("tiempo_entrenamiento_s", round(time.time() - t0, 2))
        t1 = time.time()
        pred = pipe.predict(X_te)
        lat_ms = (time.time() - t1) / len(X_te) * 1000
        m = margen_top2(pipe, X_te)
        met = {"accuracy": accuracy_score(y_te, pred), "f1_macro": f1_score(y_te, pred, average="macro"),
               "margen_mediana": float(np.median(m)), "margen_p5": float(np.percentile(m, 5)),
               "baja_confianza_fraccion": float((m < 1.2).mean()), "latencia_prediccion_ms": lat_ms}
        for c in sorted(set(y_te)):
            met["f1_" + c.replace(" ", "_")] = f1_score(y_te, pred, labels=[c], average="macro")
        mlflow.log_metrics({k: round(float(v), 4) for k, v in met.items()})
        clases = sorted(set(y_te))
        cm = confusion_matrix(y_te, pred, labels=clases)
        fig, ax = plt.subplots(figsize=(6.4, 5.4))
        ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(len(clases)), [c[:14] for c in clases], rotation=40, ha="right", fontsize=8)
        ax.set_yticks(range(len(clases)), [c[:14] for c in clases], fontsize=8)
        for i in range(len(clases)):
            for j in range(len(clases)):
                ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=8,
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
        ax.set_title(f"Matriz de confusion - {version_modelo} (prueba)")
        fig.tight_layout()
        mlflow.log_figure(fig, "matriz_confusion.png")
        plt.close(fig)
        # referencia de rasgos NO personales del conjunto de prueba
        analizador = pipe.named_steps["tfidf"].build_analyzer()
        vocab = set(pipe.named_steps["tfidf"].vocabulary_)
        pal = [len(t.split()) for t in X_te]
        cob = []
        for t in X_te:
            toks = analizador(t)
            cob.append(sum(1 for w in toks if w in vocab) / max(1, len(toks)))
        base = {"modelo": version_modelo, "n": len(X_te), "margen": [float(v) for v in m], "palabras": pal,
                "cobertura": cob, "clases": {c: float((pd.Series(y_te) == c).mean()) for c in clases}}
        mlflow.log_dict(base, "referencia_entrenamiento.json")
        info = mlflow.sklearn.log_model(pipe, "modelo", registered_model_name=MODELO)
        v = info.registered_model_version
        cliente.set_model_version_tag(MODELO, v, "version_modelo", version_modelo)
        for k, val in met.items():
            cliente.set_model_version_tag(MODELO, v, k, f"{val:.4f}")
        print(f"{nombre}: version registrada {v} " + " ".join(f"{k}={val:.3f}" for k, val in met.items() if not k.startswith("f1_")))
        return pipe, v, met, run.info.run_id


def main():
    d = pd.read_csv(DATASET).dropna(subset=["texto", "categoria"])
    X_tr, X_te, y_tr, y_te = train_test_split(d.texto.astype(str).tolist(), d.categoria.tolist(), test_size=0.2,
                                              stratify=d.categoria, random_state=42)
    p1, v1, m1, r1 = entrenar("v1-produccion", "v1", dict(max_features=10000, ngram_range=(1, 1), lowercase=True),
                              dict(C=1.0, random_state=42), X_tr, X_te, y_tr, y_te,
                              "Modelo desplegado: TF-IDF 10 000 terminos + LinearSVC C=1")
    cliente.set_registered_model_alias(MODELO, "produccion", v1)
    p2, v2, m2, r2 = entrenar("v2-candidato", "v2", dict(max_features=20000, ngram_range=(1, 2), lowercase=True),
                              dict(C=0.5, random_state=42), X_tr, X_te, y_tr, y_te,
                              "Candidato: TF-IDF 1-2 gramas 20 000 terminos + LinearSVC C=0.5")
    compuertas = {
        "f1_macro >= v1 - 0.005": m2["f1_macro"] >= m1["f1_macro"] - 0.005,
        "margen_p5 >= v1": m2["margen_p5"] >= m1["margen_p5"],
        "baja_confianza <= 5 %": m2["baja_confianza_fraccion"] <= 0.05,
        "latencia_prediccion <= 5 ms": m2["latencia_prediccion_ms"] <= 5.0,
    }
    with mlflow.start_run(run_id=r2):
        for k, ok in compuertas.items():
            mlflow.log_metric("compuerta_" + k.split()[0], int(ok))
        mlflow.set_tag("compuertas", json.dumps(compuertas, ensure_ascii=False))
    print("Compuertas del candidato:", compuertas)
    if all(compuertas.values()):
        cliente.set_registered_model_alias(MODELO, "candidato", v2)
        cliente.set_model_version_tag(MODELO, v2, "estado", "candidato: compuertas superadas")
    else:
        cliente.set_model_version_tag(MODELO, v2, "estado",
                                      "rechazado: " + ", ".join(k for k, ok in compuertas.items() if not ok))
    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, "metricas_modelos.json"), "w") as f:
        json.dump({"v1": m1, "v2": m2, "compuertas": compuertas}, f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
