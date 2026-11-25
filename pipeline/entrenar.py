"""Pipeline de ENTRENAMIENTO: valida los datos, entrena, evalua contra las compuertas de calidad, versiona los artefactos y (opcional) registra
el modelo en MLflow. Si algo falla (datos invalidos o compuertas sin cumplir) sale con codigo 1 y el pipeline se detiene.

    python pipeline/datos_demo.py --salida datos_demo.csv
    python pipeline/entrenar.py --datos datos_demo.csv --salida artefactos --version demo-1
    MLFLOW_TRACKING_URI=sqlite:///mlflow.db python pipeline/entrenar.py --datos datos_demo.csv --salida artefactos

Salida (carpeta --salida): modelo_clasificador.pkl, vectorizador.pkl, metricas.json y manifiesto.json (huellas sha256, versiones, parametros,
resultado de cada compuerta y el commit de Git que lo produjo).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.svm import LinearSVC

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from validar_datos import validar  # noqa: E402

PARAMS = {"tfidf_max_features": 10000, "tfidf_ngram_range": [1, 1], "svc_C": 1.0, "semilla": 42, "prueba": 0.2}
UMBRAL_DUDA = 1.2   # margen de decision por debajo del cual el documento pasa a revision humana


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def entrenar(datos, salida, version, permitir_curp=False, vocabulario=None):
    df = pd.read_csv(datos)
    errores, resumen = validar(df, permitir_curp=permitir_curp)
    print("Validacion de datos:", json.dumps(resumen, ensure_ascii=False))
    if errores:
        print("DATOS INVALIDOS:", *errores, sep="\n  - ")
        return 1
    df = df.dropna(subset=["texto", "categoria"])
    X_tr, X_te, y_tr, y_te = train_test_split(df["texto"].astype(str), df["categoria"], test_size=PARAMS["prueba"], stratify=df["categoria"],
                                              random_state=PARAMS["semilla"])
    lista = None
    if vocabulario:   # lista revisada de palabras permitidas: obligatoria para publicar un modelo entrenado con documentos reales
        with open(vocabulario, encoding="utf-8") as f:
            lista = f.read().split()
    vec = TfidfVectorizer(max_features=PARAMS["tfidf_max_features"], ngram_range=tuple(PARAMS["tfidf_ngram_range"]), lowercase=True, vocabulary=lista)
    clf = LinearSVC(C=PARAMS["svc_C"], random_state=PARAMS["semilla"])
    t0 = time.time()
    clf.fit(vec.fit_transform(X_tr), y_tr)
    entrenamiento_s = time.time() - t0

    Xt = vec.transform(X_te)
    t1 = time.time()
    pred = clf.predict(Xt)
    latencia_ms = (time.time() - t1) / len(y_te) * 1000
    dec = np.sort(clf.decision_function(Xt), axis=1)
    margen = dec[:, -1] - dec[:, -2]
    metricas = {"exactitud": round(float(accuracy_score(y_te, pred)), 4), "f1_macro": round(float(f1_score(y_te, pred, average="macro")), 4),
                "f1_por_clase": {c: round(float(f1_score(y_te, pred, labels=[c], average="macro")), 4) for c in sorted(set(y_te))},
                "margen_p5": round(float(np.percentile(margen, 5)), 4), "baja_confianza": round(float((margen < UMBRAL_DUDA).mean()), 4),
                "latencia_prediccion_ms": round(latencia_ms, 4), "documentos_entrenamiento": int(len(y_tr)), "documentos_prueba": int(len(y_te)),
                "tiempo_entrenamiento_s": round(entrenamiento_s, 2)}

    with open(os.path.join(AQUI, "compuertas.json"), encoding="utf-8") as f:
        g = json.load(f)
    compuertas = {
        "exactitud": (metricas["exactitud"], f">= {g['exactitud_min']}", metricas["exactitud"] >= g["exactitud_min"]),
        "f1_macro": (metricas["f1_macro"], f">= {g['f1_macro_min']}", metricas["f1_macro"] >= g["f1_macro_min"]),
        "f1_peor_clase": (min(metricas["f1_por_clase"].values()), f">= {g['f1_por_clase_min']}", min(metricas["f1_por_clase"].values()) >= g["f1_por_clase_min"]),
        "baja_confianza": (metricas["baja_confianza"], f"<= {g['baja_confianza_max']}", metricas["baja_confianza"] <= g["baja_confianza_max"]),
        "latencia_prediccion_ms": (metricas["latencia_prediccion_ms"], f"<= {g['latencia_prediccion_ms_max']}", metricas["latencia_prediccion_ms"] <= g["latencia_prediccion_ms_max"]),
    }
    print("\nCompuertas de calidad:")
    for nombre, (valor, regla, ok) in compuertas.items():
        print(f"  {'OK    ' if ok else 'FALLA '} {nombre}: {valor} (regla {regla})")
    aprobado = all(ok for _, _, ok in compuertas.values())

    os.makedirs(salida, exist_ok=True)
    ruta_m, ruta_v = os.path.join(salida, "modelo_clasificador.pkl"), os.path.join(salida, "vectorizador.pkl")
    joblib.dump(clf, ruta_m)
    joblib.dump(vec, ruta_v)
    manifiesto = {"version": version, "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": os.getenv("GITHUB_SHA", "local"),
                  "ejecucion": os.getenv("GITHUB_RUN_ID", "local"), "scikit_learn": sklearn.__version__, "parametros": PARAMS,
                  "datos": {"archivo": os.path.basename(datos), "sha256": sha256(datos), "documentos": int(len(df))},
                  "artefactos": {"modelo_clasificador.pkl": sha256(ruta_m), "vectorizador.pkl": sha256(ruta_v)},
                  "clases": [str(c) for c in clf.classes_], "compuertas": {k: {"valor": v, "regla": r, "cumple": bool(ok)} for k, (v, r, ok) in compuertas.items()},
                  "aprobado": bool(aprobado)}
    with open(os.path.join(salida, "metricas.json"), "w", encoding="utf-8") as f:
        json.dump(metricas, f, ensure_ascii=False, indent=1)
    with open(os.path.join(salida, "manifiesto.json"), "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=1)

    if os.getenv("MLFLOW_TRACKING_URI"):
        registrar_mlflow(vec, clf, metricas, manifiesto, salida, version, aprobado)
    print("\nRESULTADO:", "APROBADO: el modelo cumple todas las compuertas" if aprobado else "RECHAZADO: no cumple las compuertas")
    return 0 if aprobado else 1


def registrar_mlflow(vec, clf, metricas, manifiesto, salida, version, aprobado):
    """Seguimiento y registro en MLflow; el alias 'candidato' solo se asigna si pasa las compuertas."""
    import mlflow
    from mlflow.tracking import MlflowClient
    from sklearn.pipeline import Pipeline

    mlflow.set_experiment("pipeline-entrenamiento")
    with mlflow.start_run(run_name=f"entrenamiento-{version}") as run:
        mlflow.set_tags({"commit": manifiesto["commit"], "ejecucion": manifiesto["ejecucion"], "aprobado": str(aprobado)})
        mlflow.log_params({k: str(v) for k, v in PARAMS.items()})
        mlflow.log_metrics({k: v for k, v in metricas.items() if isinstance(v, (int, float))})
        mlflow.log_artifact(os.path.join(salida, "manifiesto.json"))
        mlflow.log_artifact(os.path.join(salida, "metricas.json"))
        info = mlflow.sklearn.log_model(Pipeline([("tfidf", vec), ("svc", clf)]), "modelo", registered_model_name="clasificador-documentos-ci")
        if aprobado:
            MlflowClient().set_registered_model_alias("clasificador-documentos-ci", "candidato", info.registered_model_version)
        print(f"MLflow: run {run.info.run_id}, version {info.registered_model_version}, alias candidato={'si' if aprobado else 'no'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", required=True)
    ap.add_argument("--salida", default="artefactos")
    ap.add_argument("--version", default="dev")
    ap.add_argument("--permitir-curp", action="store_true", help="solo para el dataset real, que se usa localmente")
    ap.add_argument("--vocabulario", help="lista de palabras permitidas (pipeline/vocabulario_publico.txt) para modelos que se publican")
    a = ap.parse_args()
    sys.exit(entrenar(a.datos, a.salida, a.version, a.permitir_curp, a.vocabulario))
