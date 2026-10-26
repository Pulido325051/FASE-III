"""Pruebas de la API. Usan solo los PDFs FICTICIOS de la carpeta ejemplos/.

    pytest -v                                  (local)
    docker compose run --rm api pytest -v      (dentro del contenedor)
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

EJEMPLOS = Path(__file__).resolve().parent.parent / "ejemplos"
CURP_FICTICIA = "EELM060312MCHJPRA0"


@pytest.fixture(scope="module")
def cliente():
    with TestClient(main.app) as c:   # "with" ejecuta el arranque: carga el modelo
        yield c


def subir(cliente, nombre, contenido=None):
    datos = contenido if contenido is not None else (EJEMPLOS / nombre).read_bytes()
    return cliente.post("/clasificar", files={"archivo": (nombre, datos, "application/pdf")})


def test_salud(cliente):
    r = cliente.get("/salud")
    assert r.status_code == 200
    s = r.json()
    assert s["estado"] == "ok" and s["modelo_cargado"]
    assert set(s["categorias"]) == {"Actas de nacimiento", "CURP", "Certificado Final",
                                    "Certificado Parcial", "Certificados Secundaria", "Equivalencia"}


def test_pagina_principal(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Expedientes - Control Escolar" in r.text


def test_documentacion(cliente):
    assert cliente.get("/docs").status_code == 200
    assert "/clasificar" in cliente.get("/openapi.json").json()["paths"]


def test_constancia_curp(cliente):
    r = subir(cliente, "constancia_curp_ficticia.pdf")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tipo_documento"] == "CURP"
    assert d["curp"] == CURP_FICTICIA and d["curp_verificada"]
    assert d["nombre"] == "MARIA FERNANDA EJEMPLO LOPEZ"
    assert d["fecha_nacimiento"] == "12 DE MARZO DE 2006"


def test_acta_nacimiento(cliente):
    r = subir(cliente, "acta_nacimiento_ficticia.pdf")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tipo_documento"] == "Actas de nacimiento"
    assert d["curp"] == CURP_FICTICIA and d["curp_verificada"]


def test_rechaza_archivo_que_no_es_pdf(cliente):
    r = subir(cliente, "foto.pdf", b"esto no es un pdf")
    assert r.status_code == 415


def test_rechaza_archivo_muy_grande(cliente, monkeypatch):
    monkeypatch.setattr(main, "MAX_MB", 0.001)   # 1 KB para la prueba
    r = subir(cliente, "constancia_curp_ficticia.pdf")
    assert r.status_code == 413


def test_pdf_danado(cliente):
    r = subir(cliente, "danado.pdf", b"%PDF-1.4\nbasura que no es un pdf real")
    assert r.status_code == 422
