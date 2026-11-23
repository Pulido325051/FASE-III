"""Pruebas de DATOS del pipeline: valida el conjunto de entrenamiento antes de entrenar. Si algo falla, el pipeline se detiene.

    python pipeline/validar_datos.py datos.csv

Comprueba: columnas, nulos, clases esperadas, tamano minimo y balance por clase, longitud minima del texto, duplicados exactos y que NO
haya datos personales (CURP, correos, telefonos): un dataset con datos personales no debe entrenar un modelo que se publica.
"""
import json
import re
import sys

import pandas as pd

CLASES_ESPERADAS = {"Actas de nacimiento", "CURP", "Certificado Final", "Certificado Parcial", "Certificados Secundaria", "Equivalencia"}
MIN_POR_CLASE, DESBALANCE_MAX, MIN_PALABRAS, DUPLICADOS_MAX = 50, 1.5, 15, 0.02
PATRON_CURP = re.compile(r"\b[A-Z]{4}\d{6}[HMX][A-Z]{2}[A-Z]{3}[A-Z0-9]\d\b", re.IGNORECASE)
PATRON_CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PATRON_TEL = re.compile(r"\b\d{10}\b")


def validar(df, permitir_curp=False):
    """Devuelve (lista de errores, resumen). `permitir_curp` solo para el dataset real que se usa localmente."""
    errores, resumen = [], {}
    faltan = {"texto", "categoria"} - set(df.columns)
    if faltan:
        return [f"faltan columnas: {sorted(faltan)}"], resumen
    nulos = int(df["texto"].isna().sum() + df["categoria"].isna().sum())
    if nulos:
        errores.append(f"{nulos} valores nulos en texto o categoria")
    df = df.dropna(subset=["texto", "categoria"])
    resumen["documentos"] = int(len(df))
    clases = set(df["categoria"].unique())
    if clases != CLASES_ESPERADAS:
        errores.append(f"clases distintas a las esperadas: sobran {sorted(clases - CLASES_ESPERADAS)}, faltan {sorted(CLASES_ESPERADAS - clases)}")
    conteo = df["categoria"].value_counts()
    resumen["por_clase"] = {k: int(v) for k, v in conteo.items()}
    if len(conteo) and conteo.min() < MIN_POR_CLASE:
        errores.append(f"una clase tiene {int(conteo.min())} documentos (minimo {MIN_POR_CLASE})")
    if len(conteo) and conteo.max() / conteo.min() > DESBALANCE_MAX:
        errores.append(f"clases desbalanceadas: {conteo.max() / conteo.min():.2f} veces (maximo {DESBALANCE_MAX})")
    palabras = df["texto"].astype(str).str.split().str.len()
    cortos = int((palabras < MIN_PALABRAS).sum())
    resumen["palabras_mediana"] = int(palabras.median()) if len(palabras) else 0
    if cortos:
        errores.append(f"{cortos} documentos con menos de {MIN_PALABRAS} palabras")
    dup = float(df.duplicated(subset=["texto"]).mean()) if len(df) else 0.0
    resumen["duplicados"] = round(dup, 4)
    if dup > DUPLICADOS_MAX:
        errores.append(f"{dup:.1%} de textos duplicados (maximo {DUPLICADOS_MAX:.0%})")
    texto = "\n".join(df["texto"].astype(str).head(20000))
    pii = {"curp": len(PATRON_CURP.findall(texto)), "correo": len(PATRON_CORREO.findall(texto)), "telefono": len(PATRON_TEL.findall(texto))}
    resumen["datos_personales_hallados"] = pii
    if (pii["correo"] or pii["telefono"] or (pii["curp"] and not permitir_curp)):
        errores.append(f"se hallaron datos personales en el texto: {pii}")
    return errores, resumen


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    errores, resumen = validar(pd.read_csv(sys.argv[1]), permitir_curp="--permitir-curp" in sys.argv)
    print(json.dumps({"resumen": resumen, "errores": errores}, ensure_ascii=False, indent=1))
    sys.exit(1 if errores else 0)
