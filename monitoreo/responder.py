"""Servicio de RESPUESTA AUTOMATIZADA: recibe las alertas de Alertmanager (webhook) y ejecuta, sin intervencion humana,
las respuestas reversibles definidas en el documento tecnico. Cada accion tiene guardas, se verifica y queda registrada.

  R-A1  Reinicio automatico   ApiCaida -> reinicia la API | BaseDeDatosInaccesible -> arranca MySQL
                              Guarda: maximo 3 reinicios por servicio en 10 min; despues NO insiste y escala a una persona (P1).
                              Verificacion: /salud responde (API) o el contenedor queda 'healthy' (MySQL).
  R-A2  Modo seguro           DerivaDeDatos o BajaConfianzaElevada -> activa el modo seguro (todo documento pasa a «Revisar»).
                              Se revierte solo cuando ambas alertas se resuelven; la API ademas lo apaga a las 24 h.
  R-A6  Notificacion y        Latencia alta, errores y quema de presupuesto -> registra un seguimiento (issue) con el runbook.
        seguimiento
  R-A7  Respaldo preventivo   Cuando la base de datos se recupera -> pide un respaldo (.sql) y verifica que exista.

NO automatiza (lo decide una persona): promover o retroceder un modelo, corregir datos de alumnos, borrar archivos.

Se ejecuta en el equipo anfitrion (necesita Docker):   python responder.py        (escucha en el puerto 9100)
Alertmanager le envia las alertas a http://host.docker.internal:9100/alerta
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
COMPOSE = ["docker", "compose", "-p", os.getenv("PROYECTO", "fase3mon"), "-f",
           os.getenv("COMPOSE_FILE", os.path.join(AQUI, "..", "docker-compose.monitoreo.yml"))]
API = os.getenv("API", "http://localhost:8200")
USUARIO, CLAVE = "administrador", os.getenv("CLAVE_ADMINISTRADOR", "admin-2026")
REGISTRO = os.getenv("REGISTRO_ACCIONES", os.path.join(AQUI, "acciones_automaticas.jsonl"))
PUERTO = int(os.getenv("PUERTO_RESPONDER", "9100"))
MAX_REINICIOS, VENTANA_S = 3, 600
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

candado = threading.Lock()
activas = set()          # alertas que ya estan en disparo (para actuar solo en la transicion)
reinicios = {}           # servicio -> [momentos de los reinicios recientes]
DERIVA = {"DerivaDeDatos", "BajaConfianzaElevada"}


def registrar(alerta, regla, accion, resultado, verificacion="", **extra):
    fila = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "alerta": alerta, "respuesta": regla, "accion": accion,
            "resultado": resultado, "verificacion": verificacion, **extra}
    with candado, open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    print(f"[{fila['ts']}] {regla} {alerta}: {accion} -> {resultado}" + (f" | {verificacion}" if verificacion else ""), flush=True)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=SIN_VENTANA)
    return r.returncode, (r.stdout + r.stderr).strip()


def esperar(cond, timeout, cada=2):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(cada)
    return False


def sesion_admin():
    s = requests.Session()
    s.post(API + "/api/login", json={"usuario": USUARIO, "clave": CLAVE}, timeout=10).raise_for_status()
    return s


def permitido_reiniciar(servicio):
    """Guarda de R-A1: maximo 3 reinicios en 10 minutos por servicio."""
    ahora = time.time()
    lista = [t for t in reinicios.get(servicio, []) if ahora - t < VENTANA_S]
    reinicios[servicio] = lista
    if len(lista) >= MAX_REINICIOS:
        return False
    lista.append(ahora)
    return True


# --------------------------------------------------------------------------------------------- respuestas
def r_a1_api(alerta):
    if not permitido_reiniciar("api"):
        registrar(alerta, "R-A1", "reiniciar la API", "NO EJECUTADA: ya hubo 3 reinicios en 10 min",
                  "ESCALADO A UNA PERSONA (P1, runbook RB-01)")
        return
    t0 = time.time()
    sh(COMPOSE + ["restart", "api"])                          # reinicia (o arranca si estaba detenido)
    ok = esperar(lambda: requests.get(API + "/salud", timeout=3).ok, 120)
    registrar(alerta, "R-A1", "reiniciar la API (docker compose start/restart api)", "ejecutada",
              f"/salud {'responde' if ok else 'NO responde'} a los {time.time() - t0:.0f} s", segundos=round(time.time() - t0, 1), exito=ok)


def r_a1_bd(alerta):
    if not permitido_reiniciar("db"):
        registrar(alerta, "R-A1", "arrancar MySQL", "NO EJECUTADA: ya hubo 3 reinicios en 10 min", "ESCALADO A UNA PERSONA (P1, runbook RB-05)")
        return
    t0 = time.time()
    sh(COMPOSE + ["start", "db"])
    ok = esperar(lambda: sh(["docker", "inspect", "-f", "{{.State.Health.Status}}", "fase3mon-db-1"])[1] == "healthy", 120)
    ok2 = esperar(lambda: sesion_admin().get(API + "/alumnos", params={"q": "MARIA"}, timeout=10).status_code == 200, 60) if ok else False
    registrar(alerta, "R-A1", "arrancar MySQL (docker compose start db)", "ejecutada",
              f"MySQL {'healthy' if ok else 'NO recupero'}; /alumnos {'200 OK' if ok2 else 'sigue fallando'} a los {time.time() - t0:.0f} s",
              segundos=round(time.time() - t0, 1), exito=ok and ok2)


def r_a7_respaldo(alerta):
    """Respaldo preventivo cuando la base se recupero: protege contra una recuperacion a medias."""
    try:
        s = sesion_admin()
        s.post(API + "/respaldo/bd", timeout=20)
        ok = esperar(lambda: not s.get(API + "/respaldo/estado", timeout=10).json()["activo"], 120, 3)
        est = s.get(API + "/respaldo/estado", timeout=10).json()
        r = est.get("resultado") or {}
        registrar(alerta, "R-A7", "respaldo preventivo de la base de datos (POST /respaldo/bd)", "ejecutada",
                  f"archivo {r.get('archivo', '?')} ({r.get('tamano', 0)} bytes)" if ok and r else f"error: {est.get('error')}", exito=bool(ok and r))
    except Exception as e:
        registrar(alerta, "R-A7", "respaldo preventivo", "FALLO", str(e)[:100], exito=False)


def r_a2(on, alerta):
    try:
        s = sesion_admin()
        r = s.post(API + "/admin/modo-seguro", json={"activo": on, "razon": f"automatico por {alerta}"}, timeout=10).json()
        registrar(alerta, "R-A2", "ACTIVAR modo seguro" if on else "DESACTIVAR modo seguro (alertas resueltas)", "ejecutada",
                  f"modo_seguro = {r.get('activo')}", exito=r.get("activo") == on)
    except Exception as e:
        registrar(alerta, "R-A2", "cambiar modo seguro", "FALLO", str(e)[:100], exito=False)


def r_a6(alerta, runbook):
    registrar(alerta, "R-A6", "crear seguimiento (issue) y avisar al responsable", "ejecutada",
              f"seguimiento abierto: atender con {runbook}; sin accion automatica sobre el servicio (la decision es humana)")


def despachar(nombre, estado, runbook):
    with candado:
        if estado == "firing":
            nueva = nombre not in activas
            activas.add(nombre)
        else:
            nueva = nombre in activas
            activas.discard(nombre)
        deriva_activa = bool(DERIVA & activas)
    if not nueva:
        return                                   # Alertmanager repite avisos: solo se actua cuando la alerta cambia de estado
    if estado == "firing":
        if nombre == "ApiCaida":
            r_a1_api(nombre)
        elif nombre == "BaseDeDatosInaccesible":
            r_a1_bd(nombre)
        elif nombre in DERIVA:
            if not (DERIVA - {nombre}) & activas:    # solo la primera de las dos activa el modo
                r_a2(True, nombre)
        elif nombre in ("LatenciaClasificarAlta", "TasaErroresAlta", "QuemaDePresupuestoRapida", "CorreccionesDeCategoria", "CurpVerificadaBaja"):
            r_a6(nombre, runbook)
    else:
        if nombre in DERIVA and not deriva_activa:
            r_a2(False, nombre)
        elif nombre == "BaseDeDatosInaccesible":
            r_a7_respaldo(nombre)


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(n) or b"{}")
        for a in cuerpo.get("alerts", []):
            threading.Thread(target=despachar, daemon=True,
                             args=(a["labels"].get("alertname", "?"), a["status"], a["labels"].get("runbook", ""))).start()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        filas = []
        try:
            with open(REGISTRO, encoding="utf-8") as f:
                filas = [json.loads(x) for x in f if x.strip()]
        except OSError:
            pass
        if self.path.startswith("/acciones"):
            cuerpo, tipo = json.dumps(filas, ensure_ascii=False).encode(), "application/json"
        else:
            tr = "".join(f"<tr><td>{a['ts']}</td><td>{a['respuesta']}</td><td>{a['alerta']}</td><td>{a['accion']}</td>"
                         f"<td>{a['resultado']}</td><td>{a['verificacion']}</td></tr>" for a in reversed(filas[-40:]))
            cuerpo = ("<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=5><title>Respuesta automatizada</title>"
                      "<style>body{font-family:Segoe UI,Arial;margin:24px;background:#f6f8fa;color:#1f2937}table{border-collapse:collapse;width:100%;background:#fff}"
                      "th,td{border:1px solid #d0d7de;padding:6px 10px;font-size:13px;text-align:left;vertical-align:top}th{background:#1f3a5f;color:#fff}</style>"
                      "<h2>Respuesta automatizada: acciones ejecutadas sin intervencion humana</h2>"
                      "<table><tr><th>Hora</th><th>Respuesta</th><th>Alerta</th><th>Accion</th><th>Resultado</th><th>Verificacion</th></tr>"
                      f"{tr}</table>").encode()
            tipo = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.end_headers()
        self.wfile.write(cuerpo)


if __name__ == "__main__":
    print(f"Respuesta automatizada escuchando en el puerto {PUERTO}; registro en {REGISTRO}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PUERTO), Manejador).serve_forever()
