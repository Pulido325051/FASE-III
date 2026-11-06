"""Respaldos desde el propio programa (no hace falta mysqldump ni instalar nada).

- respaldar_bd:       toda la base de datos en un archivo .sql (estructura + datos), tomada de un
                      solo instante para que quede consistente aunque otras personas esten trabajando.
- respaldar_archivos: todos los PDF de la carpeta de expedientes en un RAR (si hay WinRAR) o en un ZIP.

Los PDF ya vienen comprimidos, asi que se guardan sin recomprimir: es mas rapido y pesa casi igual.
Nada de esto modifica la base de datos ni la carpeta de expedientes (solo lee).
"""

import logging
import os
import shutil
import subprocess
import zipfile
from datetime import datetime

import pymysql
import pymysql.cursors

from .base_datos import ErrorBaseDatos

log = logging.getLogger(__name__)

FILAS_POR_INSERT = 500
CARPETA_EN_RESPALDO = "archivos"   # nombre de la carpeta raiz dentro del RAR/ZIP


class ErrorRespaldo(Exception):
    pass


class RespaldoCancelado(Exception):
    pass


def _ruta_libre(carpeta, base, extension):
    ruta = os.path.join(carpeta, base + extension)
    n = 2
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, f"{base}_{n}{extension}")
        n += 1
    return ruta


def _entre_comillas(nombre):
    return "`" + nombre.replace("`", "``") + "`"


def tamano_legible(bytes_):
    for unidad in ("bytes", "KB", "MB", "GB"):
        if bytes_ < 1024 or unidad == "GB":
            return f"{bytes_:.0f} {unidad}" if unidad == "bytes" else f"{bytes_:.1f} {unidad}"
        bytes_ /= 1024


# ----------------------------------------------------------------------------
# BASE DE DATOS
# ----------------------------------------------------------------------------
def _valor_sql(con, valor):
    # Datos binarios (BLOB) en hexadecimal: no dependen de la codificacion del archivo
    if isinstance(valor, (bytes, bytearray)):
        return "0x" + bytes(valor).hex() if valor else "''"
    return con.escape(valor)


def _volcar_tabla(con, f, tabla, cancelado):
    q = _entre_comillas(tabla)
    with con.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE {q}")
        ddl = cur.fetchone()[1]
    f.write(f"--\n-- Tabla {tabla}\n--\nDROP TABLE IF EXISTS {q};\n{ddl};\n\n")

    filas = 0
    lote = []
    cur = con.cursor(pymysql.cursors.SSCursor)   # sin cargar toda la tabla en memoria
    try:
        cur.execute(f"SELECT * FROM {q}")
        columnas = ", ".join(_entre_comillas(d[0]) for d in cur.description)
        encabezado = f"INSERT INTO {q} ({columnas}) VALUES\n"
        for fila in cur:
            lote.append("(" + ",".join(_valor_sql(con, v) for v in fila) + ")")
            filas += 1
            if len(lote) >= FILAS_POR_INSERT:
                f.write(encabezado + ",\n".join(lote) + ";\n")
                lote = []
                if cancelado():
                    raise RespaldoCancelado()
        if lote:
            f.write(encabezado + ",\n".join(lote) + ";\n")
    finally:
        cur.close()
    f.write("\n")
    return filas


def respaldar_bd(bd, destino, progreso, cancelado):
    """Regresa (ruta del .sql, [(tabla, filas), ...])."""
    os.makedirs(destino, exist_ok=True)
    base = bd.config.mysql_base
    ruta = _ruta_libre(destino, f"BD_{base}_{datetime.now():%Y-%m-%d_%H%M%S}", ".sql")
    temporal = ruta + ".tmp"
    resumen = []

    progreso("Conectando a la base de datos...", None)
    try:
        con = bd._conectar()
    except ErrorBaseDatos as e:
        raise ErrorRespaldo(str(e)) from e
    try:
        with con.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cur.execute("SHOW FULL TABLES")
            objetos = cur.fetchall()
        tablas = [n for n, t in objetos if t == "BASE TABLE"]
        vistas = [n for n, t in objetos if t != "BASE TABLE"]

        with open(temporal, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"-- Respaldo de la base de datos {base}\n"
                    f"-- Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                    "-- Hecho con el Sistema de Expedientes. Para restaurar: importa este archivo en MySQL "
                    "(DBeaver > Ejecutar script, o el cliente mysql).\n\n"
                    "SET NAMES utf8mb4;\nSET SESSION sql_mode = '';\nSET FOREIGN_KEY_CHECKS = 0;\n"
                    "SET UNIQUE_CHECKS = 0;\n\n")
            for i, tabla in enumerate(tablas):
                if cancelado():
                    raise RespaldoCancelado()
                progreso(f"Copiando la tabla '{tabla}' ({i + 1} de {len(tablas)})...", i / max(1, len(tablas)))
                resumen.append((tabla, _volcar_tabla(con, f, tabla, cancelado)))
            for vista in vistas:
                with con.cursor() as cur:
                    cur.execute(f"SHOW CREATE VIEW {_entre_comillas(vista)}")
                    ddl = cur.fetchone()[1]
                f.write(f"DROP VIEW IF EXISTS {_entre_comillas(vista)};\n{ddl};\n\n")
            f.write("SET FOREIGN_KEY_CHECKS = 1;\nSET UNIQUE_CHECKS = 1;\n\n-- Fin del respaldo\n")
        con.rollback()   # cierra la lectura consistente
        os.replace(temporal, ruta)
    except pymysql.MySQLError as e:
        raise ErrorRespaldo(f"Error al leer la base de datos: {e}") from e
    except OSError as e:
        raise ErrorRespaldo(f"No se pudo escribir el respaldo en {destino}: {e}") from e
    finally:
        con.close()
        if os.path.exists(temporal):
            try:
                os.remove(temporal)
            except OSError:
                pass
    log.info("Respaldo de BD: %s (%s)", ruta, resumen)
    return ruta, resumen


# ----------------------------------------------------------------------------
# ARCHIVOS
# ----------------------------------------------------------------------------
def buscar_rar():
    """Ruta de Rar.exe (viene con WinRAR) o None."""
    candidatos = [os.path.join(os.environ.get(v, ""), "WinRAR", "Rar.exe")
                  for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432") if os.environ.get(v)]
    candidatos.append(shutil.which("rar") or "")
    return next((c for c in candidatos if c and os.path.isfile(c)), None)


def escanear(carpeta, cancelado=lambda: False):
    """(cantidad de archivos, bytes) de todo lo que hay en la carpeta."""
    cantidad = total = 0
    pendientes = [carpeta]
    while pendientes:
        if cancelado():
            raise RespaldoCancelado()
        try:
            with os.scandir(pendientes.pop()) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        pendientes.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        cantidad += 1
                        total += e.stat().st_size
        except OSError:
            log.exception("No se pudo leer una carpeta al contar archivos")
    return cantidad, total


def _esta_dentro(ruta, carpeta):
    ruta, carpeta = os.path.normcase(os.path.abspath(ruta)), os.path.normcase(os.path.abspath(carpeta))
    return ruta == carpeta or ruta.startswith(carpeta.rstrip(os.sep) + os.sep)


def respaldar_archivos(config, destino, progreso, cancelado, registrar_proceso=lambda p: None):
    """Regresa (ruta del .rar/.zip, cantidad de archivos, no_leidos)."""
    origen = os.path.normpath(config.carpeta_expedientes)
    if not os.path.isdir(origen):
        raise ErrorRespaldo(f"No se encuentra la carpeta de expedientes:\n{origen}\n\n"
                            "Revisa que estes conectado a la red del servidor.")
    if _esta_dentro(destino, origen):
        raise ErrorRespaldo("La carpeta donde guardas el respaldo no puede estar dentro de la carpeta de "
                            "expedientes. Elige otra (por ejemplo, un disco externo).")
    try:
        os.makedirs(destino, exist_ok=True)
    except OSError as e:
        raise ErrorRespaldo(f"No se pudo crear la carpeta de respaldos:\n{destino}\n\n{e}") from e

    progreso("Contando los archivos (puede tardar un poco)...", None)
    cantidad, total = escanear(origen, cancelado)
    if cantidad == 0:
        raise ErrorRespaldo("La carpeta de expedientes no tiene archivos.")
    libre = shutil.disk_usage(destino).free
    if libre < total * 1.03 + 100 * 1024 * 1024:
        raise ErrorRespaldo(f"No hay espacio suficiente en el destino.\n\nHacen falta unos {tamano_legible(total)} "
                            f"y hay {tamano_legible(libre)} libres.")

    marca = f"{datetime.now():%Y-%m-%d_%H%M%S}"
    rar = buscar_rar()
    if rar:
        ruta = _ruta_libre(destino, f"Archivos_{marca}", ".rar")
        no_leidos = _crear_rar(rar, origen, ruta, cantidad, progreso, cancelado, registrar_proceso)
    else:
        ruta = _ruta_libre(destino, f"Archivos_{marca}", ".zip")
        no_leidos = _crear_zip(origen, ruta, cantidad, progreso, cancelado)
    log.info("Respaldo de archivos: %s (%s archivos, %s sin leer)", ruta, cantidad, no_leidos)
    return ruta, cantidad, no_leidos


def _borrar(ruta):
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
    except OSError:
        log.exception("No se pudo borrar el respaldo incompleto %s", ruta)


def _crear_rar(rar, origen, ruta, cantidad, progreso, cancelado, registrar_proceso):
    # a = agregar, -r subcarpetas, -m0 sin recomprimir (los PDF ya van comprimidos), -ep1 sin la ruta de red
    # completa dentro del RAR, -idp sin porcentajes (solo una linea por archivo), -y responder si a todo
    comando = [rar, "a", "-r", "-m0", "-ep1", "-idp", "-y", "-mt4", ruta, origen]
    try:
        proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise ErrorRespaldo(f"No se pudo iniciar WinRAR: {e}") from e
    registrar_proceso(proceso)
    hechos, errores, ultimas = 0, 0, []
    marca_carpeta = os.path.basename(origen) + "\\"
    try:
        for linea in proceso.stdout:
            texto = linea.decode("cp850", errors="replace").strip()
            if not texto:
                continue
            ultimas = (ultimas + [texto])[-6:]
            # WinRAR escribe una linea por archivo ("Anadiendo carpeta\archivo.pdf  Aceptar"), segun el idioma
            if marca_carpeta in texto and not texto.startswith(("Creando", "Creating")):
                hechos += 1
                if hechos % 25 == 0 or hechos == cantidad:
                    progreso(f"Guardando en el RAR: {hechos:,} de {cantidad:,} archivos", min(1.0, hechos / cantidad))
            elif "Cannot" in texto or "No se puede" in texto:
                errores += 1
            if cancelado():
                proceso.kill()
                raise RespaldoCancelado()
        codigo = proceso.wait()
        if cancelado():   # el usuario cancelo y se cerro WinRAR desde la ventana
            raise RespaldoCancelado()
    except BaseException:
        if proceso.poll() is None:
            proceso.kill()
        proceso.wait()
        _borrar(ruta)
        raise
    if codigo not in (0, 1) or not os.path.isfile(ruta):   # 1 = aviso (ej. algun archivo no se pudo leer)
        _borrar(ruta)
        raise ErrorRespaldo("WinRAR no pudo crear el respaldo (codigo %s).\n\n%s" % (codigo, "\n".join(ultimas[-3:])))
    return errores if codigo == 1 else 0


def _crear_zip(origen, ruta, cantidad, progreso, cancelado):
    hechos = no_leidos = 0
    try:
        with zipfile.ZipFile(ruta, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for raiz, _, archivos in os.walk(origen):
                for nombre in archivos:
                    if cancelado():
                        raise RespaldoCancelado()
                    completa = os.path.join(raiz, nombre)
                    try:
                        z.write(completa, os.path.join(CARPETA_EN_RESPALDO, os.path.relpath(completa, origen)))
                    except OSError:
                        no_leidos += 1
                        log.exception("No se pudo respaldar %s", completa)
                    hechos += 1
                    if hechos % 25 == 0 or hechos == cantidad:
                        progreso(f"Guardando en el ZIP: {hechos:,} de {cantidad:,} archivos",
                                 min(1.0, hechos / cantidad))
    except BaseException as e:
        _borrar(ruta)
        if isinstance(e, OSError):
            raise ErrorRespaldo(f"No se pudo escribir el respaldo: {e}") from e
        raise
    return no_leidos
