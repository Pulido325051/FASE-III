"""Mide latencia, throughput y uso de recursos del servicio de clasificacion variando CPU, concurrencia, numero de contenedores
y la variable OMP_THREAD_LIMIT (hilos de Tesseract). Sirve de evidencia para el analisis de escalabilidad y costos.

Levanta contenedores de PRUEBA con la imagen del sistema, limitados con --cpus y --memory, y les manda los PDF ficticios de
ejemplos/ convertidos a imagen (para parecerse a un escaneo). Requiere el stack de monitoreo (la base de datos de prueba):

    docker compose -p fase3mon -f docker-compose.monitoreo.yml up -d --build
    python escalabilidad/medir_rendimiento.py --serie todo          (unos 30 min)
    python escalabilidad/medir_rendimiento.py --serie omp --docs 6  (prueba corta)

Variables opcionales: IMAGEN (por defecto clasificador-documentos:fase3-mon), RED (fase3mon_default), POPPLER (carpeta de Poppler en Windows).
Los resultados quedan en escalabilidad/resultados/mediciones_rendimiento.json
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "monitoreo"))
import generar_trafico as gt   # noqa: E402  (reutiliza la conversion de PDF a imagen y la sesion)

IMAGEN = os.getenv("IMAGEN", "clasificador-documentos:fase3-mon")
RED = os.getenv("RED", "fase3mon_default")
SALIDA = os.path.join(AQUI, "resultados", "mediciones_rendimiento.json")
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
nombres_activos = []


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=SIN_VENTANA)
    return (r.stdout + r.stderr).strip()


def levantar(nombre, puerto, cpus, max_conc, omp=None, mem="1g"):
    sh(["docker", "rm", "-f", nombre])
    entorno = ["-e", "DB_HOST=db", "-e", "DB_USER=clasificador", "-e", "DB_PASSWORD=prueba-2026", "-e", "DB_NAME=controlescolar_prueba",
               "-e", "ARCHIVOS_DIR=/tmp/exp", "-e", f"MAX_CONCURRENCIA={max_conc}", "-e", "EVENTOS_PATH=/tmp/eventos.jsonl"]
    if omp:
        entorno += ["-e", f"OMP_THREAD_LIMIT={omp}"]
    sh(["docker", "run", "-d", "--name", nombre, "--network", RED, "--cpus", str(cpus), "--memory", mem, "-p", f"{puerto}:8000", *entorno, IMAGEN])
    t = time.time()
    while time.time() - t < 90:
        try:
            if requests.get(f"http://localhost:{puerto}/salud", timeout=2).ok:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("no arranco " + nombre)


def memoria_y_cpu(nombre):
    mem, cpu = sh(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}|{{.CPUPerc}}", nombre]).split("|")
    v = mem.split("/")[0].strip()
    n = float(v.replace("MiB", "").replace("GiB", "").replace("KiB", "") or 0)
    return (n * 1024 if "GiB" in v else n), float(cpu.strip("%"))


def carga(puertos, concurrencia, n):
    """n documentos repartidos entre los contenedores, con `concurrencia` clientes en paralelo."""
    pdfs = [gt.a_pdf(gt.normal(i)) for i in (gt.paginas("acta_nacimiento_ficticia.pdf")[0], gt.paginas("constancia_curp_ficticia.pdf")[0])]
    cola, lat, fallos = list(range(n)), [], [0]
    candado, picos, parar = threading.Lock(), {"mem": 0.0, "cpu": 0.0}, threading.Event()

    def muestreo():
        while not parar.is_set():
            for nom in nombres_activos:
                try:
                    m, c = memoria_y_cpu(nom)
                    picos["mem"], picos["cpu"] = max(picos["mem"], m), max(picos["cpu"], c)
                except Exception:
                    pass
            parar.wait(2)

    def cliente():
        s = requests.Session()
        while True:
            with candado:
                if not cola:
                    return
                i = cola.pop()
            t = time.time()
            try:
                r = s.post(f"http://localhost:{puertos[i % len(puertos)]}/clasificar", data={"guardar": "false"}, timeout=300,
                           files={"archivo": ("d.pdf", pdfs[1 if i % 6 == 5 else 0], "application/pdf")})
                ok = r.status_code == 200
            except Exception:
                ok = False
            with candado:
                lat.append(time.time() - t)
                fallos[0] += 0 if ok else 1

    hilos = [threading.Thread(target=cliente) for _ in range(concurrencia)]
    threading.Thread(target=muestreo, daemon=True).start()
    t0 = time.time()
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    dur = time.time() - t0
    parar.set()
    lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]   # noqa: E731
    return {"docs": n, "concurrencia": concurrencia, "segundos": round(dur, 1), "docs_por_min": round(n / dur * 60, 1),
            "lat_media": round(statistics.mean(lat), 2), "lat_p50": round(p(0.5), 2), "lat_p95": round(p(0.95), 2),
            "fallos": fallos[0], "mem_pico_mb": round(picos["mem"]), "cpu_pico_pct": round(picos["cpu"])}


def experimento(res, clave, etiqueta, cpus, max_conc, contenedores, concurrencia, docs, omp=None):
    global nombres_activos
    puertos, nombres = [], []
    for k in range(contenedores):
        nom, pto = f"med-{clave}-{k}", 8310 + k
        levantar(nom, pto, cpus, max_conc, omp)
        nombres.append(nom)
        puertos.append(pto)
    nombres_activos = nombres
    carga(puertos, 1, 4)                                   # calentamiento: carga del modelo y primeras lecturas
    r = carga(puertos, concurrencia, docs)
    r.update(omp_thread_limit=omp, experimento=etiqueta, cpus_por_contenedor=cpus, max_concurrencia=max_conc, contenedores=contenedores)
    print(json.dumps(r, ensure_ascii=False), flush=True)
    res["experimentos"].append(r)
    for nom in nombres:
        sh(["docker", "rm", "-f", nom])
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


def plan(docs):
    """(clave, etiqueta, cpus por contenedor, max lecturas, contenedores, clientes, docs, OMP_THREAD_LIMIT)"""
    base = [("a1", "A. Base: 1 CPU, 1 lectura a la vez", 1, 1, 1, 1, docs, None)]
    base += [(f"b{c}", f"B. Vertical: {c} CPU, 2 lecturas", c, 2, 1, 2, docs, None) for c in (1, 2, 4)]
    base += [(f"c{m}", f"C. 4 CPU, MAX_CONCURRENCIA={m}", 4, m, 1, 4, docs, None) for m in (1, 2, 4)]
    base += [("d2", "D. Horizontal: 2 contenedores x 1 CPU", 1, 1, 2, 2, docs, None), ("d4", "D. Horizontal: 4 contenedores x 1 CPU", 1, 1, 4, 4, docs, None)]
    omp = [("e1", "E. OMP_THREAD_LIMIT=1: 1 CPU, 1 lectura", 1, 1, 1, 1, docs, 1), ("e2", "E. OMP_THREAD_LIMIT=1: 2 CPU, 2 lecturas", 2, 2, 1, 2, docs, 1),
           ("e4", "E. OMP_THREAD_LIMIT=1: 4 CPU, 4 lecturas", 4, 4, 1, 4, docs, 1), ("e42", "E. OMP_THREAD_LIMIT=1: 4 CPU, 2 lecturas", 4, 2, 1, 2, docs, 1)]
    return base, omp


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serie", choices=["base", "omp", "todo"], default="todo", help="base = configuracion actual; omp = con OMP_THREAD_LIMIT=1")
    ap.add_argument("--docs", type=int, default=24, help="documentos por experimento")
    ap.add_argument("--solo", help="clave de un solo experimento (a1, b1, b2, b4, c1, c2, c4, d2, d4, e1, e2, e4, e42)")
    a = ap.parse_args()
    base, omp = plan(a.docs)
    lista = (base if a.serie in ("base", "todo") else []) + (omp if a.serie in ("omp", "todo") else [])
    if a.solo:
        lista = [x for x in base + omp if x[0] == a.solo]
    resultado = {"vm": {"cpus": os.cpu_count()}, "experimentos": []}
    for x in lista:
        experimento(resultado, *x[:7], omp=x[7])
    print("LISTO ->", SALIDA)
