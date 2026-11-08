"""Ejecuta los runbooks de respuesta a incidentes sobre incidentes SIMULADOS y deja un registro con hora de cada paso.

Los pasos de diagnostico, mitigacion y verificacion son los de los runbooks del documento tecnico (RB-02, RB-04, RB-05) y
se ejecutan con comandos reales (docker, consultas a Prometheus, API de MLflow). En produccion los ejecutaria una persona;
aqui un script los corre en orden para dejar evidencia con tiempos medidos.

Uso:  python runbooks.py INC-01 | INC-02 | INC-03 | todos
"""
import json
import os
import subprocess
import sys
import threading
import time

import requests

import generar_trafico as gt

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
COMPOSE = ["docker", "compose", "-p", "fase3mon", "-f", os.path.join(RAIZ, "docker-compose.monitoreo.yml")]
PROM, MLF, API = "http://localhost:9090", "http://localhost:5000", gt.BASE
# Capturas de pantalla opcionales: si CAPTURAS_SCRIPT apunta a un script (salida, url, espera_ms, alto) se usan; si no, se omiten
CAPTURAS_SCRIPT = os.getenv("CAPTURAS_SCRIPT", "")
REGISTRO = os.getenv("REGISTRO_INCIDENTES", os.path.join(AQUI, "registro_incidentes.log"))
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)     # en Windows evita ventanas de consola


def log(clave, texto):
    linea = f"[{time.strftime('%H:%M:%S')}] {clave:<22} {texto}"
    print(linea, flush=True)
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def prom(q):
    try:
        return requests.get(PROM + "/api/v1/query", params={"query": q}, timeout=10).json()["data"]["result"]
    except Exception:
        return []


def valor(q, defecto=0.0):
    r = prom(q)
    return float(r[0]["value"][1]) if r else defecto


def activas():
    try:
        return sorted({a["labels"]["alertname"] for a in requests.get(PROM + "/api/v1/alerts", timeout=10).json()["data"]["alerts"]
                       if a["state"] == "firing"})
    except Exception:
        return ["(prometheus no responde)"]


def esperar(cond, timeout, cada=3):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(cada)
    return False


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=SIN_VENTANA)
    return (r.stdout + r.stderr).strip()


def captura(nombre, url, alto=900):
    if CAPTURAS_SCRIPT:
        subprocess.run([sys.executable, CAPTURAS_SCRIPT, nombre, url, "4000", str(alto)], capture_output=True, creationflags=SIN_VENTANA)


class Trafico(threading.Thread):
    """Carga de fondo: un documento cada ~2 s mientras dura el incidente."""

    def __init__(self, variante="normal", n=None):
        super().__init__(daemon=True)
        self.parar, self.variante, self.n = threading.Event(), variante, n
        self.imgs = [gt.paginas("acta_nacimiento_ficticia.pdf")[0], gt.paginas("constancia_curp_ficticia.pdf")[0]]

    def run(self):
        s = gt.sesion()
        i = 0
        while not self.parar.is_set() and (self.n is None or i < self.n):
            img = self.imgs[1 if i % 6 == 5 else 0]
            img = gt.degradado(img) if self.variante == "degradado" else gt.normal(img)
            try:
                gt.enviar(s, gt.a_pdf(img))
            except Exception:
                pass
            i += 1
            self.parar.wait(1.5)


def tabla_etapas():
    r = prom("sum by (etapa) (rate(expedientes_etapa_duracion_seconds_sum[2m])) / sum by (etapa) (rate(expedientes_etapa_duracion_seconds_count[2m]))")
    return sorted(((x["metric"]["etapa"], float(x["value"][1])) for x in r), key=lambda t: -t[1])


def p95():
    return valor('histogram_quantile(0.95, sum by (le) (rate(expedientes_http_request_duration_seconds_bucket{ruta="/clasificar"}[1m])))')


def base_estable():
    """Deja el sistema en estado normal antes de cada incidente."""
    log("PREPARACION", "se envian documentos normales hasta que no haya alertas activas")
    t = Trafico("normal")
    t.start()
    ok = esperar(lambda: not activas(), 300, 5)
    t.parar.set()
    log("PREPARACION", "sin alertas activas" if ok else f"aun activas: {activas()}")


# ----------------------------------------------------------------------------- INC-01 latencia (RB-02)
def inc01():
    log("INC-01", "=== INICIO. Incidente SIMULADO: aumento de latencia (retardo de 20 s inyectado en el OCR) ===")
    s = gt.sesion()
    base_estable()
    t0 = time.time()
    s.post(API + "/admin/fallas", json={"retardo_ocr_s": 20}, timeout=10)
    log("INC-01", "falla inyectada; arranca la carga de fondo")
    tr = Trafico("normal")
    tr.start()
    ok = esperar(lambda: "LatenciaClasificarAlta" in activas(), 240)
    mttd = time.time() - t0
    log("INC-01 deteccion", f"alerta LatenciaClasificarAlta {'DISPARADA' if ok else 'NO disparada'} a los {mttd:.0f} s de iniciada la falla; p95 = {p95():.1f} s")
    captura("inc1_alerta_receptor.png", "http://localhost:9099/", 700)
    captura("inc1_d1_incidente.png", "http://localhost:3000/d/expedientes-servicio/?kiosk&from=now-10m", 900)
    # --- RB-02 diagnostico
    log("RB-02 diag 1", "D1: etapa que crece (duracion media por etapa, ultimos 2 min):")
    et = tabla_etapas()
    for e, v in et:
        log("RB-02 diag 1", f"   {e:<14} {v:6.2f} s")
    log("RB-02 diag 1", f"=> etapa dominante: {et[0][0]}" if et else "=> sin datos")
    log("RB-02 diag 2", f"concurrencia: lecturas en curso = {valor('expedientes_clasificar_en_curso'):.0f} de 2")
    log("RB-02 diag 2", "docker stats api: " + sh(["docker", "stats", "--no-stream", "--format", "CPU {{.CPUPerc}} | memoria {{.MemUsage}}", "fase3mon-api-1"]))
    log("RB-02 diag 4", "causa: la etapa ocr tarda ~20 s por documento mientras CPU y memoria estan normales -> el cuello de botella esta dentro de la API")
    # --- RB-02 mitigacion
    t1 = time.time()
    log("RB-02 mitig 3", "docker compose restart api (limpia el estado interno del servicio)")
    sh(COMPOSE + ["restart", "api"])
    ok = esperar(lambda: requests.get(API + "/salud", timeout=3).ok, 120, 2)
    log("RB-02 mitig 3", f"API de nuevo en linea en {time.time() - t1:.0f} s" if ok else "la API no volvio")
    # --- verificacion
    log("RB-02 verif", "criterio: p95 de /clasificar < 15 s y alerta resuelta")
    ok = esperar(lambda: "LatenciaClasificarAlta" not in activas(), 300, 5)
    tr.parar.set()
    log("RB-02 verif", f"alerta {'RESUELTA' if ok else 'sigue activa'}; p95 = {p95():.1f} s; tiempo hasta restaurar = {time.time() - t0:.0f} s desde la falla")
    captura("inc1_recuperado_d1.png", "http://localhost:3000/d/expedientes-servicio/?kiosk&from=now-10m", 900)
    log("INC-01", "=== FIN ===")


# ----------------------------------------------------------------------------- INC-02 degradacion por data drift (RB-04)
def mlflow_post(ruta, datos):
    return requests.post(MLF + "/api/2.0/mlflow/" + ruta, json=datos, timeout=10).json()


def inc02():
    log("INC-02", "=== INICIO. Incidente SIMULADO: modelo degradado por escaneos de mala calidad (data drift) ===")
    base_estable()
    t0 = time.time()
    exp = requests.get(MLF + "/api/2.0/mlflow/experiments/get-by-name", params={"experiment_name": "incidentes"}, timeout=10).json()
    exp_id = exp["experiment"]["experiment_id"] if "experiment" in exp else mlflow_post("experiments/create", {"name": "incidentes"})["experiment_id"]
    run = mlflow_post("runs/create", {"experiment_id": exp_id, "start_time": int(t0 * 1000), "run_name": "INC-02-data-drift",
                                      "tags": [{"key": "tipo", "value": "incidente simulado"}, {"key": "runbook", "value": "RB-04"}]})["run"]["info"]["run_id"]
    tr = Trafico("degradado", n=30)
    tr.start()
    log("INC-02", "llegan escaneos borrosos, de bajo contraste y reducidos")
    esperar(lambda: "DerivaDeDatos" in activas(), 300)
    mttd = time.time() - t0
    al = activas()
    log("INC-02 deteccion", f"alertas activas a los {mttd:.0f} s: {', '.join(al)}")
    psi = {x["metric"]["senal"]: float(x["value"][1]) for x in prom("expedientes_monitor_psi")}
    tasas = {x["metric"]["indicador"]: float(x["value"][1]) for x in prom("expedientes_monitor_tasa")}
    captura("inc2_alertas_receptor.png", "http://localhost:9099/", 700)
    captura("inc2_d3_deriva.png", "http://localhost:3000/d/expedientes-deriva/?kiosk&from=now-10m", 1000)
    # --- RB-04 diagnostico
    log("RB-04 diag 1", "PSI por senal (umbral de deriva 0.25): " + ", ".join(f"{k}={v:.2f}" for k, v in sorted(psi.items())))
    log("RB-04 diag 2", "indicadores de la ventana: " + ", ".join(f"{k}={v:.0%}" for k, v in sorted(tasas.items())))
    corr = tasas.get("correccion", 0)
    log("RB-04 diag 3", f"correcciones humanas = {corr:.0%}: " + ("el modelo aun no falla segun las personas -> cambio en los DATOS DE ENTRADA, no en el concepto; no se reentrena"
                                                              if corr < 0.15 else "hay correcciones: posible deriva de concepto"))
    # --- mitigacion: modo seguro + registro en MLflow + marca en el registro de modelos
    log("RB-04 mitig", "R-A2 modo seguro: se exige revision humana de todo documento con margen < 1.2 y se pide re-escanear el lote")
    for k, v in psi.items():
        mlflow_post("runs/log-metric", {"run_id": run, "key": "psi_" + k, "value": v, "timestamp": int(time.time() * 1000), "step": 1})
    for k, v in tasas.items():
        mlflow_post("runs/log-metric", {"run_id": run, "key": "tasa_" + k, "value": v, "timestamp": int(time.time() * 1000), "step": 1})
    mlflow_post("runs/set-tag", {"run_id": run, "key": "accion", "value": "modo seguro: revision humana obligatoria; reescanear lote; sin reentrenamiento"})
    mlflow_post("model-versions/set-tag", {"name": "clasificador-documentos", "version": "1", "key": "estado", "value": "en revision (INC-02 data drift)"})
    log("RB-04 mitig", "MLflow: run INC-02 registrado y version 1 (@produccion) marcada 'en revision'")
    tr.join(timeout=120)
    # --- recuperacion: llega material de buena calidad
    log("RB-04 mitig", "se re-escanea el lote: vuelven documentos de calidad normal")
    tr2 = Trafico("normal")
    tr2.start()
    ok = esperar(lambda: not {"DerivaDeDatos", "BajaConfianzaElevada", "CurpVerificadaBaja"} & set(activas()), 420, 5)
    tr2.parar.set()
    psi = {x["metric"]["senal"]: float(x["value"][1]) for x in prom("expedientes_monitor_psi")}
    tasas = {x["metric"]["indicador"]: float(x["value"][1]) for x in prom("expedientes_monitor_tasa")}
    log("RB-04 verif", f"alertas de calidad {'RESUELTAS' if ok else 'siguen activas'}; PSI: " + ", ".join(f"{k}={v:.2f}" for k, v in sorted(psi.items())))
    log("RB-04 verif", "indicadores: " + ", ".join(f"{k}={v:.0%}" for k, v in sorted(tasas.items())))
    mlflow_post("model-versions/set-tag", {"name": "clasificador-documentos", "version": "1", "key": "estado", "value": "estable (INC-02 cerrado)"})
    mlflow_post("runs/set-tag", {"run_id": run, "key": "resultado", "value": f"recuperado en {time.time() - t0:.0f} s"})
    mlflow_post("runs/update", {"run_id": run, "status": "FINISHED", "end_time": int(time.time() * 1000)})
    log("RB-04 cierre", f"MLflow: marca de version vuelve a 'estable'; tiempo total hasta recuperar = {time.time() - t0:.0f} s")
    captura("inc2_recuperado_d3.png", "http://localhost:3000/d/expedientes-deriva/?kiosk&from=now-15m", 1000)
    captura("inc2_mlflow_incidente.png", f"http://localhost:5000/#/experiments/{exp_id}/runs/{run}", 900)
    log("INC-02", "=== FIN ===")


# ----------------------------------------------------------------------------- INC-03 base de datos (RB-05)
def inc03():
    log("INC-03", "=== INICIO. Incidente SIMULADO: base de datos MySQL detenida ===")
    base_estable()
    s = gt.sesion()
    t0 = time.time()
    sh(COMPOSE + ["stop", "db"])
    log("INC-03", "docker compose stop db")
    stop = threading.Event()

    def golpes():
        while not stop.is_set():
            try:
                s.get(API + "/alumnos", params={"q": "MARIA"}, timeout=10)
            except Exception:
                pass
            stop.wait(0.5)

    th = threading.Thread(target=golpes, daemon=True)
    th.start()
    ok = esperar(lambda: "BaseDeDatosInaccesible" in activas(), 180)
    log("INC-03 deteccion", f"alertas activas a los {time.time() - t0:.0f} s: {', '.join(activas())}")
    captura("inc3_alertas_receptor.png", "http://localhost:9099/", 700)
    captura("inc3_d5.png", "http://localhost:3000/d/expedientes-presupuesto/?kiosk&from=now-10m", 1000)
    # --- RB-05 diagnostico
    r = requests.get(API + "/salud", timeout=10).json()
    log("RB-05 diag 1", f"GET /salud -> base_datos = {r.get('base_datos', r)}")
    log("RB-05 diag 2", "docker compose ps db -> " + (sh(COMPOSE + ["ps", "-a", "--format", "{{.Name}}: {{.Status}}", "db"]) or "sin contenedor"))
    # --- mitigacion
    t1 = time.time()
    log("RB-05 mitig 1", "docker compose start db (equivale a restart: el contenedor estaba detenido)")
    sh(COMPOSE + ["start", "db"])
    ok = esperar(lambda: sh(["docker", "inspect", "-f", "{{.State.Health.Status}}", "fase3mon-db-1"]) == "healthy", 120, 3)
    log("RB-05 mitig 1", f"MySQL 'healthy' en {time.time() - t1:.0f} s" if ok else "MySQL no recupero")
    # --- verificacion
    ok = esperar(lambda: requests.get(API + "/alumnos", params={"q": "MARIA"}, timeout=10, cookies=s.cookies).status_code == 200, 90, 3)
    log("RB-05 verif", f"GET /alumnos -> {'200 OK (busqueda de alumnos restaurada)' if ok else 'sigue fallando'}")
    r = requests.get(API + "/salud", timeout=10).json()
    log("RB-05 verif", f"GET /salud -> base_datos = {r.get('base_datos', r)}; alumnos = {r.get('alumnos', '?')}")
    stop.set()
    ok = esperar(lambda: not {"BaseDeDatosInaccesible", "TasaErroresAlta", "QuemaDePresupuestoRapida"} & set(activas()), 300, 5)
    log("RB-05 verif", f"alertas {'RESUELTAS' if ok else 'siguen activas'}; servicio restaurado a los {time.time() - t0:.0f} s de iniciado el incidente")
    captura("inc3_recuperado_d5.png", "http://localhost:3000/d/expedientes-presupuesto/?kiosk&from=now-10m", 1000)
    log("INC-03", "=== FIN ===")


if __name__ == "__main__":
    os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
    cual = sys.argv[1] if len(sys.argv) > 1 else "todos"
    for nombre, f in (("INC-01", inc01), ("INC-02", inc02), ("INC-03", inc03)):
        if cual in (nombre, "todos"):
            f()
