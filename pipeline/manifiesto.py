"""Genera (o verifica) el MANIFIESTO del modelo desplegado: huellas sha256 de los artefactos, version, clases y metricas de referencia.
El manifiesto se versiona en Git: si alguien cambia el modelo sin actualizarlo, las pruebas fallan (integridad de artefactos).

    python pipeline/manifiesto.py              genera modelo/MANIFIESTO_MODELO.json
    python pipeline/manifiesto.py --verificar  comprueba que los archivos coinciden con el manifiesto
"""
import hashlib
import json
import os
import sys
from datetime import date

import joblib
import sklearn

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MODELO = os.path.join(RAIZ, "modelo")
MANIFIESTO = os.path.join(MODELO, "MANIFIESTO_MODELO.json")
ARCHIVOS = ("modelo_clasificador.pkl", "vectorizador.pkl")


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def construir():
    with open(os.path.join(MODELO, "metricas_referencia.json"), encoding="utf-8") as f:
        ref = json.load(f)
    clf = joblib.load(os.path.join(MODELO, "modelo_clasificador.pkl"))
    return {"modelo": "clasificador-documentos", "version": ref["version"], "generado": date.today().isoformat(), "scikit_learn": sklearn.__version__,
            "clases": [str(c) for c in clf.classes_], "artefactos": {a: sha256(os.path.join(MODELO, a)) for a in ARCHIVOS},
            "metricas_referencia": {k: ref[k] for k in ("exactitud", "f1_macro", "margen_p5", "baja_confianza", "latencia_prediccion_ms")}}


if __name__ == "__main__":
    if "--verificar" in sys.argv:
        esperado = json.load(open(MANIFIESTO, encoding="utf-8"))["artefactos"]
        mal = [a for a in ARCHIVOS if sha256(os.path.join(MODELO, a)) != esperado[a]]
        print("Artefactos del modelo: " + ("coinciden con el manifiesto" if not mal else f"NO coinciden: {mal}"))
        sys.exit(1 if mal else 0)
    with open(MANIFIESTO, "w", encoding="utf-8") as f:
        json.dump(construir(), f, ensure_ascii=False, indent=1)
    print("Escrito", MANIFIESTO)
