"""Monitor de data drift y desempeno del modelo.

Lee el archivo de eventos de la API (rasgos NO personales de cada documento), compara una ventana reciente contra
una referencia usando PSI (Population Stability Index), expone el resultado a Prometheus (:9101) y lo registra como
metricas en MLflow (experimento "monitoreo-produccion").

Referencia: en produccion seria el conjunto de entrenamiento / primeras semanas de trafico real. En la demo se congela
con las primeras REF_N clasificaciones de trafico normal (queda en /estado/referencia.json).
"""
import json
import math
import os
import time
from collections import Counter

import mlflow
import numpy as np
from prometheus_client import Gauge, start_http_server

EVENTOS = os.getenv("EVENTOS_PATH", "/eventos/monitoreo/eventos.jsonl")
REF_PATH = os.getenv("REF_PATH", "/estado/referencia.json")
REF_N = int(os.getenv("REF_N", "30"))
VENTANA = int(os.getenv("VENTANA", "30"))
CICLO = int(os.getenv("CICLO_S", "15"))
MLFLOW = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
EPS = 1e-4

g_psi = Gauge("expedientes_monitor_psi", "PSI de cada senal contra la referencia", ["senal"])
g_n = Gauge("expedientes_monitor_ventana_documentos", "Documentos en la ventana de analisis")
g_ref = Gauge("expedientes_monitor_referencia_documentos", "Documentos en la referencia (0 = aun sin congelar)")
g_tasa = Gauge("expedientes_monitor_tasa", "Indicadores de calidad en la ventana", ["indicador"])
g_ciclo = Gauge("expedientes_monitor_ultimo_ciclo_timestamp", "Ultimo ciclo del monitor")


def leer_eventos():
    cl, co = [], []
    try:
        with open(EVENTOS, encoding="utf-8") as f:
            for linea in f:
                try:
                    e = json.loads(linea)
                except ValueError:
                    continue
                (cl if e.get("tipo") == "clasificacion" else co if e.get("tipo") == "correccion" else []).append(e)
    except OSError:
        pass
    return cl, co


def psi_numerica(ref, act, bins=5):
    ref, act = np.asarray(ref, float), np.asarray(act, float)
    cortes = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)[1:-1]))
    pr = np.bincount(np.searchsorted(cortes, ref, side="right"), minlength=len(cortes) + 1) / len(ref)
    pa = np.bincount(np.searchsorted(cortes, act, side="right"), minlength=len(cortes) + 1) / len(act)
    pr, pa = np.clip(pr, EPS, None), np.clip(pa, EPS, None)
    return float(np.sum((pa - pr) * np.log(pa / pr)))


def psi_categorica(ref, act):
    cats = set(ref) | set(act)
    cr, ca = Counter(ref), Counter(act)
    s = 0.0
    for c in cats:
        pr, pa = max(cr[c] / len(ref), EPS), max(ca[c] / len(act), EPS)
        s += (pa - pr) * math.log(pa / pr)
    return s


def rasgos(evs):
    return {"margen": [e["margen"] for e in evs if e.get("margen") is not None],
            "palabras": [e["palabras"] for e in evs], "cobertura": [e["cobertura"] for e in evs],
            "clase": [e["clase"] for e in evs]}


def main():
    start_http_server(9101)
    mlflow.set_tracking_uri(MLFLOW)
    run = None
    paso = 0
    ref = None
    if os.path.exists(REF_PATH):
        with open(REF_PATH) as f:
            ref = json.load(f)
    while True:
        try:
            cl, co = leer_eventos()
            g_ciclo.set(time.time())
            if ref is None and len(cl) >= REF_N:
                ref = rasgos(cl[:REF_N])
                os.makedirs(os.path.dirname(REF_PATH), exist_ok=True)
                with open(REF_PATH, "w") as f:
                    json.dump(ref, f)
                print(f"Referencia congelada con {REF_N} documentos", flush=True)
            g_ref.set(len(ref["clase"]) if ref else 0)
            ventana = cl[-VENTANA:]
            g_n.set(len(ventana))
            metricas = {}
            if ventana:
                act = rasgos(ventana)
                tasas = {"baja_confianza": float(np.mean([e["margen"] < 1.2 for e in ventana if e.get("margen") is not None] or [0])),
                         "curp_verificada": float(np.mean([e["curp_verificada"] for e in ventana])),
                         "pasadas_extra": float(np.mean([e["pasadas_extra"] > 0 for e in ventana])),
                         "correccion": min(1.0, sum(1 for c in co if c["ts"] >= ventana[0]["ts"]) / len(ventana))}
                for k, v in tasas.items():
                    g_tasa.labels(k).set(v)
                    metricas["tasa_" + k] = v
            if ref and len(ventana) >= 10:
                act = rasgos(ventana)
                for s in ("margen", "palabras", "cobertura"):
                    v = psi_numerica(ref[s], act[s])
                    g_psi.labels(s).set(v)
                    metricas["psi_" + s] = v
                v = psi_categorica(ref["clase"], act["clase"])
                g_psi.labels("clase").set(v)
                metricas["psi_clase"] = v
            if metricas:
                if run is None:
                    run = mlflow.start_run(run_name="monitor-" + time.strftime("%Y%m%d-%H%M"),
                                           experiment_id=(mlflow.get_experiment_by_name("monitoreo-produccion")
                                                          or mlflow.get_experiment(mlflow.create_experiment("monitoreo-produccion"))).experiment_id)
                    mlflow.set_tags({"tipo": "monitoreo", "ventana": str(VENTANA), "referencia": str(REF_N)})
                paso += 1
                metricas["documentos_ventana"] = len(ventana)
                mlflow.log_metrics(metricas, step=paso)
        except Exception as e:   # el monitor nunca debe caerse por un fallo pasajero
            print("ciclo con error:", type(e).__name__, e, flush=True)
        time.sleep(CICLO)


if __name__ == "__main__":
    main()
