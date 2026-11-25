"""Pruebas de DATOS y de ARTEFACTOS del modelo (parte de la integracion continua).

Comprueban que el modelo versionado es el que debe ser (huellas sha256), que no contiene datos personales, que cumple las compuertas de
calidad, que sus clases coinciden con la aplicacion y que los datos semilla de la base de prueba son validos.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import joblib
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "pipeline"))

import datos_demo  # noqa: E402
import entrenar  # noqa: E402
import manifiesto  # noqa: E402
import validar_datos  # noqa: E402
from app import main  # noqa: E402
from app.motor_ocr import curp_verificada  # noqa: E402

COMPUERTAS = json.loads((RAIZ / "pipeline" / "compuertas.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- artefactos del modelo
def test_los_artefactos_coinciden_con_el_manifiesto():
    esperado = json.loads(Path(manifiesto.MANIFIESTO).read_text(encoding="utf-8"))["artefactos"]
    for archivo in manifiesto.ARCHIVOS:
        assert manifiesto.sha256(RAIZ / "modelo" / archivo) == esperado[archivo], f"{archivo} cambio sin actualizar el manifiesto (pipeline/manifiesto.py)"


def test_el_vocabulario_solo_usa_palabras_revisadas():
    """Privacidad: el modelo publicado no puede llevar nombres, CURP ni folios. Solo la lista revisada."""
    permitidas = set((RAIZ / "pipeline" / "vocabulario_publico.txt").read_text(encoding="utf-8").split())
    vectorizador = joblib.load(RAIZ / "modelo" / "vectorizador.pkl")
    fuera = [t for t in vectorizador.vocabulary_ if t not in permitidas and not t.startswith("__x")]
    assert not fuera, f"{len(fuera)} palabras del vocabulario no estan en la lista revisada"
    assert not getattr(vectorizador, "stop_words_", None), "el vectorizador guarda palabras descartadas"
    assert not [t for t in permitidas if re.search(r"\d", t)], "la lista permitida no debe tener numeros"


def test_las_metricas_de_referencia_cumplen_las_compuertas():
    m = json.loads((RAIZ / "modelo" / "metricas_referencia.json").read_text(encoding="utf-8"))
    assert m["exactitud"] >= COMPUERTAS["exactitud_min"]
    assert m["f1_macro"] >= COMPUERTAS["f1_macro_min"]
    assert min(m["f1_por_clase"].values()) >= COMPUERTAS["f1_por_clase_min"]
    assert m["baja_confianza"] <= COMPUERTAS["baja_confianza_max"]
    assert m["latencia_prediccion_ms"] <= COMPUERTAS["latencia_prediccion_ms_max"]


def test_las_clases_del_modelo_coinciden_con_la_aplicacion():
    clases_modelo = {str(c) for c in joblib.load(RAIZ / "modelo" / "modelo_clasificador.pkl").classes_}
    clases_app = set(main.TIPOS) - set(main.MANUALES)
    assert clases_modelo == clases_app


# ------------------------------------------------------------- datos semilla de la base de prueba
def test_los_datos_semilla_son_validos():
    sql = (RAIZ / "db" / "init" / "02_datos.sql").read_text(encoding="utf-8")
    curps = re.findall(r"'([A-Z]{4}\d{6}[HMX][A-Z]{2}[A-Z]{3}[A-Z0-9]\d)'", sql)
    assert len(curps) == 100, "deben ser 100 alumnos ficticios"
    assert len(set(curps)) == 100, "hay CURP repetidas"
    assert all(curp_verificada(c) for c in curps), "alguna CURP ficticia no tiene digito verificador valido"
    assert "ejemplo.com" in sql and "FICTICIOS" in sql


# ------------------------------------------------------------- pruebas del propio pipeline de entrenamiento
@pytest.fixture(scope="module")
def datos_buenos(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("datos") / "demo.csv"
    datos_demo.generar(str(ruta), por_clase=120)
    return ruta


def test_la_validacion_de_datos_acepta_un_conjunto_correcto(datos_buenos):
    errores, resumen = validar_datos.validar(pd.read_csv(datos_buenos))
    assert not errores and resumen["documentos"] == 720


def test_la_validacion_de_datos_rechaza_datos_personales(datos_buenos):
    df = pd.read_csv(datos_buenos)
    df.loc[0, "texto"] += " EELM060312MCHJPRA0 alumno@ejemplo.com 6145559385"
    errores, _ = validar_datos.validar(df)
    assert any("datos personales" in e for e in errores)


def test_la_validacion_de_datos_rechaza_clases_desbalanceadas(datos_buenos):
    df = pd.read_csv(datos_buenos)
    df = pd.concat([df, df[df.categoria == "CURP"].assign(texto=lambda d: d.texto + " extra")] * 2)
    errores, _ = validar_datos.validar(df)
    assert any("desbalanceadas" in e for e in errores)


def test_el_pipeline_aprueba_un_modelo_bueno_y_deja_su_manifiesto(datos_buenos, tmp_path):
    assert entrenar.entrenar(str(datos_buenos), str(tmp_path / "art"), "prueba") == 0
    man = json.loads((tmp_path / "art" / "manifiesto.json").read_text(encoding="utf-8"))
    assert man["aprobado"] and set(man["artefactos"]) == {"modelo_clasificador.pkl", "vectorizador.pkl"}
    assert all(c["cumple"] for c in man["compuertas"].values())
    assert entrenar.sha256(tmp_path / "art" / "modelo_clasificador.pkl") == man["artefactos"]["modelo_clasificador.pkl"]


def test_la_compuerta_de_calidad_detiene_un_modelo_malo(datos_buenos, tmp_path):
    df = pd.read_csv(datos_buenos)
    df["categoria"] = df["categoria"].sample(frac=1, random_state=1).values       # etiquetas revueltas: el modelo no puede aprender
    malo = tmp_path / "malo.csv"
    df.to_csv(malo, index=False)
    assert entrenar.entrenar(str(malo), str(tmp_path / "art"), "malo") == 1
    assert json.loads((tmp_path / "art" / "manifiesto.json").read_text(encoding="utf-8"))["aprobado"] is False


# ------------------------------------------------------------- los documentos de ejemplo se clasifican como se espera
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="sin Tesseract (se ejecuta dentro de Docker)")
@pytest.mark.parametrize("pdf,clase", [("acta_nacimiento_ficticia.pdf", "Actas de nacimiento"), ("constancia_curp_ficticia.pdf", "CURP")])
def test_los_ejemplos_se_clasifican_bien(pdf, clase):
    from app.main import MotorOCR
    motor = MotorOCR(main.MODELO_PATH, main.VECTORIZADOR_PATH, main.TESSERACT_CMD, main.POPPLER_PATH)
    datos = motor.procesar(str(RAIZ / "ejemplos" / pdf))
    assert datos["categoria"] == clase and datos["curp_verificada"]
