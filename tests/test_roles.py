"""Pruebas de los tres roles (administrador, operador, consultor). No necesitan base de datos.

Lo importante: los permisos se aplican en el SERVIDOR (403), no solo ocultando botones en la pantalla.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main

CLAVES = {"administrador": "adm-prueba", "operador": "ope-prueba", "consultor": "con-prueba"}

# Que debe poder hacer cada rol: {rol: {nivel: permitido}}
ESPERADO = {
    "administrador": {"consultar": True, "capturar": True, "respaldar": True},
    "operador": {"consultar": True, "capturar": True, "respaldar": False},
    "consultor": {"consultar": True, "capturar": False, "respaldar": False},
}
# Una peticion de ejemplo por nivel: (metodo, ruta, argumentos). Si el permiso alcanza, la peticion SIGUE su camino
# y responde otra cosa (415, 422, 404...); si no alcanza, responde 403.
# Estan pensadas para NO tener efectos (no guardan, no eliminan, no cambian la CURP, no respaldan): fallan a proposito
# despues de revisar el permiso (tipo invalido, documento inexistente, CURP invalida, respaldos apagados).
PETICIONES = {
    "consultar": [("GET", "/tipos", {}), ("GET", "/alumnos", {"params": {"q": "EJEMPLO"}}),
                  ("GET", "/alumnos/1/expediente", {}), ("GET", "/alumnos/1/expediente/1/pdf", {})],
    "capturar": [("POST", "/clasificar", {"files": {"archivo": ("x.pdf", b"no soy pdf", "application/pdf")}}),
                 ("POST", "/guardar", {"data": {"id_alumno": 1, "categoria": "TIPO-QUE-NO-EXISTE"},
                                       "files": {"archivo": ("x.pdf", b"%PDF-1.4", "application/pdf")}}),
                 ("GET", "/alumnos/1/destino", {"params": {"categoria": "TIPO-QUE-NO-EXISTE"}}),
                 ("DELETE", "/alumnos/1/expediente/999999", {}),
                 ("POST", "/alumnos/1/curp", {"json": {"curp": "XXXX"}})],
    "respaldar": [("POST", "/respaldo/bd", {}), ("POST", "/respaldo/archivos", {}), ("GET", "/respaldo/estado", {}),
                  ("POST", "/respaldo/cancelar", {}), ("GET", "/respaldo/descargar/BD_x.sql", {})],
}


@pytest.fixture(scope="module")
def cliente():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def usuarios_activos(monkeypatch):
    monkeypatch.setattr(main, "CLAVES", dict(CLAVES))
    monkeypatch.setattr(main, "RESPALDOS_DIR", "")   # que ninguna peticion de estas pruebas inicie un respaldo de verdad
    main.intentos_fallidos.clear()
    yield
    main.intentos_fallidos.clear()


def entrar(cliente, rol, clave=None):
    cliente.cookies.clear()
    return cliente.post("/api/login", json={"usuario": rol, "clave": clave or CLAVES[rol]})


def test_sin_contrasenas_la_web_queda_abierta(cliente, monkeypatch):
    monkeypatch.setattr(main, "CLAVES", {})
    cliente.cookies.clear()
    s = cliente.get("/api/sesion").json()
    assert s["requiere_clave"] is False and s["permisos"] == ["consultar", "capturar", "respaldar"]
    assert cliente.get("/tipos").status_code == 200
    assert cliente.get("/salud").json()["requiere_clave"] is False


def test_nivel_requerido_por_ruta():
    assert main.nivel_requerido("GET", "/alumnos") == "consultar"
    assert main.nivel_requerido("GET", "/alumnos/1/expediente/3/pdf") == "consultar"
    assert main.nivel_requerido("POST", "/clasificar") == "capturar"
    assert main.nivel_requerido("POST", "/guardar") == "capturar"
    assert main.nivel_requerido("DELETE", "/alumnos/1/expediente/3") == "capturar"
    assert main.nivel_requerido("GET", "/alumnos/1/destino") == "capturar"
    assert main.nivel_requerido("POST", "/alumnos/1/curp") == "capturar"
    assert main.nivel_requerido("GET", "/respaldo/descargar/BD_x.sql") == "respaldar"
    assert main.nivel_requerido("POST", "/respaldo/bd") == "respaldar"


def test_entrar_con_cada_usuario(cliente):
    for rol, esperado in ESPERADO.items():
        r = entrar(cliente, rol)
        assert r.status_code == 200, r.text
        assert r.json()["rol"] == rol
        assert set(r.json()["permisos"]) == {n for n, ok in esperado.items() if ok}
        assert cliente.get("/api/sesion").json()["usuario"] == main.ROLES[rol]["nombre"]


def test_usuario_o_contrasena_incorrectos(cliente):
    assert entrar(cliente, "operador", "mal").status_code == 401
    assert entrar(cliente, "nadie", "ope-prueba").status_code == 401
    assert entrar(cliente, "ADMINISTRADOR ", CLAVES["administrador"]).status_code == 200   # mayusculas/espacios no importan
    # la contrasena de un rol no sirve para otro
    assert entrar(cliente, "consultor", CLAVES["administrador"]).status_code == 401


def test_sin_sesion_nada_funciona(cliente):
    cliente.cookies.clear()
    assert cliente.get("/salud").status_code == 200 and cliente.get("/").status_code == 200   # publicas
    assert cliente.get("/api/sesion").json()["usuarios"] == [
        {"usuario": rol, "nombre": main.ROLES[rol]["nombre"], "descripcion": main.ROLES[rol]["descripcion"]}
        for rol in ESPERADO]
    for nivel, lista in PETICIONES.items():
        for metodo, ruta, args in lista:
            assert cliente.request(metodo, ruta, **args).status_code == 401, (metodo, ruta)


@pytest.mark.parametrize("rol", list(ESPERADO))
def test_matriz_de_permisos(cliente, rol):
    assert entrar(cliente, rol).status_code == 200
    for nivel, permitido in ESPERADO[rol].items():
        for metodo, ruta, args in PETICIONES[nivel]:
            codigo = cliente.request(metodo, ruta, **args).status_code
            if permitido:
                assert codigo != 403, f"{rol} deberia poder {metodo} {ruta} y recibio 403"
            else:
                assert codigo == 403, f"{rol} NO deberia poder {metodo} {ruta} y recibio {codigo}"
    # y el mensaje de rechazo dice el rol
    if not all(ESPERADO[rol].values()):
        r = cliente.post("/respaldo/bd")
        assert r.status_code == 403 and main.ROLES[rol]["nombre"] in r.json()["detail"]


def test_cerrar_sesion(cliente):
    entrar(cliente, "operador")
    assert cliente.get("/tipos").status_code == 200
    cliente.post("/api/logout")
    assert cliente.get("/tipos").status_code == 401


def test_contrasena_con_hash_del_escritorio(cliente, monkeypatch):
    sal = bytes.fromhex("fa906f56ad53ee49e0b245d2ba8504cd")
    h = hashlib.pbkdf2_hmac("sha256", "MiClave".encode(), sal, 200000).hex()
    monkeypatch.setattr(main, "CLAVES", {"operador": f"pbkdf2_sha256${200000}${sal.hex()}${h}"})
    assert entrar(cliente, "operador", "otra").status_code == 401
    assert entrar(cliente, "operador", "MiClave").status_code == 200
    # con solo un usuario definido, los demas no pueden entrar
    assert entrar(cliente, "administrador", "MiClave").status_code == 401
    assert [u["usuario"] for u in cliente.get("/api/sesion").json()["usuarios"]] == ["operador"]


def test_bloqueo_tras_cinco_intentos_fallidos(cliente):
    for _ in range(5):
        assert entrar(cliente, "operador", "mal").status_code == 401
    assert entrar(cliente, "operador").status_code == 429          # ni la buena pasa mientras dura el bloqueo
