"""Pruebas de la observabilidad (metricas, logs y eventos). No necesitan base de datos.

Lo importante: las metricas se publican, cada respuesta lleva su identificador de peticion, la inyeccion de fallas
esta apagada por defecto y NINGUN evento ni log lleva datos personales (CURP, nombre).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app import observabilidad as obs

EJEMPLOS = Path(__file__).resolve().parent.parent / "ejemplos"


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "EVENTOS_PATH", str(tmp_path / "eventos.jsonl"))
    with TestClient(main.app) as c:
        yield c


def test_metrics_publica_las_metricas(cliente):
    r = cliente.get("/metrics")
    assert r.status_code == 200
    assert "expedientes_http_requests_total" in r.text
    assert "expedientes_modelo_info" in r.text


def test_cada_respuesta_lleva_request_id(cliente):
    r = cliente.get("/salud")
    assert len(r.headers["X-Request-ID"]) == 12


def test_feedback_de_categoria_cuenta_y_no_cuenta_si_no_cambia(cliente):
    antes = obs.correccion.labels("CURP", "Equivalencia")._value.get()
    assert cliente.post("/feedback/categoria", json={"de": "CURP", "a": "Equivalencia"}).status_code == 200
    cliente.post("/feedback/categoria", json={"de": "CURP", "a": "CURP"})
    assert obs.correccion.labels("CURP", "Equivalencia")._value.get() == antes + 1


def test_inyeccion_de_fallas_apagada_por_defecto(cliente):
    assert cliente.post("/admin/fallas", json={"retardo_ocr_s": 5}).status_code == 404


def test_inyeccion_de_fallas_limita_el_retardo(cliente, monkeypatch):
    monkeypatch.setattr(main, "FALLAS_HABILITADAS", True)
    try:
        r = cliente.post("/admin/fallas", json={"retardo_ocr_s": 999})
        assert r.status_code == 200 and r.json()["retardo_ocr_s"] == 60.0
    finally:
        obs.FALLAS["retardo_ocr_s"] = 0.0


@pytest.mark.parametrize("ruta,esperada", [
    ("/alumnos/123/expediente/45/pdf", "/alumnos/{id}/expediente/{id}/pdf"),
    ("/alumnos/por-curp/ABCD010101HDFRRR09", "/alumnos/por-curp/{curp}"),
    ("/ruta/que/no/existe", "otra"),
])
def test_rutas_sin_datos_en_las_etiquetas(ruta, esperada):
    assert obs.normalizar_ruta(ruta) == esperada


def test_clasificar_registra_metricas_y_el_evento_no_lleva_datos_personales(cliente):
    pdf = EJEMPLOS / "acta_nacimiento_ficticia.pdf"
    r = cliente.post("/clasificar", files={"archivo": (pdf.name, pdf.read_bytes(), "application/pdf")}, data={"guardar": "false"})
    assert r.status_code == 200
    datos = r.json()
    assert datos["margen"] is not None
    assert 'expedientes_prediccion_total{clase="Actas de nacimiento"}' in cliente.get("/metrics").text
    eventos = Path(obs.EVENTOS_PATH).read_text(encoding="utf-8")
    assert '"tipo": "clasificacion"' in eventos
    assert datos["curp"] not in eventos and "EJEMPLO" not in eventos
    registro = json.loads(eventos.splitlines()[-1])
    assert {"margen", "palabras", "cobertura", "curp_verificada"} <= set(registro)


def test_modo_seguro_marca_todo_documento_para_revision(cliente):
    pdf = EJEMPLOS / "acta_nacimiento_ficticia.pdf"
    archivo = {"archivo": (pdf.name, pdf.read_bytes(), "application/pdf")}
    try:
        assert cliente.post("/admin/modo-seguro", json={"activo": True, "razon": "prueba"}).json()["activo"] is True
        r = cliente.post("/clasificar", files=archivo, data={"guardar": "false"}).json()
        assert r["modo_seguro"] is True and r["aviso"].startswith("MODO SEGURO")
        assert "expedientes_modo_seguro 1.0" in cliente.get("/metrics").text
    finally:
        cliente.post("/admin/modo-seguro", json={"activo": False})
    r = cliente.post("/clasificar", files=archivo, data={"guardar": "false"}).json()
    assert r["modo_seguro"] is False


def test_modo_seguro_caduca_a_las_24_horas(cliente):
    try:
        cliente.post("/admin/modo-seguro", json={"activo": True, "razon": "prueba"})
        main.MODO_SEGURO["desde"] -= 25 * 3600
        assert cliente.get("/admin/modo-seguro").json()["activo"] is False
    finally:
        cliente.post("/admin/modo-seguro", json={"activo": False})
