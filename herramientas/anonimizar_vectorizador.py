"""Quita datos personales del vectorizador antes de publicarlo.

El vectorizador TF-IDF guarda las 10 000 palabras mas frecuentes de los documentos con los que se entreno.
Si el entrenamiento uso documentos reales, entre ellas pueden quedar CURPs completas, folios o numeros
de certificado. Este script sustituye esas entradas por marcadores neutros (__x123) SIN cambiar su posicion,
asi el modelo (que depende del orden de las columnas) funciona igual y esos datos desaparecen del archivo.

    python herramientas/anonimizar_vectorizador.py ORIGEN.pkl DESTINO.pkl

Despues de reentrenar el modelo, ejecutalo antes de copiar el vectorizador a modelo/ y subirlo a GitHub.
"""

import re
import sys

import joblib

CURP = re.compile(r"[a-z]{4}\d{6}[hmx][a-z]{5}[a-z0-9]\d")
CURP_PARCIAL = re.compile(r"[a-z]{4}\d{6}[a-z0-9]{4,8}")   # CURP leida con errores de OCR
NUMERO_LARGO = re.compile(r"\d{6,}")                         # folios, matriculas, numeros de certificado


def es_dato_personal(token):
    return bool(CURP.fullmatch(token) or CURP_PARCIAL.fullmatch(token) or NUMERO_LARGO.search(token))


def main(origen, destino):
    vectorizador = joblib.load(origen)
    for atributo in ("stop_words_",):           # sklearn puede guardar aqui TODAS las palabras descartadas
        if getattr(vectorizador, atributo, None):
            setattr(vectorizador, atributo, set())
    vocabulario = vectorizador.vocabulary_
    quitados = [t for t in vocabulario if es_dato_personal(t)]
    for token in quitados:
        indice = vocabulario.pop(token)
        vocabulario[f"__x{indice}"] = indice     # misma columna, sin el dato
    joblib.dump(vectorizador, destino)
    print(f"{len(quitados)} entradas sustituidas de {len(vocabulario)}. Guardado en {destino}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
