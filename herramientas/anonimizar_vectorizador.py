"""Garantiza que el vectorizador que se publica solo contenga palabras de la lista revisada.

El vectorizador TF-IDF guarda palabras sacadas de los documentos con los que se entreno. Con documentos reales pueden
quedar nombres, apellidos, CURP o folios. No basta con filtrar patrones: aqui se usa una LISTA DE PALABRAS PERMITIDAS
(pipeline/vocabulario_publico.txt: palabras comunes y de formato, revisadas a mano). Cualquier otra entrada se sustituye
por un marcador neutro (__x123) sin cambiar su posicion.

    python herramientas/anonimizar_vectorizador.py ORIGEN.pkl DESTINO.pkl

Lo recomendado es entrenar directamente con la lista (pipeline/entrenar.py --vocabulario pipeline/vocabulario_publico.txt):
asi el modelo aprende solo con esas palabras y sus metricas son las del modelo publicado. Despues de sustituir entradas
con este script hay que volver a medir el modelo.
"""

import os
import sys

import joblib

LISTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "vocabulario_publico.txt")


def palabras_permitidas(ruta=LISTA):
    with open(ruta, encoding="utf-8") as f:
        return set(f.read().split())


def no_permitidas(vocabulario, permitidas):
    return [t for t in vocabulario if t not in permitidas and not t.startswith("__x")]


def main(origen, destino):
    vectorizador = joblib.load(origen)
    if getattr(vectorizador, "stop_words_", None):     # sklearn puede guardar aqui TODAS las palabras descartadas
        vectorizador.stop_words_ = set()
    vocabulario = vectorizador.vocabulary_
    quitadas = no_permitidas(vocabulario, palabras_permitidas())
    for token in quitadas:
        indice = vocabulario.pop(token)
        vocabulario[f"__x{indice}"] = indice           # misma columna, sin la palabra
    if getattr(vectorizador, "vocabulary", None) is not None:
        vectorizador.vocabulary = dict(vocabulario)
    joblib.dump(vectorizador, destino)
    print(f"{len(quitadas)} entradas sustituidas de {len(vocabulario)}. Guardado en {destino}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
