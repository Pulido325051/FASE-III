"""API web del Clasificador de Documentos Escolares.

Expone el mismo modelo y motor de OCR del Sistema de Expedientes:
    POST /clasificar                -> tipo de documento, CURP, nombre y fecha de nacimiento
                                       (+ alumno encontrado en la BD y, opcional, guardar en su expediente)
    GET  /alumnos?q=...             -> buscar alumnos por nombre, CURP o matricula
    GET  /alumnos/{id}/expediente   -> documentos registrados de un alumno
    GET  /alumnos/por-curp/{curp}   -> alumno(s) con esa CURP
    GET  /alumnos/{id}/destino      -> como se guardaria un documento y que tiene ya el alumno
    POST /guardar                   -> guardar un PDF ya revisado (nuevo, reemplazar o adicional)
    GET  /alumnos/{id}/expediente/{doc}/pdf  -> abrir un PDF del expediente
    DELETE /alumnos/{id}/expediente/{doc}    -> eliminar un documento (el PDF va a 'eliminados')
    GET  /tipos                     -> tipos de documento que maneja el sistema
    GET  /salud                     -> estado del servicio (para Docker y la nube)
    GET  /                          -> pagina web de prueba
    GET  /docs                      -> documentacion interactiva (la genera FastAPI)

La base de datos es OPCIONAL (variables DB_*). En docker-compose se usa una base
de PRUEBA con datos ficticios. Sin base de datos, la API solo clasifica.
"""

import logging
import os
import shutil
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import almacenamiento
from .base_datos import BaseDatos, ErrorBaseDatos, categoria_de_tipo
from .motor_ocr import NO_ENCONTRADA, NO_ENCONTRADO, MotorOCR, curp_valida

BASE = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- configuracion
# Todo se configura con variables de entorno (asi se hace en Docker y en la nube)
MODELO_PATH = os.getenv("MODELO_PATH", str(BASE / "modelo" / "modelo_clasificador.pkl"))
VECTORIZADOR_PATH = os.getenv("VECTORIZADOR_PATH", str(BASE / "modelo" / "vectorizador.pkl"))
TESSERACT_CMD = os.getenv("TESSERACT_CMD") or shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = os.getenv("POPPLER_PATH") or None   # en Linux poppler-utils ya esta en el PATH
MAX_MB = float(os.getenv("MAX_MB", "15"))
MAX_CONCURRENCIA = int(os.getenv("MAX_CONCURRENCIA", "2"))   # el OCR usa mucho CPU

# Mismo formato que el sistema real: <idAlumno>_<tipoArchivo>.pdf y los mismos textos de tipoArchivo
TIPOS = {
    "Actas de nacimiento": ("ACTA DE NAC", "ACTA_NACIMIENTO"),
    "CURP": ("CURP", "CURP"),
    "Certificado Final": ("CERT FINAL", "CERTIFICADO_FINAL"),
    "Certificado Parcial": ("CERT PARCIAL", "CERTIFICADO_PARCIAL"),
    "Certificados Secundaria": ("CERT DE SEC", "CERTIFICADO_SECUNDARIA"),
    "Equivalencia": ("EQUIVALENCIA", "EQUIVALENCIA"),
}
ORDEN = ["CURP", "Certificados Secundaria", "Actas de nacimiento",
         "Certificado Final", "Certificado Parcial", "Equivalencia"]

CONFIG_BD = SimpleNamespace(
    mysql_host=os.getenv("DB_HOST", ""),
    mysql_puerto=int(os.getenv("DB_PORT", "3306")),
    mysql_usuario=os.getenv("DB_USER", ""),
    mysql_contrasena=os.getenv("DB_PASSWORD", ""),
    mysql_base=os.getenv("DB_NAME", "controlescolar_prueba"),
    tabla_alumnos="alumnos",
    tabla_archivos="archivos",
    carpeta_expedientes=os.getenv("ARCHIVOS_DIR", str(BASE / "datos" / "archivos")),
    formato_nombre="{id}_{tipo}",
    carpeta_por_alumno=False,
    tipos={c: SimpleNamespace(categoria=c, texto_bd=t, sufijo=s) for c, (t, s) in TIPOS.items()},
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")

estado = {"motor": None, "bd": None, "inicio": time.time(), "procesados": 0}
limite = threading.BoundedSemaphore(MAX_CONCURRENCIA)


@asynccontextmanager
async def ciclo_de_vida(app):
    # El modelo se carga una sola vez al arrancar el contenedor
    log.info("Cargando modelo: %s", MODELO_PATH)
    estado["motor"] = MotorOCR(MODELO_PATH, VECTORIZADOR_PATH, TESSERACT_CMD, POPPLER_PATH)
    log.info("Modelo listo. Categorias: %s", estado["motor"].categorias)
    if CONFIG_BD.mysql_host:
        estado["bd"] = BaseDatos(CONFIG_BD)
        os.makedirs(CONFIG_BD.carpeta_expedientes, exist_ok=True)
        log.info("Base de datos: %s/%s", CONFIG_BD.mysql_host, CONFIG_BD.mysql_base)
    else:
        log.info("Sin base de datos (DB_HOST vacio): solo clasificacion")
    yield


app = FastAPI(
    title="Clasificador de Documentos Escolares",
    description=(
        "Clasifica documentos escolares escaneados (acta de nacimiento, CURP, certificados, "
        "equivalencia), extrae CURP, nombre y fecha de nacimiento con OCR y, si hay base de datos, "
        "los asocia al expediente del alumno."
    ),
    version="2.0.0",
    lifespan=ciclo_de_vida,
)
app.mount("/static", StaticFiles(directory=BASE / "app" / "static"), name="static")


# ---------------------------------------------------------------- modelos de respuesta
class AlumnoOut(BaseModel):
    id: int
    nombre_completo: str
    curp: str
    matricula: str
    generacion: str
    escuela: str


class DocumentoOut(BaseModel):
    id: int
    tipo_capturado: str
    tipo_reconocido: Optional[str]
    archivo: str
    fecha: str
    pdf_existe: Optional[bool] = None


class Resultado(BaseModel):
    archivo: str
    tipo_documento: str
    confianza: Optional[float] = None
    curp: Optional[str]
    curp_verificada: bool
    nombre: Optional[str]
    fecha_nacimiento: Optional[str]
    segundos: float
    # Solo con base de datos:
    alumno: Optional[AlumnoOut] = None
    encontrado_por: Optional[str] = None          # "curp" | "nombre"
    documentos_del_mismo_tipo: List[DocumentoOut] = []
    guardado_como: Optional[str] = None
    aviso: Optional[str] = None
    aviso_bd: Optional[str] = None                # ej. "Hay 2 alumnos con esa CURP"


class DestinoOut(BaseModel):
    se_guardara_como: str
    existentes: List[DocumentoOut]


class GuardadoOut(BaseModel):
    guardado_como: str


class TipoOut(BaseModel):
    categoria: str
    tipo_bd: str


class Salud(BaseModel):
    estado: str
    modelo_cargado: bool
    base_datos: str
    categorias: list
    base_nombre: Optional[str] = None
    alumnos: Optional[int] = None
    archivos: Optional[int] = None
    documentos_procesados: int
    segundos_activo: int


def _alumno_out(a):
    return AlumnoOut(id=a.id, nombre_completo=a.nombre_completo, curp=a.curp or "", matricula=a.matricula or "",
                     generacion=a.generacion or "", escuela=a.escuela or "")


def _documento_out(d, con_existencia=False):
    existe = None
    if con_existencia:
        ruta = almacenamiento.ruta_de_registro(CONFIG_BD, d.nombre)
        existe = bool(ruta) and os.path.isfile(ruta)
    return DocumentoOut(id=d.id, tipo_capturado=d.tipo or "", tipo_reconocido=categoria_de_tipo(d.tipo),
                        archivo=d.nombre or "", fecha=str(d.fecha), pdf_existe=existe)


def _bd():
    if estado["bd"] is None:
        raise HTTPException(503, "Este despliegue no tiene base de datos configurada (DB_HOST).")
    return estado["bd"]


# ---------------------------------------------------------------- endpoints
@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(BASE / "app" / "static" / "index.html")


@app.get("/salud", response_model=Salud, summary="Estado del servicio")
def salud():
    motor, bd = estado["motor"], estado["bd"]
    estado_bd, alumnos, archivos = "desactivada", None, None
    if bd is not None:
        try:
            alumnos, archivos = bd.probar_conexion()
            estado_bd = "conectada"
        except ErrorBaseDatos:
            estado_bd = "error"
    return Salud(
        estado="ok" if motor else "cargando",
        modelo_cargado=motor is not None,
        base_datos=estado_bd,
        base_nombre=CONFIG_BD.mysql_base if bd is not None else None,
        alumnos=alumnos,
        archivos=archivos,
        categorias=motor.categorias if motor else [],
        documentos_procesados=estado["procesados"],
        segundos_activo=int(time.time() - estado["inicio"]),
    )


def _leer_pdf(archivo):
    """Lee el PDF subido validando tamano y que realmente sea un PDF."""
    contenido = archivo.file.read(int(MAX_MB * 1024 * 1024) + 1)
    if len(contenido) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"El archivo supera el limite de {MAX_MB:g} MB.")
    if not contenido.startswith(b"%PDF"):
        raise HTTPException(415, "El archivo no es un PDF valido.")
    return contenido


@app.post("/clasificar", response_model=Resultado, summary="Clasificar un PDF y extraer sus datos")
def clasificar(
    archivo: UploadFile = File(..., description="Documento escaneado en PDF"),
    guardar: bool = Form(False, description="Guardar en el expediente si el alumno se encontro por CURP"),
):
    motor = estado["motor"]
    if motor is None:
        raise HTTPException(503, "El modelo todavia se esta cargando, intenta en unos segundos.")

    contenido = _leer_pdf(archivo)

    # Archivo temporal con nombre propio: nunca se usa el nombre que manda el usuario
    fd, ruta = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
        inicio = time.time()
        try:
            with limite:
                datos = motor.procesar(ruta)
        except Exception:
            log.exception("Error procesando %s", archivo.filename)
            raise HTTPException(422, "No se pudo leer el PDF (puede estar danado o protegido con contrasena).")
        estado["procesados"] += 1

        res = Resultado(
            archivo=os.path.basename(archivo.filename or "documento.pdf"),
            tipo_documento=datos["categoria"],
            confianza=None if datos.get("confianza") is None else round(datos["confianza"], 4),
            curp=None if datos["curp"] == NO_ENCONTRADA else datos["curp"],
            curp_verificada=datos["curp_verificada"],
            nombre=None if datos["nombre"] == NO_ENCONTRADO else datos["nombre"],
            fecha_nacimiento=None if datos["fecha"] == NO_ENCONTRADA else datos["fecha"],
            segundos=0,
        )
        if estado["bd"] is not None:
            _asociar(res, ruta, guardar)
        res.segundos = round(time.time() - inicio, 1)
        log.info("Clasificado en %.1fs -> %s (alumno: %s)", res.segundos, res.tipo_documento,
                 res.alumno.id if res.alumno else None)
        return res
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


def _asociar(res, ruta_pdf, guardar):
    """Busca al alumno (por CURP y, si no, por nombre) y opcionalmente guarda el documento."""
    bd = estado["bd"]
    try:
        alumnos = bd.buscar_por_curp(res.curp) if res.curp else []
        if len(alumnos) == 1:
            res.encontrado_por = "curp"
        elif len(alumnos) > 1:
            res.aviso_bd = f"Hay {len(alumnos)} alumnos con esa CURP en la BD: elige con 'Buscar por nombre'."
            res.aviso = res.aviso_bd
            return
        elif res.nombre:
            alumnos = bd.buscar_por_nombre(res.nombre, limite=5)
            res.encontrado_por = "nombre" if len(alumnos) == 1 else None
        if len(alumnos) != 1:
            res.aviso = "No se encontro al alumno en la base de datos."
            return
        alumno = alumnos[0]
        res.alumno = _alumno_out(alumno)
        previos = bd.archivos_del_alumno(alumno.id, res.tipo_documento)
        res.documentos_del_mismo_tipo = [_documento_out(d) for d in previos]

        if not guardar:
            return
        # Solo se guarda automaticamente si es seguro: alumno por CURP verificada y sin duplicado
        if res.encontrado_por != "curp" or not res.curp_verificada:
            res.aviso = "No se guardo: el alumno se encontro por nombre o la CURP no esta verificada (requiere revision)."
        elif previos:
            res.aviso = "No se guardo: el alumno ya tiene un documento de este tipo."
        elif res.tipo_documento not in CONFIG_BD.tipos:
            res.aviso = "No se guardo: tipo de documento no configurado."
        else:
            destino = almacenamiento.guardar_documento(bd, CONFIG_BD, ruta_pdf, alumno,
                                                       CONFIG_BD.tipos[res.tipo_documento])
            res.guardado_como = os.path.basename(destino)
    except (ErrorBaseDatos, almacenamiento.ErrorAlmacenamiento) as e:
        log.warning("Base de datos: %s", e)
        res.aviso = f"Base de datos no disponible: {e}"


@app.get("/alumnos", response_model=List[AlumnoOut], summary="Buscar alumnos")
def buscar_alumnos(q: str = Query(..., min_length=2, description="Nombre, CURP o matricula")):
    try:
        return [_alumno_out(a) for a in _bd().buscar_alumnos(q, limite=50)]
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))


@app.get("/alumnos/{id_alumno}/expediente", response_model=List[DocumentoOut],
         summary="Documentos registrados de un alumno (orden: CURP, secundaria, acta, demas)")
def expediente(id_alumno: int):
    try:
        documentos = _bd().archivos_del_alumno(id_alumno)
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))
    salida = [_documento_out(d, con_existencia=True) for d in documentos]
    salida.sort(key=lambda d: (ORDEN.index(d.tipo_reconocido) if d.tipo_reconocido in ORDEN else 99, d.fecha, d.id))
    return salida


# ---------------------------------------------------------------- interfaz de revision (como la app de escritorio)
@app.get("/tipos", response_model=List[TipoOut], summary="Tipos de documento que maneja el sistema")
def tipos():
    return [TipoOut(categoria=c, tipo_bd=TIPOS[c][0]) for c in ORDEN]


@app.get("/alumnos/por-curp/{curp}", response_model=List[AlumnoOut], summary="Alumnos con esa CURP")
def alumnos_por_curp(curp: str):
    curp = curp.strip().upper().replace(" ", "")
    if not curp_valida(curp):
        raise HTTPException(422, "La CURP debe tener 18 caracteres con el formato oficial.")
    try:
        return [_alumno_out(a) for a in _bd().buscar_por_curp(curp)]
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))


def _alumno_o_404(id_alumno):
    try:
        alumno = _bd().alumno_por_id(id_alumno)
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))
    if alumno is None:
        raise HTTPException(404, "No existe ese alumno.")
    return alumno


def _tipo_o_422(categoria):
    if categoria not in CONFIG_BD.tipos:
        raise HTTPException(422, f"Tipo de documento no valido: {categoria}")
    return CONFIG_BD.tipos[categoria]


@app.get("/alumnos/{id_alumno}/destino", response_model=DestinoOut,
         summary="Como se guardaria un documento de ese tipo y que tiene ya el alumno")
def destino(id_alumno: int, categoria: str = Query(...)):
    alumno, tipo = _alumno_o_404(id_alumno), _tipo_o_422(categoria)
    try:
        existentes = _bd().archivos_del_alumno(alumno.id, categoria)
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))
    ruta = almacenamiento.ruta_propuesta(CONFIG_BD, alumno, tipo)
    return DestinoOut(se_guardara_como=os.path.basename(ruta),
                      existentes=[_documento_out(d) for d in existentes])


@app.post("/guardar", response_model=GuardadoOut, summary="Guardar un PDF ya revisado en el expediente")
def guardar(
    archivo: UploadFile = File(...),
    id_alumno: int = Form(...),
    categoria: str = Form(...),
    modo: str = Form("nuevo", description="nuevo | reemplazar | adicional"),
    reemplazar_id: Optional[int] = Form(None, description="Registro a reemplazar (modo reemplazar)"),
):
    alumno, tipo = _alumno_o_404(id_alumno), _tipo_o_422(categoria)
    if modo not in (almacenamiento.NUEVO, almacenamiento.REEMPLAZAR, almacenamiento.ADICIONAL):
        raise HTTPException(422, "modo debe ser nuevo, reemplazar o adicional.")
    bd = _bd()
    try:
        existentes = bd.archivos_del_alumno(alumno.id, categoria)
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))
    existente = None
    if modo == almacenamiento.REEMPLAZAR:
        existente = next((d for d in existentes if d.id == reemplazar_id), None)
        if existente is None:
            raise HTTPException(422, "El documento a reemplazar no existe en el expediente del alumno.")
    elif modo == almacenamiento.NUEVO and existentes:
        raise HTTPException(409, "El alumno ya tiene un documento de este tipo: elige reemplazar o adicional.")

    contenido = _leer_pdf(archivo)
    fd, ruta = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
        destino_final = almacenamiento.guardar_documento(bd, CONFIG_BD, ruta, alumno, tipo, modo, existente)
    except (ErrorBaseDatos, almacenamiento.ErrorAlmacenamiento) as e:
        log.warning("No se guardo: %s", e)
        raise HTTPException(500, f"No se guardo: {e}")
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
    return GuardadoOut(guardado_como=os.path.basename(destino_final))


def _documento_o_404(id_alumno, id_documento):
    alumno = _alumno_o_404(id_alumno)
    try:
        doc = next((d for d in _bd().archivos_del_alumno(alumno.id) if d.id == id_documento), None)
    except ErrorBaseDatos as e:
        raise HTTPException(503, str(e))
    if doc is None:
        raise HTTPException(404, "El documento no existe en el expediente de ese alumno.")
    return alumno, doc


@app.get("/alumnos/{id_alumno}/expediente/{id_documento}/pdf", summary="Abrir el PDF de un documento del expediente")
def abrir_pdf(id_alumno: int, id_documento: int):
    _, doc = _documento_o_404(id_alumno, id_documento)
    ruta = almacenamiento.ruta_de_registro(CONFIG_BD, doc.nombre)
    if not ruta or not os.path.isfile(ruta):
        raise HTTPException(404, "El registro existe pero el archivo PDF no se encuentra en la carpeta.")
    return FileResponse(ruta, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.delete("/alumnos/{id_alumno}/expediente/{id_documento}",
            summary="Eliminar un documento del expediente (el PDF se conserva en la carpeta de eliminados)")
def eliminar(id_alumno: int, id_documento: int):
    alumno, doc = _documento_o_404(id_alumno, id_documento)
    try:
        almacenamiento.eliminar_documento(_bd(), CONFIG_BD, doc, alumno)
    except (ErrorBaseDatos, almacenamiento.ErrorAlmacenamiento) as e:
        raise HTTPException(500, f"No se elimino: {e}")
    return JSONResponse({"eliminado": doc.nombre})
