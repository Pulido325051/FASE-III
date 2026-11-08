"""Muestra en consola la configuracion de alertas cargada en Prometheus y su estado en este momento.

  python verificar_alertas.py            (usa http://localhost:9090)
  python verificar_alertas.py --vigilar  (se actualiza cada 5 s, como un tablero en terminal)

Las reglas viven en prometheus/reglas.yml y el enrutamiento en alertmanager/alertmanager.yml; este script solo
las consulta a traves de la API de Prometheus para comprobar que estan cargadas y ver cuales estan activas.
"""
import argparse
import os
import time

import requests

PROM = os.getenv("PROMETHEUS", "http://localhost:9090")


def reglas():
    grupos = requests.get(PROM + "/api/v1/rules", params={"type": "alert"}, timeout=10).json()["data"]["groups"]
    return [(g["name"], r) for g in grupos for r in g["rules"]]


def mostrar():
    filas = reglas()
    print(f"{'ALERTA':<26}{'ESTADO':<10}{'SEVERIDAD':<10}{'RUNBOOK':<8}{'DURACION':<9}CONDICION")
    for grupo, r in filas:
        expr = " ".join(r["query"].split())
        print(f"{r['name']:<26}{r['state']:<10}{r['labels'].get('severity', ''):<10}{r['labels'].get('runbook', ''):<8}"
              f"{str(int(r['duration'])) + ' s':<9}{expr[:90]}")
    activas = [r["name"] for _, r in filas if r["state"] == "firing"]
    print(f"\n{len(filas)} reglas cargadas; en disparo: {', '.join(activas) if activas else 'ninguna'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vigilar", action="store_true")
    a = ap.parse_args()
    while True:
        try:
            mostrar()
        except requests.RequestException as e:
            print("No se pudo consultar Prometheus:", e)
        if not a.vigilar:
            break
        time.sleep(5)
        print("\n" + "-" * 60)
