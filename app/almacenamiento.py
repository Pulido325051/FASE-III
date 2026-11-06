"""Guardado del PDF en la carpeta de expedientes + registro en la base de datos.

Por defecto sigue la convencion del sistema actual:
    <expedientes>/<idAlumno>_<tipoArchivo>.pdf      ej. 18409_CERT DE SEC.pdf
y en archivos.nombre se guarda solo el nombre del archivo, igual que ahora.
(El formato y la subcarpeta por alumno se configuran en [nombres] de config.ini.)

Si el alumno ya tiene ese tipo de documento se puede reemplazar o agregar un
duplicado con el nombre que escriba el usuario (modo PERSONALIZADO).
"""

import getpass
import logging
import os
import re
import shutil

NUEVO = "nuevo"
REEMPLAZAR = "reemplazar"
ADICIONAL = "adicional"
PERSONALIZADO = "personalizado"   # duplicado con el nombre que escribe el usuario

MAX_NOMBRE_BD = 100   # archivos.nombre es varchar(100)
_RESERVADOS_WINDOWS = {"CON", "PRN", "AUX", "NUL"}

log = logging.getLogger(__name__)


class ErrorAlmacenamiento(Exception):
    pass


def _curp_alumno(alumno):
    curp = (alumno.curp or "").strip().upper()
    # La CURP puede ir en nombres de archivo/carpeta: solo letras y numeros
    if not re.fullmatch(r"[A-Z0-9Ñ]{18}", curp):
        raise ErrorAlmacenamiento(
            f"El alumno id={alumno.id} no tiene una CURP valida en la base de datos ({curp!r})."
        )
    return curp


def _usa_curp(config):
    return config.carpeta_por_alumno or "{curp}" in config.formato_nombre


def carpeta_destino(config, alumno):
    if config.carpeta_por_alumno:
        return os.path.join(config.carpeta_expedientes, _curp_alumno(alumno))
    return config.carpeta_expedientes


def nombre_base(config, alumno, tipo):
    """Nombre sin extension, ej. '18409_CERT DE SEC'."""
    base = config.formato_nombre.format(
        id=int(alumno.id),
        tipo=tipo.texto_bd,
        sufijo=tipo.sufijo,
        curp=_curp_alumno(alumno) if _usa_curp(config) else "",
    ).strip()
    # Nunca separadores de carpeta ni caracteres prohibidos en Windows
    if not re.fullmatch(r"[\w\- .]+", base):
        raise ErrorAlmacenamiento(f"Nombre de archivo no valido: {base!r}")
    return base


def nombre_libre(carpeta, base):
    """<base>.pdf si no existe; si existe, <base>_2.pdf, <base>_3.pdf..."""
    nombre = f"{base}.pdf"
    n = 2
    while os.path.exists(os.path.join(carpeta, nombre)):
        nombre = f"{base}_{n}.pdf"
        n += 1
    return nombre


def nombre_en_bd(config, carpeta, nombre):
    # Igual que el sistema actual: solo el nombre del archivo.
    # Con subcarpeta por alumno se guarda la ruta relativa (ej. CURP\CURP_CURP.pdf).
    if config.carpeta_por_alumno:
        return os.path.relpath(os.path.join(carpeta, nombre), config.carpeta_expedientes)
    return nombre


def prefijo_nombre(config, alumno):
    """Como empieza el nombre de TODOS los archivos del alumno, ej. '18409_'. Todas las carpetas de
    expedientes comparten una sola carpeta, asi que el nombre debe llevar siempre el id del alumno."""
    formato = config.formato_nombre
    cortes = [formato.index(x) for x in ("{tipo}", "{sufijo}") if x in formato]
    prefijo = formato[:min(cortes)] if cortes else ""
    prefijo = prefijo.format(id=int(alumno.id), tipo="", sufijo="",
                             curp=_curp_alumno(alumno) if _usa_curp(config) else "").strip()
    return prefijo or f"{int(alumno.id)}_"


def sugerir_nombre_duplicado(config, alumno, carpeta):
    """Nombre propuesto para un duplicado, como en el sistema anterior: '<id>_DUPLICADO',
    y si ya existe, '<id>_DUPLICADO 2', '<id>_DUPLICADO 3'..."""
    prefijo = prefijo_nombre(config, alumno)
    sufijo, n = "DUPLICADO", 2
    while os.path.exists(os.path.join(carpeta, f"{prefijo}{sufijo}.pdf")):
        sufijo = f"DUPLICADO {n}"
        n += 1
    return sufijo


def validar_nombre_personalizado(config, bd, carpeta, texto, prefijo=None):
    """Valida el nombre escrito por el usuario para un duplicado.
    Regresa el nombre sin extension (se le agrega .pdf). Lanza ErrorAlmacenamiento si no sirve:
    vacio, sin el prefijo del alumno (su id), con simbolos prohibidos, demasiado largo o ya usado
    (en la carpeta o en la BD)."""
    base = re.sub(r"\.pdf$", "", (texto or "").strip(), flags=re.IGNORECASE).strip()
    if not base:
        raise ErrorAlmacenamiento("Escribe el nombre con el que se guardara el archivo.")
    if prefijo:
        if not base.upper().startswith(prefijo.upper()):
            raise ErrorAlmacenamiento(f"El nombre debe empezar con '{prefijo}' (el numero del alumno).")
        if not base[len(prefijo):].strip():
            raise ErrorAlmacenamiento(f"Escribe algo despues de '{prefijo}', por ejemplo: {prefijo}DUPLICADO")
    if (not re.fullmatch(r"[\w\- .]+", base) or base.endswith(".") or not base.strip(". ")
            or base.upper() in _RESERVADOS_WINDOWS or re.fullmatch(r"(COM|LPT)\d", base.upper())):
        raise ErrorAlmacenamiento(
            "El nombre solo puede llevar letras, numeros, espacios, guion (-), guion bajo (_) y punto "
            "(no se permiten / \\ : * ? \" < > |), y no puede terminar en punto."
        )
    nombre = f"{base}.pdf"
    registrado = nombre_en_bd(config, carpeta, nombre)
    if len(registrado) > MAX_NOMBRE_BD:
        raise ErrorAlmacenamiento(f"El nombre es demasiado largo (maximo {MAX_NOMBRE_BD} caracteres con '.pdf').")
    if os.path.exists(os.path.join(carpeta, nombre)):
        raise ErrorAlmacenamiento(f"Ya existe un archivo llamado '{nombre}' en la carpeta de expedientes.\n"
                                  "Escribe un nombre diferente.")
    if bd is not None and bd.contar_referencias(registrado) > 0:
        raise ErrorAlmacenamiento(f"Ya hay un registro en la base de datos con el nombre '{nombre}'.\n"
                                  "Escribe un nombre diferente.")
    return base


def ruta_de_registro(config, nombre):
    """Ruta en disco de un archivo registrado en la BD (archivos.nombre).
    Regresa None si el nombre intentara salirse de la carpeta de expedientes."""
    if not nombre:
        return None
    base = os.path.normpath(config.carpeta_expedientes)
    ruta = os.path.normpath(os.path.join(base, nombre.strip()))
    if not ruta.lower().startswith(base.lower() + os.sep):
        return None
    return ruta


def carpeta_papelera(config):
    """Carpeta donde van los PDF eliminados: junto a la de archivos, ej. ...\\archivos_eliminados"""
    base = os.path.normpath(config.carpeta_expedientes)
    return os.path.join(os.path.dirname(base), os.path.basename(base) + "_eliminados")


def eliminar_documento(bd, config, archivo, alumno, usuario=None):
    """Quita un documento del expediente sin perderlo:
    1) mueve el PDF a la carpeta de eliminados (si ningun otro registro lo usa),
    2) borra el registro de la BD (si falla, regresa el PDF a su lugar),
    3) anota en registro_eliminados.csv quien, cuando y que se elimino."""
    import csv
    from datetime import datetime

    papelera = carpeta_papelera(config)
    try:
        os.makedirs(papelera, exist_ok=True)
    except OSError as e:
        raise ErrorAlmacenamiento(f"No se pudo crear la carpeta de eliminados:\n{papelera}\n\n{e}") from e

    ahora = datetime.now()
    origen = ruta_de_registro(config, archivo.nombre)
    destino = None
    otros = bd.contar_referencias(archivo.nombre) - 1
    if origen and os.path.isfile(origen) and otros <= 0:
        destino = os.path.join(papelera, f"{ahora:%Y%m%d_%H%M%S}_{os.path.basename(origen)}")
        try:
            shutil.move(origen, destino)
        except OSError as e:
            raise ErrorAlmacenamiento(f"No se pudo mover el PDF a la carpeta de eliminados: {e}") from e

    try:
        bd.eliminar_archivo(archivo.id, alumno.id)
    except Exception:
        if destino:
            try:
                shutil.move(destino, origen)
            except OSError:
                log.exception("No se pudo regresar %s a su lugar", destino)
        raise

    registro = os.path.join(papelera, "registro_eliminados.csv")
    nuevo = not os.path.exists(registro)
    try:
        with open(registro, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["fecha_eliminacion", "usuario_windows", "id_registro", "idAlumno", "alumno",
                            "tipoArchivo", "nombre_archivo", "fecha_registro", "pdf_movido_a"])
            w.writerow([f"{ahora:%Y-%m-%d %H:%M:%S}", usuario or getpass.getuser(), archivo.id, alumno.id,
                        alumno.nombre_completo, archivo.tipo, archivo.nombre, archivo.fecha,
                        destino or ("(lo usa otro registro, no se movio)" if otros > 0 else "(no existia el PDF)")])
    except OSError:
        log.exception("No se pudo escribir el registro de eliminados")

    log.info("Eliminado registro id=%s (%s, %s) del alumno id=%s; PDF -> %s",
             archivo.id, archivo.tipo, archivo.nombre, alumno.id, destino)
    return destino


def registrar_cambio_curp(config, alumno, curp_anterior, curp_nueva, usuario=None):
    """Anota en registro_cambios_curp.csv (junto a la carpeta de expedientes) quien cambio que CURP,
    para poder revisarlo o deshacerlo despues."""
    import csv
    from datetime import datetime

    ruta = os.path.join(os.path.dirname(os.path.normpath(config.carpeta_expedientes)), "registro_cambios_curp.csv")
    try:
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["fecha", "usuario_windows", "idAlumno", "alumno", "curp_anterior", "curp_nueva"])
            w.writerow([f"{datetime.now():%Y-%m-%d %H:%M:%S}", usuario or getpass.getuser(), alumno.id,
                        alumno.nombre_completo, curp_anterior, curp_nueva])
    except OSError:
        log.exception("No se pudo escribir %s", ruta)
    log.info("CURP corregida: alumno id=%s (%s) %r -> %r", alumno.id, alumno.nombre_completo,
             curp_anterior, curp_nueva)


def ruta_propuesta(config, alumno, tipo):
    carpeta = carpeta_destino(config, alumno)
    return os.path.join(carpeta, nombre_libre(carpeta, nombre_base(config, alumno, tipo)))


def guardar_documento(bd, config, origen, alumno, tipo, modo=NUEVO, existente=None, nombre_personalizado=None,
                      usuario=None):
    """Copia el PDF a su carpeta y lo registra en la BD.
    Si falla el registro se deshace la copia. Regresa la ruta final."""

    if not os.path.isfile(origen):
        raise ErrorAlmacenamiento(f"Ya no existe el archivo original: {origen}")
    if not os.path.isdir(config.carpeta_expedientes):
        raise ErrorAlmacenamiento(
            f"No se encuentra la carpeta de expedientes:\n{config.carpeta_expedientes}\n\n"
            "Revisa [rutas] expedientes en config.ini (y que la carpeta de red este disponible)."
        )

    carpeta = carpeta_destino(config, alumno)
    os.makedirs(carpeta, exist_ok=True)
    base = nombre_base(config, alumno, tipo)

    if modo == PERSONALIZADO:
        nombre = validar_nombre_personalizado(config, bd, carpeta, nombre_personalizado,
                                              prefijo_nombre(config, alumno)) + ".pdf"
    elif modo == REEMPLAZAR and existente is not None and not config.carpeta_por_alumno \
            and re.fullmatch(r"[\w\- .]+\.pdf", existente.nombre or "", re.I):
        # Se sobrescribe el MISMO archivo del registro existente (ej. "18407_CERT DE SEC .pdf"),
        # asi el sistema actual lo sigue encontrando con el nombre que ya tiene en la BD
        nombre = existente.nombre
    elif modo == REEMPLAZAR:
        nombre = f"{base}.pdf"
    else:
        nombre = nombre_libre(carpeta, base)

    destino = os.path.join(carpeta, nombre)
    temporal = destino + ".tmp"
    respaldo = destino + ".bak"
    hubo_respaldo = False

    try:
        shutil.copy2(origen, temporal)
        if os.path.exists(destino):
            os.replace(destino, respaldo)
            hubo_respaldo = True
        os.replace(temporal, destino)
    except OSError as e:
        if os.path.exists(temporal):
            os.remove(temporal)
        if hubo_respaldo and not os.path.exists(destino):
            os.replace(respaldo, destino)
        raise ErrorAlmacenamiento(f"No se pudo copiar el archivo a {carpeta}: {e}") from e

    usuario = usuario or getpass.getuser()   # en la web: quien inicio sesion
    descripcion = (f"Clasificador ({usuario}) duplicado" if modo == PERSONALIZADO
                   else f"Clasificador ({usuario})")[:45]
    try:
        bd.registrar_archivo(
            id_alumno=alumno.id,
            nombre_archivo=nombre_en_bd(config, carpeta, nombre),
            tipo=tipo.texto_bd,
            descripcion=descripcion,
            reemplazar_id=existente.id if (modo == REEMPLAZAR and existente is not None) else None,
        )
    except Exception:
        # Deshacer: quitar la copia y restaurar el archivo anterior
        try:
            os.remove(destino)
            if hubo_respaldo:
                os.replace(respaldo, destino)
        except OSError:
            log.exception("No se pudo deshacer la copia de %s", destino)
        raise

    if hubo_respaldo:
        try:
            os.remove(respaldo)
        except OSError:
            log.warning("No se pudo borrar el respaldo %s", respaldo)

    log.info("Guardado %s -> %s (alumno id=%s, tipo=%s, modo=%s)",
             origen, destino, alumno.id, tipo.texto_bd, modo)
    return destino
