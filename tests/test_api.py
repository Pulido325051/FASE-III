"""Pruebas de la API. Usan solo los PDFs FICTICIOS de la carpeta ejemplos/.

    pytest -v                                  (local)
    docker compose run --rm api pytest -v      (dentro del contenedor)
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from types import SimpleNamespace

from app import main, reglas

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


# ---------------------------------------------------------------- Fase III (no necesitan base de datos)
def test_tipos_incluye_duplicado_solo_manual(cliente):
    tipos = cliente.get("/tipos").json()
    assert [t["categoria"] for t in tipos][-1] == "Duplicado"
    assert [t["categoria"] for t in tipos if t["manual"]] == ["Duplicado"]
    # No es una clase del modelo: la IA nunca lo propone
    assert "Duplicado" not in cliente.get("/salud").json()["categorias"]


def _alumno(curp="GOTD070116MCHNRSA0"):
    return SimpleNamespace(nombre_completo="DEISY ADILENE GONZALEZ TORRES", curp=curp)


def test_alumno_por_nombre_sin_curp_no_pide_revision():
    ok = reglas.motivo_nombre_dudoso(_alumno(), None, "DEISY ADILENE GONZALEZ TORRES", "16 DE ENERO DE 2007")
    assert ok is None
    # sin fecha leida tambien es suficiente
    assert reglas.motivo_nombre_dudoso(_alumno(), None, "DEISY ADILENE GONZALEZ TORRES", None) is None


def test_alumno_por_nombre_pide_revision_si_hay_duda():
    # nombre parcial
    assert "no coincide por completo" in reglas.motivo_nombre_dudoso(_alumno(), None, "DEISY GONZALEZ", None)
    # la fecha del documento no es la de la CURP del alumno
    assert "fecha de nacimiento" in reglas.motivo_nombre_dudoso(
        _alumno(), None, "DEISY ADILENE GONZALEZ TORRES", "02 DE MARZO DE 2008")
    # el documento si traia CURP pero no estaba en la BD
    assert "no esta en la BD" in reglas.motivo_nombre_dudoso(
        _alumno(), "GOTD070116MCHNRSA9", "DEISY ADILENE GONZALEZ TORRES", None)


def test_contrasena_de_acceso(cliente, monkeypatch):
    monkeypatch.setattr(main, "APP_CLAVE", "Secreta-2026")
    assert cliente.get("/salud").json()["requiere_clave"] is True     # publica: la pagina necesita saberlo
    assert cliente.get("/").status_code == 200
    sin = cliente.get("/api/sesion").json()                            # publica: la pagina pregunta si ya hay sesion
    assert sin == {"usuario": None, "requiere_clave": True}
    assert cliente.get("/tipos").status_code == 401                    # protegido
    assert cliente.post("/respaldo/bd").status_code == 401
    assert cliente.post("/api/login", json={"usuario": "Nancy", "clave": "mal"}).status_code == 401
    assert cliente.get("/tipos").status_code == 401
    r = cliente.post("/api/login", json={"usuario": "Nancy", "clave": "Secreta-2026"})
    assert r.status_code == 200 and r.json()["usuario"] == "Nancy"
    assert cliente.get("/tipos").status_code == 200                    # con la cookie de sesion
    assert cliente.get("/api/sesion").json()["usuario"] == "Nancy"
    cliente.post("/api/logout")
    assert cliente.get("/tipos").status_code == 401
    cliente.cookies.clear()


def test_contrasena_con_hash_del_escritorio(cliente, monkeypatch):
    import hashlib
    sal = bytes.fromhex("fa906f56ad53ee49e0b245d2ba8504cd")
    h = hashlib.pbkdf2_hmac("sha256", "MiClave".encode(), sal, 200000).hex()
    monkeypatch.setattr(main, "APP_CLAVE", f"pbkdf2_sha256${200000}${sal.hex()}${h}")
    assert cliente.post("/api/login", json={"usuario": "X", "clave": "otra"}).status_code == 401
    assert cliente.post("/api/login", json={"usuario": "X", "clave": "MiClave"}).status_code == 200
    cliente.post("/api/logout")
    cliente.cookies.clear()
