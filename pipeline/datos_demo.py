"""Genera un conjunto de datos SINTETICO para ejecutar el pipeline de entrenamiento en CI sin usar datos reales.

Cada documento es un texto inventado con el vocabulario tipico de cada clase, mas ruido y nombres ficticios. Sirve para comprobar que el
pipeline (validacion de datos, entrenamiento, compuertas y registro) funciona; el modelo de produccion se entrena con el dataset real, que
nunca se sube al repositorio.

    python pipeline/datos_demo.py --salida datos_demo.csv --por-clase 150
"""
import argparse
import csv
import random

CLASES = {
    "Actas de nacimiento": ["acta", "de", "nacimiento", "registro", "civil", "oficialia", "libro", "foja", "certifica", "que", "nacio", "padres",
                            "lugar", "de", "registro", "fecha", "de", "nacimiento", "sexo", "testigos", "acta", "numero"],
    "CURP": ["clave", "unica", "de", "registro", "de", "poblacion", "constancia", "renapo", "secretaria", "de", "gobernacion", "curp",
             "datos", "del", "solicitante", "entidad", "de", "registro", "presente"],
    "Certificado Final": ["certificado", "de", "terminacion", "de", "estudios", "bachillerato", "promedio", "general", "concluyo", "plan", "de",
                          "estudios", "plantel", "direccion", "general", "firma", "director", "constancia", "de", "acreditacion", "total"],
    "Certificado Parcial": ["certificado", "parcial", "asignaturas", "acreditadas", "periodo", "semestre", "calificaciones", "no", "acreditadas",
                            "cursadas", "hasta", "la", "fecha", "creditos", "parciales", "historial", "academico"],
    "Certificados Secundaria": ["certificado", "de", "educacion", "secundaria", "secretaria", "de", "educacion", "publica", "escuela", "secundaria",
                                "ciclo", "escolar", "grado", "tercero", "clave", "del", "centro", "de", "trabajo", "promedio", "final"],
    "Equivalencia": ["resolucion", "de", "equivalencia", "de", "estudios", "dictamen", "tabla", "de", "equivalencias", "asignaturas",
                     "equivalentes", "revalidacion", "autoridad", "educativa", "oficio", "numero", "procede", "validez", "oficial"],
}
RUIDO = ["sello", "firma", "folio", "pagina", "fecha", "documento", "oficial", "mexico", "chihuahua", "numero", "copia", "original", "escuela",
         "alumno", "nombre", "apellido", "estado", "municipio", "localidad", "director", "secretario", "validez", "registro", "datos"]
NOMBRES = ["maria", "jose", "ana", "luis", "carmen", "juan", "sofia", "pedro", "lucia", "diego"]
APELLIDOS = ["ejemplo", "prueba", "demo", "ficticio", "lopez", "garcia", "ramos", "torres", "flores", "reyes"]


def documento(clase, rng):
    palabras = [w for w in CLASES[clase] if rng.random() < 0.8]
    otras = [w for c, ws in CLASES.items() if c != clase for w in ws]      # vocabulario de otras clases: los documentos se parecen entre si
    palabras += [rng.choice(otras) for _ in range(rng.randint(2, 6))]
    palabras += [rng.choice(RUIDO) for _ in range(rng.randint(15, 45))]
    palabras += [rng.choice(NOMBRES), rng.choice(APELLIDOS), rng.choice(APELLIDOS)]
    rng.shuffle(palabras)
    return " ".join(palabras)


def generar(salida, por_clase=150, semilla=42):
    rng = random.Random(semilla)
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["texto", "categoria", "archivo"])
        for clase in CLASES:
            for i in range(por_clase):
                w.writerow([documento(clase, rng), clase, f"demo_{clase[:4]}_{i}.pdf"])
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", default="datos_demo.csv")
    ap.add_argument("--por-clase", type=int, default=150)
    ap.add_argument("--semilla", type=int, default=42)
    a = ap.parse_args()
    print("Generado:", generar(a.salida, a.por_clase, a.semilla))
