"""Pone a prueba la RESPUESTA AUTOMATIZADA: provoca incidentes SIMULADOS y NO interviene: solo mide cuanto tarda el servicio
responder.py en detectar la alerta, actuar y dejar el sistema recuperado. Requiere el stack de monitoreo y responder.py en marcha.

  python incidentes_automaticos.py API | DERIVA | BD | todos
"""
import sys
import time

import requests

import generar_trafico as gt
from runbooks import API, COMPOSE, Trafico, activas, captura, esperar, log, sh

RESP = "http://localhost:9100"


def acciones():
    try:
        return requests.get(RESP + "/acciones", timeout=5).json()
    except Exception:
        return []


def nueva_accion(desde, regla, alerta=None, timeout=240):
    """Espera una accion NUEVA del responder (por indice) con esa respuesta."""
    hallada = []

    def hay():
        for a in acciones()[desde:]:
            if a["respuesta"] == regla and (alerta is None or a["alerta"] == alerta):
                hallada.append(a)
                return True
        return False

    esperar(hay, timeout, 2)
    return hallada[0] if hallada else None


def espera_estable():
    log("PREPARACION", "tráfico normal hasta que no haya alertas activas")
    t = Trafico("normal")
    t.start()
    esperar(lambda: not activas(), 300, 5)
    t.parar.set()


def api_caida():
    log("INC-A1", "=== INICIO. SIMULADO: la API se cae (docker stop). Nadie interviene: debe reiniciarla el servicio de respuesta ===")
    espera_estable()
    for intento in range(1, 5):
        n = len(acciones())
        t0 = time.time()
        sh(COMPOSE + ["stop", "api"])
        log("INC-A1", f"intento {intento}/4: API detenida")
        a = nueva_accion(n, "R-A1", "ApiCaida", 200)
        if a is None:
            log("INC-A1", "el responder no actuó en 200 s")
            break
        log("INC-A1 respuesta", f"{a['ts']}  {a['accion']} -> {a['resultado']} | {a['verificacion']}  (a los {time.time() - t0:.0f} s de la caída)")
        if intento == 1:
            captura("auto1_responder.png", "http://localhost:9100/", 600)
        if "ESCALADO" in a["verificacion"]:
            log("INC-A1 guarda", "se alcanzó el límite de 3 reinicios en 10 min: el sistema NO insiste y escala a una persona")
            captura("auto1_guarda_escalado.png", "http://localhost:9100/", 700)
            sh(COMPOSE + ["restart", "api"])            # intervención humana (la decisión de un P1 es de una persona)
            esperar(lambda: requests.get(API + "/salud", timeout=3).ok, 120)
            log("INC-A1", "una persona reinició la API a mano (acción humana tras el escalamiento)")
            break
        esperar(lambda: "ApiCaida" not in activas(), 120, 3)
    log("INC-A1", "=== FIN ===")


def deriva():
    log("INC-A2", "=== INICIO. SIMULADO: llegan escaneos de mala calidad (data drift). Debe activarse sola el modo seguro ===")
    espera_estable()
    s = gt.sesion()
    n = len(acciones())
    t0 = time.time()
    tr = Trafico("degradado", n=30)
    tr.start()
    a = nueva_accion(n, "R-A2", None, 360)
    if a is None:
        log("INC-A2", "no se activó el modo seguro")
        return
    log("INC-A2 respuesta", f"{a['ts']}  {a['accion']} ({a['alerta']}) -> {a['verificacion']}  (a los {time.time() - t0:.0f} s)")
    tr.join(timeout=150)
    # verificación: lo que hace el sistema con un documento mientras el modo está activo
    img = gt.paginas("acta_nacimiento_ficticia.pdf")[0]
    r, _ = gt.enviar(s, gt.a_pdf(gt.normal(img)))
    d = r.json()
    log("INC-A2 verif", f"documento limpio leído en modo seguro -> modo_seguro={d.get('modo_seguro')}; aviso: {str(d.get('aviso'))[:70]}")
    captura("auto2_responder_modo_seguro.png", "http://localhost:9100/", 700)
    captura("auto2_d3_deriva.png", "http://localhost:3000/d/expedientes-deriva/?kiosk&from=now-10m", 1000)
    log("INC-A2", "se re-escanea el lote: vuelven documentos normales")
    n = len(acciones())
    tr2 = Trafico("normal")
    tr2.start()
    off = nueva_accion(n, "R-A2", None, 600)
    tr2.parar.set()
    if off:
        log("INC-A2 reversión", f"{off['ts']}  {off['accion']} -> {off['verificacion']}")
    r, _ = gt.enviar(s, gt.a_pdf(gt.normal(img)))
    log("INC-A2 verif", f"documento leído tras la reversión -> modo_seguro={r.json().get('modo_seguro')}")
    log("INC-A2", f"recuperado automáticamente; tiempo total {time.time() - t0:.0f} s")
    captura("auto2_responder_final.png", "http://localhost:9100/", 700)
    log("INC-A2", "=== FIN ===")


def base_datos():
    log("INC-A3", "=== INICIO. SIMULADO: MySQL se detiene. Debe arrancarla sola y pedir un respaldo preventivo ===")
    espera_estable()
    s = gt.sesion()
    n = len(acciones())
    t0 = time.time()
    sh(COMPOSE + ["stop", "db"])
    parar = False

    def golpes():
        while not parar:
            try:
                s.get(API + "/alumnos", params={"q": "MARIA"}, timeout=10)
            except Exception:
                pass
            time.sleep(0.5)

    import threading
    th = threading.Thread(target=golpes, daemon=True)
    th.start()
    a = nueva_accion(n, "R-A1", "BaseDeDatosInaccesible", 240)
    parar = True
    if a is None:
        log("INC-A3", "el responder no actuó")
        return
    log("INC-A3 respuesta", f"{a['ts']}  {a['accion']} -> {a['verificacion']}  (a los {time.time() - t0:.0f} s de la caída)")
    n = len(acciones())
    b = nueva_accion(n, "R-A7", None, 360)
    if b:
        log("INC-A3 respuesta", f"{b['ts']}  {b['accion']} -> {b['verificacion']}")
    captura("auto3_responder.png", "http://localhost:9100/", 700)
    log("INC-A3", f"recuperado automáticamente; tiempo total {time.time() - t0:.0f} s")
    log("INC-A3", "=== FIN ===")


if __name__ == "__main__":
    cual = sys.argv[1].upper() if len(sys.argv) > 1 else "TODOS"
    for nombre, f in (("API", api_caida), ("DERIVA", deriva), ("BD", base_datos)):
        if cual in (nombre, "TODOS"):
            f()
