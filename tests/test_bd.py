"""Pruebas con la base de datos de PRUEBA (datos ficticios).
Se ejecutan solo si hay base configurada (DB_HOST), por ejemplo:

    docker compose run --rm api pytest -v
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import almacenamiento, main
from app.motor_ocr import digito_verificador

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
    assert tipos[:3] == ["CURP", "Certificados Secundaria", "Actas de nacimiento"] and len(tipos) == 7
    assert tipos[-1] == "Duplicado"   # solo manual: la IA no lo detecta
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


# ---------------------------------------------------------------- Fase III: duplicados
def _pdf(nombre="x.pdf"):
    return {"archivo": (nombre, (EJEMPLOS / "constancia_curp_ficticia.pdf").read_bytes(), "application/pdf")}


def test_duplicado_con_nombre_que_lleva_el_id(cliente):
    _limpiar_alumna_demo()
    try:
        # Primero el documento "normal" para que ya exista
        assert cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Certificado Final"},
                            files=_pdf()).status_code == 200
        d = cliente.get("/alumnos/1/destino", params={"categoria": "Certificado Final"}).json()
        assert d["prefijo"] == "1_" and d["sugerencia_duplicado"] == "DUPLICADO" and len(d["existentes"]) == 1

        # Nombres que NO sirven: sin el id del alumno, vacio, o con simbolos prohibidos
        for malo in ("Duplicado", "1_", "", "1_a/b", "2_DUPLICADO"):
            r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Certificado Final",
                                               "modo": "personalizado", "nombre": malo}, files=_pdf())
            assert r.status_code == 422, (malo, r.text)

        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Certificado Final",
                                           "modo": "personalizado", "nombre": "1_DUPLICADO"}, files=_pdf())
        assert r.status_code == 200 and r.json()["guardado_como"] == "1_DUPLICADO.pdf"

        # El mismo nombre otra vez: rechazado; y la sugerencia avanza a "DUPLICADO 2"
        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Certificado Final",
                                           "modo": "personalizado", "nombre": "1_DUPLICADO"}, files=_pdf())
        assert r.status_code == 422 and "Ya existe" in r.json()["detail"]
        d = cliente.get("/alumnos/1/destino", params={"categoria": "Certificado Final"}).json()
        assert d["sugerencia_duplicado"] == "DUPLICADO 2"
        assert len(cliente.get("/alumnos/1/expediente").json()) == 2
    finally:
        _limpiar_alumna_demo()


def test_categoria_duplicado_se_elige_a_mano(cliente):
    _limpiar_alumna_demo()
    try:
        # No choca con "Certificado Final": un duplicado no cuenta como "ya tiene este documento"
        assert cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Certificado Final"},
                            files=_pdf()).status_code == 200
        d = cliente.get("/alumnos/1/destino", params={"categoria": "Duplicado"}).json()
        assert d["existentes"] == [] and d["se_guardara_como"] == "1_DUPLICADO.pdf"
        r1 = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Duplicado"}, files=_pdf())
        r2 = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "Duplicado"}, files=_pdf())
        assert (r1.status_code, r2.status_code) == (200, 200)
        assert [r1.json()["guardado_como"], r2.json()["guardado_como"]] == ["1_DUPLICADO.pdf", "1_DUPLICADO_2.pdf"]
        tipos_bd = {d["tipo_capturado"] for d in cliente.get("/alumnos/1/expediente").json()}
        assert tipos_bd == {"CERT FINAL", "DUPLICADO"}
    finally:
        _limpiar_alumna_demo()


# ---------------------------------------------------------------- Fase III: corregir CURP
def test_corregir_curp(cliente):
    alumno = next(a for a in cliente.get("/alumnos", params={"q": "CARRASCO"}).json() if a["id"] == 2)
    curp_vieja = alumno["curp"]
    base17 = "ZZZZ000101HCHXXX0"
    nueva = base17 + digito_verificador(base17)
    try:
        # CURP con digito verificador incorrecto o formato malo: no se acepta
        malo = nueva[:-1] + ("0" if nueva[-1] != "0" else "1")
        assert cliente.post("/alumnos/2/curp", json={"curp": malo}).status_code == 422
        assert cliente.post("/alumnos/2/curp", json={"curp": "XXXX"}).status_code == 422
        # La de otro alumno: se rechaza (la CURP es unica)
        assert cliente.post("/alumnos/2/curp", json={"curp": CURP_DEMO}).status_code == 409
        # Alumno inexistente
        assert cliente.post("/alumnos/99999/curp", json={"curp": nueva}).status_code == 404

        r = cliente.post("/alumnos/2/curp", json={"curp": nueva.lower()})
        assert r.status_code == 200 and r.json()["curp"] == nueva
        assert cliente.get(f"/alumnos/por-curp/{nueva}").json()[0]["id"] == 2
        assert cliente.post("/alumnos/2/curp", json={"curp": nueva}).status_code == 422   # ya es esa
        bitacora = Path(main.CONFIG_BD.carpeta_expedientes).parent / "registro_cambios_curp.csv"
        texto = bitacora.read_text(encoding="utf-8-sig")
        assert curp_vieja in texto and nueva in texto
    finally:
        main.estado["bd"].actualizar_curp(2, nueva, curp_vieja)   # deja la base como estaba
    assert cliente.get(f"/alumnos/por-curp/{curp_vieja}").json()[0]["id"] == 2


# ---------------------------------------------------------------- Fase III: respaldos
def _esperar_fin(cliente, segundos=60):
    import time
    fin = time.time() + segundos
    while time.time() < fin:
        e = cliente.get("/respaldo/estado").json()
        if not e["activo"]:
            return e
        time.sleep(0.3)
    pytest.fail("El respaldo no termino a tiempo")


def test_respaldos_deshabilitados_sin_carpeta(cliente, monkeypatch):
    monkeypatch.setattr(main, "RESPALDOS_DIR", "")
    assert cliente.post("/respaldo/bd").status_code == 404
    assert cliente.get("/respaldo/estado").status_code == 404
    assert cliente.get("/salud").json()["respaldos"] is False


def test_respaldo_de_la_base_de_datos(cliente, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RESPALDOS_DIR", str(tmp_path / "respaldos"))
    assert cliente.get("/salud").json()["respaldos"] is True
    assert cliente.post("/respaldo/bd").status_code == 200
    e = _esperar_fin(cliente)
    assert e["error"] is None, e
    r = e["resultado"]
    tablas = {t["tabla"]: t["filas"] for t in r["tablas"]}
    assert tablas["alumnos"] >= 100 and "archivos" in tablas
    assert [x["nombre"] for x in e["respaldos"]] == [r["archivo"]]

    sql = cliente.get(f"/respaldo/descargar/{r['archivo']}")
    assert sql.status_code == 200 and "CREATE TABLE" in sql.text and "EJEMPLO" in sql.text
    # Solo se descargan respaldos hechos por el sistema (nada de rutas ni otros archivos)
    assert cliente.get("/respaldo/descargar/passwd").status_code == 404
    assert cliente.get("/respaldo/descargar/..%2f..%2fetc%2fpasswd").status_code == 404


def test_respaldo_de_archivos_en_zip(cliente, tmp_path, monkeypatch):
    import zipfile
    _limpiar_alumna_demo()
    monkeypatch.setattr(main, "RESPALDOS_DIR", str(tmp_path / "respaldos"))
    try:
        assert cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP"}, files=_pdf()).status_code == 200
        assert cliente.post("/respaldo/archivos").status_code == 200
        e = _esperar_fin(cliente)
        assert e["error"] is None, e
        ruta = tmp_path / "respaldos" / e["resultado"]["archivo"]
        assert ruta.suffix in (".zip", ".rar") and e["resultado"]["archivos"] >= 1
        if ruta.suffix == ".zip":
            z = zipfile.ZipFile(ruta)
            assert z.testzip() is None and any(n.endswith("1_CURP.pdf") for n in z.namelist())
    finally:
        _limpiar_alumna_demo()


# ---------------------------------------------------------------- Fase III: roles con la base de datos
def test_roles_con_base_de_datos(cliente, tmp_path, monkeypatch):
    claves = {"administrador": "adm-p", "operador": "ope-p", "consultor": "con-p"}
    monkeypatch.setattr(main, "CLAVES", claves)
    monkeypatch.setattr(main, "RESPALDOS_DIR", str(tmp_path / "respaldos"))
    main.intentos_fallidos.clear()

    def entrar(rol):
        cliente.cookies.clear()
        assert cliente.post("/api/login", json={"usuario": rol, "clave": claves[rol]}).status_code == 200

    _limpiar_alumna_demo()
    try:
        # OPERADOR: guarda (queda su nombre en la BD), pero no respalda
        entrar("operador")
        r = cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP"}, files=_pdf())
        assert r.status_code == 200 and r.json()["guardado_como"] == "1_CURP.pdf"
        con = main.estado["bd"]._conectar()
        try:
            with con.cursor() as cur:
                cur.execute("SELECT descripcion FROM archivos WHERE nombre = %s", ("1_CURP.pdf",))
                assert "Operador" in cur.fetchone()[0]
        finally:
            con.close()
        assert cliente.post("/respaldo/bd").status_code == 403

        # CONSULTOR: consulta y ve el PDF, pero no guarda, ni elimina, ni corrige, ni respalda
        entrar("consultor")
        docs = cliente.get("/alumnos/1/expediente").json()
        assert len(docs) == 1
        pdf = cliente.get(f"/alumnos/1/expediente/{docs[0]['id']}/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert cliente.get("/alumnos", params={"q": "EJEMPLO"}).status_code == 200
        assert cliente.post("/guardar", data={"id_alumno": 1, "categoria": "CURP", "modo": "adicional"},
                            files=_pdf()).status_code == 403
        assert cliente.delete(f"/alumnos/1/expediente/{docs[0]['id']}").status_code == 403
        assert cliente.post("/alumnos/1/curp", json={"curp": "ZZZZ000101HCHXXX04"}).status_code == 403
        assert cliente.post("/respaldo/bd").status_code == 403
        assert len(cliente.get("/alumnos/1/expediente").json()) == 1        # nada cambio

        # OPERADOR: si puede eliminar documentos
        entrar("operador")
        assert cliente.delete(f"/alumnos/1/expediente/{docs[0]['id']}").status_code == 200
        assert cliente.get("/alumnos/1/expediente").json() == []

        # ADMINISTRADOR: respalda; el consultor no puede descargar el respaldo
        entrar("administrador")
        assert cliente.post("/respaldo/bd").status_code == 200
        e = _esperar_fin(cliente)
        assert e["error"] is None, e
        nombre = e["resultado"]["archivo"]
        assert cliente.get(f"/respaldo/descargar/{nombre}").status_code == 200
        entrar("consultor")
        assert cliente.get(f"/respaldo/descargar/{nombre}").status_code == 403
    finally:
        cliente.cookies.clear()
        monkeypatch.setattr(main, "CLAVES", {})
        _limpiar_alumna_demo()
