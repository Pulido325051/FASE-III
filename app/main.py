"""API web del Clasificador de Documentos Escolares.

Expone el mismo modelo y motor de OCR del Sistema de Expedientes:
    POST /clasificar                -> tipo de documento, CURP, nombre y fecha de nacimiento
                                       (+ alumno encontrado en la BD y, opcional, guardar en su expediente)
    GET  /alumnos?q=...             -> buscar alumnos por nombre, CURP o matricula
    GET  /alumnos/{id}/expediente   -> documentos registrados de un alumno
    GET  /alumnos/por-curp/{curp}   -> alumno(s) con esa CURP
    GET  /alumnos/{id}/destino      -> como se guardaria un documento y que tiene ya el alumno
    POST /guardar                   -> guardar un PDF ya revisado (nuevo, reemplazar, adicional o duplicado con nombre)
    POST /alumnos/{id}/curp         -> corregir la CURP de un alumno en la BD (queda en una bitacora)
    POST /respaldo/bd | /respaldo/archivos, GET /respaldo/estado | /respaldo/descargar/{nombre}
                                    -> respaldos de la base de datos (.sql) y de los PDF (.zip)
    POST /api/login, /api/logout    -> contrasena de acceso (solo si se define APP_CLAVE)
    GET  /alumnos/{id}/expediente/{doc}/pdf  -> abrir un PDF del expediente
    DELETE /alumnos/{id}/expediente/{doc}    -> eliminar un documento (el PDF va a 'eliminados')
    GET  /tipos                     -> tipos de documento que maneja el sistema
    GET  /salud                     -> estado del servicio (para Docker y la nube)
    GET  /                          -> pagina web de prueba
    GET  /docs                      -> documentacion interactiva (la genera FastAPI)

La base de datos es OPCIONAL (variables DB_*). En docker-compose se usa una base
de PRUEBA con datos ficticios. Sin base de datos, la API solo clasifica.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import almacenamiento, reglas, respaldos
from .base_datos import BaseDatos, ErrorBaseDatos, categoria_de_tipo
from .motor_ocr import NO_ENCONTRADA, NO_ENCONTRADO, MotorOCR, curp_valida, curp_verificada

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
    # "Duplicado" NO lo detecta la IA (el PDF de un duplicado no dice que lo sea): solo se elige a mano
    "Duplicado": ("DUPLICADO", "DUPLICADO"),
}
MANUALES = {"Duplicado"}   # tipos que no son clases del modelo
ORDEN = ["CURP", "Certificados Secundaria", "Actas de nacimiento",
         "Certificado Final", "Certificado Parcial", "Equivalencia", "Duplicado"]

# Contrasena de acceso (opcional): sin APP_CLAVE la web queda abierta (demo con datos ficticios)
APP_CLAVE = os.getenv("APP_CLAVE", "")
HORAS_SESION = float(os.getenv("HORAS_SESION", "10"))
# Respaldos: solo si se indica la carpeta donde se guardan (docker-compose la define)
RESPALDOS_DIR = os.getenv("RESPALDOS_DIR", "")

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
sesiones = {}              # token -> {"usuario": str, "expira": float}
intentos_fallidos = {}     # ip -> [momentos de intentos de entrada fallidos]
# Un solo respaldo a la vez (el de archivos puede tardar mucho)
trabajo = {"activo": False, "tipo": None, "texto": "", "fraccion": None, "resultado": None, "error": None,
           "cancelar": threading.Event()}
candado_trabajo = threading.Lock()


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
    version="3.0.0",
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
    # Solo si el alumno se encontro por NOMBRE: None = la coincidencia es suficiente (no pide revision);
    # texto = por que una persona debe revisar
    motivo_revision_nombre: Optional[str] = None


class DestinoOut(BaseModel):
    se_guardara_como: str
    existentes: List[DocumentoOut]
    prefijo: str = ""                  # como empieza el nombre de los archivos del alumno, ej. "18409_"
    sugerencia_duplicado: str = ""     # parte editable propuesta para un duplicado, ej. "DUPLICADO"


class GuardadoOut(BaseModel):
    guardado_como: str


class TipoOut(BaseModel):
    categoria: str
    tipo_bd: str
    manual: bool = False               # True = solo se elige a mano (la IA no lo detecta)


class CorregirCurp(BaseModel):
    curp: str


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
    requiere_clave: bool = False
    respaldos: bool = False


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


# ---------------------------------------------------------------- contrasena de acceso (opcional)
RUTAS_PUBLICAS = ("/", "/salud", "/api/login", "/api/logout", "/api/sesion", "/favicon.ico")


def clave_correcta(clave):
    """APP_CLAVE puede ser la contrasena tal cual o el MISMO hash que usa el sistema de escritorio
    en su config.ini ([acceso] clave = pbkdf2_sha256$...)."""
    if APP_CLAVE.startswith("pbkdf2_sha256$"):
        try:
            _, iteraciones, sal, esperado = APP_CLAVE.split("$")
            h = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), int(iteraciones))
            return hmac.compare_digest(h.hex(), esperado)
        except ValueError:
            return False
    return hmac.compare_digest(clave.encode("utf-8"), APP_CLAVE.encode("utf-8"))


def _usuario(request: Request):
    """Quien inicio sesion (None si la web no tiene contrasena o la sesion no es valida)."""
    token = request.cookies.get("sesion", "")
    s = sesiones.get(token)
    if not s or s["expira"] < time.time():
        sesiones.pop(token, None)
        return None
    return s["usuario"]


@app.middleware("http")
async def exigir_sesion(request: Request, call_next):
    if APP_CLAVE and request.method != "OPTIONS":
        ruta = request.url.path
        if ruta not in RUTAS_PUBLICAS and not ruta.startswith("/static/") and _usuario(request) is None:
            return JSONResponse({"detail": "Inicia sesion para continuar."}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    usuario: str
    clave: str


@app.post("/api/login", include_in_schema=False)
def login(datos: Login, request: Request, response: Response):
    if not APP_CLAVE:
        return {"usuario": None}
    ip = request.client.host if request.client else "?"
    recientes = [t for t in intentos_fallidos.get(ip, []) if t > time.time() - 300]
    if len(recientes) >= 5:
        raise HTTPException(429, "Demasiados intentos. Espera 5 minutos.")
    usuario = re.sub(r"[^\w .\-]", "", datos.usuario).strip()[:30]
    if not usuario or not clave_correcta(datos.clave):
        intentos_fallidos[ip] = recientes + [time.time()]
        log.warning("Acceso denegado desde %s", ip)
        raise HTTPException(401, "Nombre o contrasena incorrectos.")
    intentos_fallidos.pop(ip, None)
    token = secrets.token_urlsafe(32)
    sesiones[token] = {"usuario": usuario, "expira": time.time() + HORAS_SESION * 3600}
    response.set_cookie("sesion", token, httponly=True, samesite="strict", max_age=int(HORAS_SESION * 3600))
    log.info("Entro %s desde %s", usuario, ip)
    return {"usuario": usuario}


@app.post("/api/logout", include_in_schema=False)
def logout(request: Request, response: Response):
    sesiones.pop(request.cookies.get("sesion", ""), None)
    response.delete_cookie("sesion")
    return {"ok": True}


@app.get("/api/sesion", include_in_schema=False)
def sesion(request: Request):
    return {"usuario": _usuario(request), "requiere_clave": bool(APP_CLAVE)}


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
        requiere_clave=bool(APP_CLAVE),
        respaldos=bool(RESPALDOS_DIR) and bd is not None,
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
        if res.encontrado_por == "nombre":
            res.motivo_revision_nombre = reglas.motivo_nombre_dudoso(alumno, res.curp, res.nombre,
                                                                     res.fecha_nacimiento)
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
    return [TipoOut(categoria=c, tipo_bd=TIPOS[c][0], manual=c in MANUALES) for c in ORDEN]


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
    carpeta = almacenamiento.carpeta_destino(CONFIG_BD, alumno)
    return DestinoOut(se_guardara_como=os.path.basename(ruta),
                      existentes=[_documento_out(d) for d in existentes],
                      prefijo=almacenamiento.prefijo_nombre(CONFIG_BD, alumno),
                      sugerencia_duplicado=almacenamiento.sugerir_nombre_duplicado(CONFIG_BD, alumno, carpeta))


@app.post("/guardar", response_model=GuardadoOut, summary="Guardar un PDF ya revisado en el expediente")
def guardar(
    request: Request,
    archivo: UploadFile = File(...),
    id_alumno: int = Form(...),
    categoria: str = Form(...),
    modo: str = Form("nuevo", description="nuevo | reemplazar | adicional | personalizado"),
    reemplazar_id: Optional[int] = Form(None, description="Registro a reemplazar (modo reemplazar)"),
    nombre: Optional[str] = Form(None, description="Nombre completo (modo personalizado): empieza con el id del "
                                                   "alumno, ej. 18409_DUPLICADO; el .pdf se agrega solo"),
):
    alumno, tipo = _alumno_o_404(id_alumno), _tipo_o_422(categoria)
    if modo not in (almacenamiento.NUEVO, almacenamiento.REEMPLAZAR, almacenamiento.ADICIONAL,
                    almacenamiento.PERSONALIZADO):
        raise HTTPException(422, "modo debe ser nuevo, reemplazar, adicional o personalizado.")
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
        raise HTTPException(409, "El alumno ya tiene un documento de este tipo: elige reemplazar o agregarlo "
                                 "como duplicado con otro nombre.")
    elif modo == almacenamiento.PERSONALIZADO:
        # El nombre debe llevar el id del alumno (todos los PDF comparten una sola carpeta)
        try:
            almacenamiento.validar_nombre_personalizado(
                CONFIG_BD, bd, almacenamiento.carpeta_destino(CONFIG_BD, alumno), nombre or "",
                almacenamiento.prefijo_nombre(CONFIG_BD, alumno))
        except almacenamiento.ErrorAlmacenamiento as e:
            raise HTTPException(422, str(e))
        except ErrorBaseDatos as e:
            raise HTTPException(503, str(e))

    contenido = _leer_pdf(archivo)
    fd, ruta = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
        destino_final = almacenamiento.guardar_documento(bd, CONFIG_BD, ruta, alumno, tipo, modo, existente,
                                                         nombre, usuario=_usuario(request))
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
def eliminar(request: Request, id_alumno: int, id_documento: int):
    alumno, doc = _documento_o_404(id_alumno, id_documento)
    try:
        almacenamiento.eliminar_documento(_bd(), CONFIG_BD, doc, alumno, usuario=_usuario(request))
    except (ErrorBaseDatos, almacenamiento.ErrorAlmacenamiento) as e:
        raise HTTPException(500, f"No se elimino: {e}")
    return JSONResponse({"eliminado": doc.nombre})


@app.post("/alumnos/{id_alumno}/curp", response_model=AlumnoOut,
          summary="Corregir la CURP de un alumno en la base de datos (queda anotado en una bitacora)")
def corregir_curp(request: Request, id_alumno: int, datos: CorregirCurp):
    """La CURP de algunos alumnos esta mal escrita en la BD y por eso no se les encuentra. Solo cambia si la
    CURP nueva tiene el digito verificador correcto y ninguna otra persona la tiene."""
    alumno = _alumno_o_404(id_alumno)
    nueva = datos.curp.strip().upper().replace(" ", "")
    if not curp_valida(nueva):
        raise HTTPException(422, "La CURP debe tener 18 caracteres con el formato oficial.")
    if not curp_verificada(nueva):
        raise HTTPException(422, "Esa CURP no pasa la verificacion (el digito verificador no cuadra): "
                                 "probablemente tiene una letra o numero mal.")
    anterior = alumno.curp or ""
    if nueva == anterior.strip().upper():
        raise HTTPException(422, "La CURP del alumno en la base de datos ya es esa.")
    try:
        _bd().actualizar_curp(alumno.id, anterior, nueva)
    except ErrorBaseDatos as e:
        raise HTTPException(409, str(e))
    almacenamiento.registrar_cambio_curp(CONFIG_BD, alumno, anterior, nueva, usuario=_usuario(request))
    alumno.curp = nueva
    return _alumno_out(alumno)


# ---------------------------------------------------------------- respaldos
PATRON_RESPALDO = re.compile(r"(BD|Archivos)_[\w\-]+\.(sql|zip|rar)")


def _respaldos_o_404():
    if not RESPALDOS_DIR or estado["bd"] is None:
        raise HTTPException(404, "Los respaldos no estan habilitados en este despliegue (falta RESPALDOS_DIR).")


def _lista_respaldos():
    if not RESPALDOS_DIR or not os.path.isdir(RESPALDOS_DIR):
        return []
    salida = []
    for nombre in sorted(os.listdir(RESPALDOS_DIR), reverse=True):
        ruta = os.path.join(RESPALDOS_DIR, nombre)
        if PATRON_RESPALDO.fullmatch(nombre) and os.path.isfile(ruta):
            info = os.stat(ruta)
            salida.append({"nombre": nombre, "tamano": info.st_size,
                           "fecha": time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime))})
    return salida


def _estado_trabajo():
    return {"activo": trabajo["activo"], "tipo": trabajo["tipo"], "texto": trabajo["texto"],
            "fraccion": trabajo["fraccion"], "resultado": trabajo["resultado"], "error": trabajo["error"],
            "respaldos": _lista_respaldos()}


def _correr_trabajo(tipo):
    def progreso(texto, fraccion):
        trabajo["texto"], trabajo["fraccion"] = texto, fraccion

    cancelado = trabajo["cancelar"].is_set
    try:
        if tipo == "bd":
            ruta, resumen = respaldos.respaldar_bd(estado["bd"], RESPALDOS_DIR, progreso, cancelado)
            trabajo["resultado"] = {"archivo": os.path.basename(ruta), "tamano": os.path.getsize(ruta),
                                    "tablas": [{"tabla": t, "filas": n} for t, n in resumen]}
        else:
            ruta, cantidad, no_leidos = respaldos.respaldar_archivos(CONFIG_BD, RESPALDOS_DIR, progreso, cancelado)
            trabajo["resultado"] = {"archivo": os.path.basename(ruta), "tamano": os.path.getsize(ruta),
                                    "archivos": cantidad, "no_leidos": no_leidos}
    except respaldos.RespaldoCancelado:
        trabajo["error"] = "cancelado"
    except Exception as e:
        log.exception("Error en el respaldo")
        trabajo["error"] = str(e)
    finally:
        trabajo["activo"] = False


def _iniciar_trabajo(tipo):
    _respaldos_o_404()
    with candado_trabajo:
        if trabajo["activo"]:
            raise HTTPException(409, "Ya hay un respaldo en curso: espera a que termine o cancelalo.")
        trabajo.update(activo=True, tipo=tipo, texto="Preparando...", fraccion=None, resultado=None, error=None)
        trabajo["cancelar"].clear()
    threading.Thread(target=_correr_trabajo, args=(tipo,), daemon=True).start()
    return _estado_trabajo()


@app.post("/respaldo/bd", summary="Respaldar toda la base de datos en un archivo .sql")
def respaldo_bd():
    return _iniciar_trabajo("bd")


@app.post("/respaldo/archivos", summary="Respaldar todos los PDF de los expedientes en un archivo .zip")
def respaldo_archivos():
    return _iniciar_trabajo("archivos")


@app.get("/respaldo/estado", summary="Avance del respaldo en curso y respaldos ya hechos")
def respaldo_estado():
    _respaldos_o_404()
    return _estado_trabajo()


@app.post("/respaldo/cancelar", summary="Cancelar el respaldo en curso")
def respaldo_cancelar():
    _respaldos_o_404()
    trabajo["cancelar"].set()
    return _estado_trabajo()


@app.get("/respaldo/descargar/{nombre}", summary="Descargar un respaldo ya hecho")
def respaldo_descargar(nombre: str):
    _respaldos_o_404()
    ruta = os.path.join(RESPALDOS_DIR, nombre)
    if not PATRON_RESPALDO.fullmatch(nombre) or not os.path.isfile(ruta):
        raise HTTPException(404, "Ese respaldo no existe.")
    return FileResponse(ruta, filename=nombre, media_type="application/octet-stream")
