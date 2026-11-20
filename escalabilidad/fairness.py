"""Evaluacion de fairness y sesgos del clasificador de documentos. Solo se guardan resultados AGREGADOS (conteos y tasas por grupo):
ningun texto, nombre ni CURP sale de este script.

    python escalabilidad/fairness.py ruta/al/dataset.csv        (columnas: texto, categoria; el dataset NO se sube a GitHub)

Entrena el modelo con la configuracion de produccion (80 % del dataset) y lo evalua en el 20 % restante. Como el dataset no trae
atributos demograficos, se usan grupos inferibles sin identificar a nadie: tipo de documento, calidad del escaneo (terciles de
palabras y de cobertura del vocabulario) y, cuando la CURP es legible, el sexo y la entidad que ella contiene.
Grupos con menos de 30 documentos se reportan como 'muestra insuficiente'. Salida: escalabilidad/resultados/fairness.json
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))
from app.motor_ocr import NO_ENCONTRADA, curp_verificada, extraer_curp  # noqa: E402

SALIDA = os.path.join(AQUI, "resultados", "fairness.json")
MIN_GRUPO = 30
ESTADOS = {"AS": "Aguascalientes", "BC": "Baja California", "BS": "Baja California Sur", "CC": "Campeche", "CL": "Coahuila", "CM": "Colima",
           "CS": "Chiapas", "CH": "Chihuahua", "DF": "Ciudad de México", "DG": "Durango", "GT": "Guanajuato", "GR": "Guerrero", "HG": "Hidalgo",
           "JC": "Jalisco", "MC": "Estado de México", "MN": "Michoacán", "MS": "Morelos", "NT": "Nayarit", "NL": "Nuevo León", "OC": "Oaxaca",
           "PL": "Puebla", "QT": "Querétaro", "QR": "Quintana Roo", "SP": "San Luis Potosí", "SL": "Sinaloa", "SR": "Sonora", "TC": "Tabasco",
           "TS": "Tamaulipas", "TL": "Tlaxcala", "VZ": "Veracruz", "YN": "Yucatán", "ZS": "Zacatecas", "NE": "Nacido en el extranjero"}


def main(csv):
    d = pd.read_csv(csv).dropna(subset=["texto", "categoria"]).reset_index(drop=True)
    d["texto"] = d["texto"].astype(str)
    X_tr, X_te, y_tr, y_te, _, i_te = train_test_split(d["texto"], d["categoria"], d.index, test_size=0.2, stratify=d["categoria"], random_state=42)
    pipe = Pipeline([("tfidf", TfidfVectorizer(max_features=10000, ngram_range=(1, 1), lowercase=True)), ("svc", LinearSVC(C=1.0, random_state=42))])
    pipe.fit(X_tr, y_tr)
    dec = np.sort(pipe.decision_function(X_te), axis=1)
    t = pd.DataFrame({"y": y_te.values, "p": pipe.predict(X_te), "margen": dec[:, -1] - dec[:, -2]}, index=i_te)
    t["ok"] = t.y == t.p
    an, voc = pipe.named_steps["tfidf"].build_analyzer(), set(pipe.named_steps["tfidf"].vocabulary_)
    t["palabras"] = d.loc[t.index, "texto"].str.split().str.len()
    t["cobertura"] = [np.mean([w in voc for w in an(x)] or [0]) for x in d.loc[t.index, "texto"]]
    todos = d.copy()
    todos["curp"] = [extraer_curp(x) for x in todos.texto]
    todos["curp_ok"] = [c != NO_ENCONTRADA and curp_verificada(c) for c in todos.curp]
    t["curp"], t["curp_ok"] = todos.loc[t.index, "curp"], todos.loc[t.index, "curp_ok"]
    t["sexo"] = np.where(t.curp_ok, t.curp.str[10], None)
    t["entidad"] = np.where(t.curp_ok, t.curp.str[11:13].map(ESTADOS), None)

    res = {"n_total": int(len(d)), "n_prueba": int(len(t)), "exactitud": round(float(t.ok.mean()), 4)}
    rep = classification_report(t.y, t.p, output_dict=True, zero_division=0)
    res["por_clase"] = {c: {"n": int(v["support"]), "precision": round(v["precision"], 3), "recall": round(v["recall"], 3), "f1": round(v["f1-score"], 3)}
                        for c, v in rep.items() if c not in ("accuracy", "macro avg", "weighted avg")}
    res["macro_f1"] = round(rep["macro avg"]["f1-score"], 4)
    cm = pd.crosstab(t.y, t.p)
    errores = [(a, b, int(cm.loc[a, b])) for a in cm.index for b in cm.columns if a != b and cm.loc[a, b] > 0]
    res["errores_frecuentes"] = sorted(errores, key=lambda x: -x[2])[:5]

    def por_grupo(col):
        out, sub = {}, t[t[col].notna()]
        for g, s in sub.groupby(col, observed=True):
            if len(s) < MIN_GRUPO:
                out[str(g)] = {"n": int(len(s)), "nota": "muestra insuficiente"}
            else:
                out[str(g)] = {"n": int(len(s)), "exactitud": round(float(s.ok.mean()), 4), "baja_confianza": round(float((s.margen < 1.2).mean()), 4)}
        vals = [v["exactitud"] for v in out.values() if "exactitud" in v]
        return {"grupos": out, "razon_impacto_dispar_exactitud": round(min(vals) / max(vals), 4) if len(vals) >= 2 else None,
                "brecha_pp": round((max(vals) - min(vals)) * 100, 2) if len(vals) >= 2 else None}

    res["cobertura_curp_legible_prueba"] = round(float(t.curp_ok.mean()), 4)
    res["por_sexo"] = por_grupo("sexo")
    top = t[t.entidad.notna()].entidad.value_counts()
    t["entidad_g"] = t.entidad.where(t.entidad.isin(top[top >= MIN_GRUPO].index), np.where(t.entidad.notna(), "Otras entidades (<30 docs c/u)", None))
    res["por_entidad"] = por_grupo("entidad_g")
    t["calidad_palabras"] = pd.qcut(t.palabras, 3, labels=["bajo", "medio", "alto"])
    t["calidad_cobertura"] = pd.qcut(t.cobertura, 3, labels=["baja", "media", "alta"])
    res["por_calidad_palabras"] = por_grupo("calidad_palabras")
    res["por_calidad_cobertura"] = por_grupo("calidad_cobertura")
    todos["palabras"] = todos.texto.str.split().str.len()
    res["curp_por_clase"] = {c: {"n": int(len(s)), "curp_verificada": round(float(s.curp_ok.mean()), 4)} for c, s in todos.groupby("categoria")}
    todos["tercil"] = pd.qcut(todos.palabras, 3, labels=["bajo", "medio", "alto"])
    res["curp_por_calidad"] = {str(c): {"n": int(len(s)), "curp_verificada": round(float(s.curp_ok.mean()), 4)} for c, s in todos.groupby("tercil", observed=True)}
    res["curp_global"] = round(float(todos.curp_ok.mean()), 4)
    res["nota"] = "El dataset guarda texto OCR limpio (sin atributos demograficos). Sexo y entidad se infieren de la CURP legible y solo se reportan agregados."
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("n_prueba", "exactitud", "macro_f1", "cobertura_curp_legible_prueba")}, ensure_ascii=False))
    print("Guardado en", SALIDA)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
