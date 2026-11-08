"""Observabilidad del servicio: metricas Prometheus, logs JSON con request_id, etapas (trazas) y eventos.

Implementa lo definido en el documento tecnico de monitorizacion:
  - metricas con el prefijo  expedientes_  (se exponen en /metrics)
  - logs estructurados (una linea JSON) SIN datos personales: nunca CURP, nombre ni texto del documento
  - una traza por peticion: cada etapa (pdf_a_imagen, ocr, clasificar, extraer...) es un "span" con su duracion
  - un archivo de eventos (JSON lineas) con rasgos NO personales de cada documento, que lee el monitor para
    calcular data drift y registrar el desempeno en MLflow
"""

import contextvars
import json
import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, ProcessCollector,
                               generate_latest)

VERSION = "3.1.0-monitoreo"
BASE = Path(__file__).resolve().parent.parent
EVENTOS_PATH = os.getenv("EVENTOS_PATH", str(BASE / "datos" / "monitoreo" / "eventos.jsonl"))
UMBRAL_BAJA_CONFIANZA = float(os.getenv("UMBRAL_BAJA_CONFIANZA", "1.2"))   # margen de decision por debajo = "duda"

# ---------------------------------------------------------------- metricas
REG = CollectorRegistry()
ProcessCollector(registry=REG)          # CPU y memoria del proceso de la API
P = "expedientes_"

http_total = Counter(P + "http_requests_total", "Peticiones HTTP", ["ruta", "metodo", "codigo"], registry=REG)
http_dur = Histogram(P + "http_request_duration_seconds", "Duracion de las peticiones", ["ruta"],
                     buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 45, 60, 120), registry=REG)
en_curso = Gauge(P + "clasificar_en_curso", "Lecturas de documentos en proceso", registry=REG)
etapa_dur = Histogram(P + "etapa_duracion_seconds", "Duracion de cada etapa del procesamiento", ["etapa"],
                      buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60), registry=REG)
ocr_extra = Counter(P + "ocr_pasadas_extra_total", "Pasadas extra de OCR por no hallar la CURP", registry=REG)

prediccion = Counter(P + "prediccion_total", "Documentos por clase predicha", ["clase"], registry=REG)
margen = Histogram(P + "margen_decision", "Margen de decision (1.a menos 2.a puntuacion)",
                   buckets=(0, 0.5, 1, 1.2, 1.5, 2, 2.5, 3, 4), registry=REG)
baja_confianza = Counter(P + "baja_confianza_total", "Documentos con margen por debajo del umbral", registry=REG)
correccion = Counter(P + "correccion_categoria_total", "Veces que una persona cambio el tipo propuesto", ["de", "a"], registry=REG)
modelo_info = Gauge(P + "modelo_info", "Version del modelo en produccion", ["version", "sha"], registry=REG)

curp_encontrada = Counter(P + "curp_encontrada_total", "CURP hallada en el documento", registry=REG)
curp_verificada = Counter(P + "curp_verificada_total", "CURP hallada con digito verificador correcto", registry=REG)
nombre_encontrado = Counter(P + "nombre_encontrado_total", "Nombre leido", registry=REG)
fecha_encontrada = Counter(P + "fecha_encontrada_total", "Fecha de nacimiento leida", registry=REG)
alumno_encontrado = Counter(P + "alumno_encontrado_total", "Alumno hallado en la BD", ["por"], registry=REG)
texto_palabras = Histogram(P + "texto_palabras", "Palabras de texto por documento",
                           buckets=(50, 100, 150, 200, 250, 300, 350, 400, 500, 800), registry=REG)
cobertura = Histogram(P + "cobertura_vocabulario", "Fraccion de terminos del documento que el modelo conoce",
                      buckets=(0.5, 0.6, 0.7, 0.75, 0.8, 0.82, 0.85, 0.87, 0.9, 0.92, 0.95, 1.0), registry=REG)

guardado = Counter(P + "guardado_total", "Documentos guardados", ["modo"], registry=REG)
retractacion = Counter(P + "retractacion_total", "Documentos eliminados o reemplazados en menos de 24 h", registry=REG)
curp_corregida = Counter(P + "curp_corregida_total", "Correcciones de CURP en la BD", registry=REG)
eliminado = Counter(P + "eliminado_total", "Documentos eliminados", registry=REG)

bd_up = Gauge(P + "bd_up", "Conexion a MySQL (1 = conectada)", registry=REG)
bd_consulta = Histogram(P + "bd_consulta_seconds", "Duracion de consultas a la BD", ["operacion"],
                        buckets=(0.005, 0.01, 0.05, 0.1, 0.2, 0.5, 1, 5), registry=REG)
disco_libre = Gauge(P + "disco_libre_ratio", "Fraccion libre del disco de expedientes", ["ruta"], registry=REG)
respaldo_ultimo = Gauge(P + "respaldo_ultimo_exito_timestamp", "Marca de tiempo del ultimo respaldo correcto (0 = ninguno)", registry=REG)
respaldo_fallos = Counter(P + "respaldo_fallos_total", "Respaldos fallidos", registry=REG)

login_total = Counter(P + "login_total", "Intentos de inicio de sesion", ["resultado"], registry=REG)
acceso_denegado = Counter(P + "acceso_denegado_total", "Respuestas 401, 403 y 429", ["rol", "codigo"], registry=REG)

estado_modelo = {"version": "v1", "sha": "desconocido"}
FALLAS = {"retardo_ocr_s": 0.0}         # inyeccion de fallas para simulaciones (solo con FALLAS_HABILITADAS=1)


def fijar_modelo(version, sha):
    estado_modelo.update(version=version, sha=sha)
    modelo_info.clear()
    modelo_info.labels(version, sha).set(1)


def exportar():
    return generate_latest(REG), CONTENT_TYPE_LATEST


# ---------------------------------------------------------------- logs JSON
request_id = contextvars.ContextVar("request_id", default="-")
_spans = contextvars.ContextVar("spans", default=None)
log = logging.getLogger("api")


class FormatoJson(logging.Formatter):
    def format(self, r):
        linea = {"ts": datetime.fromtimestamp(r.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "nivel": r.levelname, "servicio": "api", "version": VERSION, "modelo": estado_modelo["version"],
                 "request_id": request_id.get()}
        campos = getattr(r, "campos", None)
        if campos:
            linea.update(campos)
        else:
            linea["mensaje"] = r.getMessage()
        if r.exc_info:   # solo tipo y mensaje, sin traza completa
            linea["error"] = f"{r.exc_info[0].__name__}: {r.exc_info[1]}"
        return json.dumps(linea, ensure_ascii=False)


def configurar_logs():
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(FormatoJson())
    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True    # el servicio registra sus propios eventos HTTP


def evento(nombre, nivel="INFO", **campos):
    """Una linea de log estructurada. Nunca pasar CURP, nombres ni texto del documento."""
    log.log(getattr(logging, nivel), nombre, extra={"campos": {"evento": nombre, **campos}})


# ---------------------------------------------------------------- trazas (etapas)
def iniciar_traza():
    _spans.set([])


def spans():
    return list(_spans.get() or [])


@contextmanager
def etapa(nombre):
    t = time.perf_counter()
    try:
        yield
        if nombre == "ocr" and FALLAS["retardo_ocr_s"] > 0:      # falla inyectada: el tiempo se ve en la etapa del OCR
            time.sleep(FALLAS["retardo_ocr_s"])
    finally:
        d = time.perf_counter() - t
        etapa_dur.labels(nombre).observe(d)
        lista = _spans.get()
        if lista is not None:
            lista.append({"etapa": nombre, "s": round(d, 3)})


# ---------------------------------------------------------------- eventos para el monitor (sin datos personales)
_candado = threading.Lock()


def registrar(tipo, **campos):
    ruta = Path(EVENTOS_PATH)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with _candado, open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "tipo": tipo, **campos}, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("No se pudo escribir el archivo de eventos")


def registrar_clasificacion(clase, margen_decision, palabras, cobertura_vocab, curp_hallada, curp_ok, nombre_ok, fecha_ok,
                            pasadas_extra, segundos, paginas, por):
    prediccion.labels(clase).inc()
    if margen_decision is not None:
        margen.observe(margen_decision)
        if margen_decision < UMBRAL_BAJA_CONFIANZA:
            baja_confianza.inc()
            evento("baja_confianza", "WARNING", clase=clase, margen=round(margen_decision, 3))
    texto_palabras.observe(palabras)
    cobertura.observe(cobertura_vocab)
    if curp_hallada:
        curp_encontrada.inc()
    if curp_ok:
        curp_verificada.inc()
    if nombre_ok:
        nombre_encontrado.inc()
    if fecha_ok:
        fecha_encontrada.inc()
    if pasadas_extra:
        ocr_extra.inc(pasadas_extra)
    alumno_encontrado.labels(por).inc()
    registrar("clasificacion", clase=clase, margen=margen_decision, palabras=palabras, cobertura=round(cobertura_vocab, 4),
              curp_encontrada=curp_hallada, curp_verificada=curp_ok, nombre=nombre_ok, fecha=fecha_ok,
              pasadas_extra=pasadas_extra, segundos=round(segundos, 3), paginas=paginas, alumno_por=por)


# ---------------------------------------------------------------- rutas (pocas etiquetas distintas)
CONOCIDAS = {"/", "/login", "/salud", "/clasificar", "/guardar", "/alumnos", "/alumnos/por-curp/{curp}", "/alumnos/{id}/expediente",
             "/alumnos/{id}/destino", "/alumnos/{id}/curp", "/alumnos/{id}/expediente/{id}", "/alumnos/{id}/expediente/{id}/pdf",
             "/tipos", "/respaldo/bd", "/respaldo/archivos", "/respaldo/estado", "/respaldo/cancelar", "/respaldo/descargar/{nombre}",
             "/api/login", "/api/logout", "/api/sesion", "/feedback/categoria", "/admin/fallas", "/docs", "/openapi.json"}


def normalizar_ruta(ruta):
    r = re.sub(r"^/alumnos/por-curp/.+", "/alumnos/por-curp/{curp}", ruta)
    r = re.sub(r"^/respaldo/descargar/.+", "/respaldo/descargar/{nombre}", r)
    r = re.sub(r"/\d+", "/{id}", r)
    return r if r in CONOCIDAS else "otra"
