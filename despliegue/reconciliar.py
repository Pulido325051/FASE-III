"""Despliegue continuo estilo GitOps: reconcilia un entorno con el ESTADO DESEADO declarado en Git (despliegue/estado-deseado.yml).

  1. Lee la version que debe correr en el entorno.
  2. Compara con lo que corre ahora (etiquetas del contenedor). Si coincide y esta sano, no hace nada (idempotente).
  3. Si no, descarga la imagen, reemplaza el contenedor, espera a que este sano y hace una PRUEBA DE HUMO (clasifica un documento de ejemplo).
  4. Si algo falla, REVIERTE al contenedor anterior y sale con error.

    python despliegue/reconciliar.py --entorno staging
    python despliegue/reconciliar.py --entorno staging --forzar --simular-falla     (demuestra la reversion)
    python despliegue/reconciliar.py --entorno staging --vigilar 30                  (bucle GitOps local: git pull y reconciliar cada 30 s)

Los entornos se simulan con contenedores Docker locales; el mismo estado deseado serviria para un entorno real cambiando solo este paso.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(AQUI, "..")
HISTORIAL = os.path.join(AQUI, "historial.jsonl")
EJEMPLO = os.path.join(RAIZ, "ejemplos", "acta_nacimiento_ficticia.pdf")


def sh(cmd, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}: {r.stderr.strip()[:300]}")
    return r.returncode, (r.stdout + r.stderr).strip()


def registrar(evento, **datos):
    fila = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "evento": evento, **datos}
    print(json.dumps(fila, ensure_ascii=False), flush=True)
    with open(HISTORIAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def estado_deseado(entorno):
    with open(os.path.join(AQUI, "estado-deseado.yml"), encoding="utf-8") as f:
        e = yaml.safe_load(f)
    return e["imagen"], str(e["entornos"][entorno]["version"]), int(e["entornos"][entorno]["puerto"])


def actual(nombre):
    codigo, salida = sh(["docker", "inspect", "-f", "{{.Config.Image}}", nombre])
    return salida if codigo == 0 else None


def sano(puerto, espera=90):
    t = time.time()
    while time.time() - t < espera:
        try:
            r = requests.get(f"http://localhost:{puerto}/salud", timeout=3)
            if r.ok and r.json().get("modelo_cargado"):
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def humo(puerto, simular_falla=False):
    """Prueba de humo: el servicio clasifica un documento de ejemplo con el resultado esperado."""
    if simular_falla:
        return False, "falla simulada para demostrar la reversion"
    try:
        with open(EJEMPLO, "rb") as f:
            r = requests.post(f"http://localhost:{puerto}/clasificar", files={"archivo": ("acta.pdf", f, "application/pdf")}, data={"guardar": "false"}, timeout=120)
        d = r.json()
        ok = r.ok and d.get("tipo_documento") == "Actas de nacimiento" and d.get("curp_verificada")
        return bool(ok), f"tipo={d.get('tipo_documento')} curp_verificada={d.get('curp_verificada')}"
    except Exception as e:
        return False, str(e)[:120]


def arrancar(nombre, imagen, version, entorno, puerto):
    sh(["docker", "rm", "-f", nombre])
    sh(["docker", "run", "-d", "--name", nombre, "-p", f"{puerto}:8000", "-l", f"fase3.entorno={entorno}", "-l", f"fase3.version={version}", imagen], check=True)


def reconciliar(entorno, forzar=False, simular_falla=False, imagen_override=None):
    imagen, version, puerto = estado_deseado(entorno)
    objetivo = imagen_override or f"{imagen}:{version}"
    nombre = f"fase3-{entorno}"
    corriendo = actual(nombre)
    registrar("lectura", entorno=entorno, deseado=objetivo, actual=corriendo)
    if corriendo == objetivo and not forzar and sano(puerto, 5):
        registrar("sin_cambios", entorno=entorno, version=version, detalle="el entorno ya coincide con el estado deseado")
        return 0
    registrar("despliegue_inicio", entorno=entorno, de=corriendo, a=objetivo)
    if imagen_override is None:
        codigo, salida = sh(["docker", "pull", objetivo])
        if codigo:
            registrar("error", detalle=f"no se pudo descargar {objetivo}: {salida[-200:]}")
            return 1
    anterior = corriendo
    try:
        if anterior:
            sh(["docker", "rename", nombre, nombre + "-anterior"])
            sh(["docker", "stop", nombre + "-anterior"])
        arrancar(nombre, objetivo, version, entorno, puerto)
        if not sano(puerto):
            raise RuntimeError("el contenedor no quedo sano a tiempo")
        ok, detalle = humo(puerto, simular_falla)
        registrar("prueba_de_humo", entorno=entorno, ok=ok, detalle=detalle)
        if not ok:
            raise RuntimeError("fallo la prueba de humo: " + detalle)
    except Exception as e:
        registrar("falla", entorno=entorno, detalle=str(e))
        sh(["docker", "rm", "-f", nombre])
        if anterior:
            sh(["docker", "rename", nombre + "-anterior", nombre])
            sh(["docker", "start", nombre])
            registrar("reversion", entorno=entorno, a=anterior, sano=sano(puerto, 60))
        return 1
    sh(["docker", "rm", "-f", nombre + "-anterior"])
    registrar("desplegado", entorno=entorno, version=version, imagen=objetivo)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entorno", required=True, choices=["staging", "produccion"])
    ap.add_argument("--forzar", action="store_true", help="vuelve a desplegar aunque ya coincida")
    ap.add_argument("--simular-falla", action="store_true", help="hace fallar la prueba de humo para demostrar la reversion")
    ap.add_argument("--imagen", help="usar esta imagen local en lugar de descargarla (pruebas locales)")
    ap.add_argument("--vigilar", type=int, metavar="SEGUNDOS", help="bucle GitOps: git pull y reconciliar cada N segundos")
    a = ap.parse_args()
    if a.vigilar:
        while True:
            sh(["git", "-C", RAIZ, "pull", "--ff-only"])
            reconciliar(a.entorno, imagen_override=a.imagen)
            time.sleep(a.vigilar)
    sys.exit(reconciliar(a.entorno, a.forzar, a.simular_falla, a.imagen))
