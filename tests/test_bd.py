"""Pruebas con la base de datos de PRUEBA (datos ficticios).
Se ejecutan solo si hay base configurada (DB_HOST), por ejemplo:

    docker compose run --rm api pytest -v
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import almacenamiento, main

pytestmark = pytest.mark.skipif(not os.getenv("DB_HOST"), reason="sin base de datos (DB_HOST)")

EJEMPLOS = Path(__file__).resolve().parent.parent / "ejemplos"
CURP_DEMO = "EELM060312MCHJPRA0"   # alumna ficticia id 1, sin documentos al inicio


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    # Las pruebas guardan sus PDFs en una carpeta temporal: no ensucian la carpeta expedientes/ real
    original = main.CONFIG_BD.carpeta_expedientes
    main.CONFIG_BD.carpeta_expedientes = str(tmp_path_factory.mktemp("expedientes") / "archivos")
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        main.CONFIG_BD.carpeta_expedientes = original


def _limpiar_alumna_demo():
    """Deja a la alumna de la demo sin documentos (por si una prueba anterior guardo alguno)."""
    bd = main.estado["bd"]
    for d in bd.archivos_del_alumno(1):
        bd.eliminar_archivo(d.id, 1)
        ruta = almacenamiento.ruta_de_registro(main.CONFIG_BD, d.nombre)
        if ruta and os.path.isfile(ruta):
            os.remove(ruta)


def test_salud_con_base(cliente):
    assert cliente.get("/salud").json()["base_datos"] == "conectada"


def test_buscar_alumno(cliente):
    r = cliente.get("/alumnos", params={"q": "EJEMPLO"})
    assert r.status_code == 200
    assert any(a["id"] == 1 and a["curp"] == CURP_DEMO for a in r.json())
    assert cliente.get("/alumnos", params={"q": CURP_DEMO}).json()[0]["id"] == 1


def test_expediente_en_orden(cliente):
    # Algun alumno ficticio con CURP, secundaria y acta: deben salir en ese orden
    for id_alumno in range(2, 101):
        docs = cliente.get(f"/alumnos/{id_alumno}/expediente").json()
        tipos = [d["tipo_reconocido"] for d in docs]
        if {"CURP", "Certificados Secundaria", "Actas de nacimiento"} <= set(tipos):
            assert tipos[:3] == ["CURP", "Certificados Secundaria", "Actas de nacimiento"]
            return
    pytest.fail("No hubo alumno con los tres documentos")


def test_clasificar_y_guardar_en_expediente(cliente):
    _limpiar_alumna_demo()
    try:
        archivo = (EJEMPLOS / "constancia_curp_ficticia.pdf").read_bytes()
        r = cliente.post("/clasificar", data={"guardar": "true"},
                         files={"archivo": ("constancia.pdf", archivo, "application/pdf")})
        d = r.json()
        assert r.status_code == 200, d
        assert d["alumno"]["id"] == 1 and d["encontrado_por"] == "curp"
        assert d["guardado_como"] == "1_CURP.pdf"

        # Segunda vez: ya lo tiene -> no se duplica
        r = cliente.post("/clasificar", data={"guardar": "true"},
                         files={"archivo": ("constancia.pdf", archivo, "application/pdf")})
        d = r.json()
        assert d["guardado_como"] is None and "ya tiene" in d["aviso"]
        assert [x["archivo"] for x in d["documentos_del_mismo_tipo"]] == ["1_CURP.pdf"]

        expediente = cliente.get("/alumnos/1/expediente").json()
        assert len(expediente) == 1 and expediente[0]["pdf_existe"]
    finally:
        _limpiar_alumna_demo()


def test_clasificar_sin_guardar_no_escribe(cliente):
    _limpiar_alumna_demo()
    archivo = (EJEMPLOS / "acta_nacimiento_ficticia.pdf").read_bytes()
    d = cliente.post("/clasificar", files={"archivo": ("acta.pdf", archivo, "application/pdf")}).json()
    assert d["alumno"]["id"] == 1 and d["guardado_como"] is None
    assert cliente.get("/alumnos/1/expediente").json() == []


# ---------------------------------------------------------------- flujo de revision (como la app de escritorio)
def test_tipos_y_salud_con_conteos(cliente):
    tipos = [t["categoria"] for t in cliente.get("/tipos").json()]
    assert tipos[:3] == ["CURP", "Certificados Secundaria", "Actas de nacimiento"] and len(tipos) == 6
    s = cliente.get("/salud").json()
    assert s["alumnos"] >= 100 and s["archivos"] >= 0 and s["base_nombre"]


def test_alumno_por_curp(cliente):
    assert cliente.get(f"/alumnos/por-curp/{CURP_DEMO.lower()}").json()[0]["id"] == 1
    assert cliente.get("/alumnos/por-curp/XXXX").status_code == 422


def test_guardar_reemplazar_adicional_ver_y_eliminar(cliente):
    _limpiar_alumna_demo()
    pdf = (EJEMPLOS / "constancia_curp_ficticia.pdf").read_bytes()
    archivo = {"archivo": ("x.pdf", pdf, "application/pdf")}
    try:
        d = cliente.get("/alumnos/1/destino", params={"categoria": "CURP"}).json()
        assert d["se_guardara_como"] == "1_CURP.pdf" and d["existentes"] == []

        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP"}, files=archivo)
        assert r.status_code == 200 and r.json()["guardado_como"] == "1_CURP.pdf"

        # Ya existe: "nuevo" se rechaza; hay que elegir reemplazar o adicional
        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP"}, files=archivo)
        assert r.status_code == 409
        existente = cliente.get("/alumnos/1/destino", params={"categoria": "CURP"}).json()["existentes"][0]
        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP", "modo": "reemplazar",
                                           "reemplazar_id": existente["id"]}, files=archivo)
        assert r.status_code == 200 and len(cliente.get("/alumnos/1/expediente").json()) == 1
        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP", "modo": "adicional"}, files=archivo)
        assert r.status_code == 200 and len(cliente.get("/alumnos/1/expediente").json()) == 2

        # Abrir el PDF y eliminarlo (queda en la carpeta de eliminados)
        docs = cliente.get("/alumnos/1/expediente").json()
        pdf_resp = cliente.get(f"/alumnos/1/expediente/{docs[0]['id']}/pdf")
        assert pdf_resp.status_code == 200 and pdf_resp.content.startswith(b"%PDF")
        assert cliente.delete(f"/alumnos/1/expediente/{docs[0]['id']}").status_code == 200
        assert len(cliente.get("/alumnos/1/expediente").json()) == 1
        assert cliente.delete("/alumnos/1/expediente/999999").status_code == 404
    finally:
        _limpiar_alumna_demo()


def test_guardar_valida_entradas(cliente):
    malo = {"archivo": ("x.pdf", b"no soy pdf", "application/pdf")}
    assert cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP"}, files=malo).status_code == 415
    pdf = {"archivo": ("x.pdf", b"%PDF-1.4 x", "application/pdf")}
    assert cliente.post("/guardar", data={"id_alumno": 1, "categoria": "OTRA"}, files=pdf).status_code == 422
    assert cliente.post("/guardar", data={"id_alumno": 9999, "categoria": "CURP"}, files=pdf).status_code == 404
