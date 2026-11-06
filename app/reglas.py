"""Reglas de revision del Sistema de Expedientes (iguales a las de la app de escritorio).

Deciden cuando un documento se puede dar por bueno solo y cuando una persona debe revisarlo.
"""

import difflib

from .motor_ocr import NO_ENCONTRADA, curp_valida, fecha_desde_curp

# Umbral de parecido entre el nombre leido en el documento y el del alumno en la BD
UMBRAL_NOMBRE = 0.8


def similitud_nombres(a, b):
    """Fraccion de palabras de 'a' que aparecen (aproximadamente) en 'b'. Ignora el orden."""
    pa, pb = a.upper().split(), b.upper().split()
    if not pa or not pb:
        return 0.0
    coincidencias = sum(1 for p in pa if difflib.get_close_matches(p, pb, n=1, cutoff=0.8))
    return coincidencias / len(pa)


def motivo_nombre_dudoso(alumno, curp_leida, nombre_leido, fecha_leida):
    """Alumno encontrado solo por NOMBRE. Regresa None si la coincidencia es suficiente para no
    pedir revision, o el motivo (texto para la persona) si hay que revisar.

    Es suficiente cuando: el documento no trae CURP, el nombre coincide casi completo (en los dos
    sentidos) y, si se leyo la fecha de nacimiento, concuerda con la CURP del alumno en la BD."""
    if curp_leida:
        return ("Alumno encontrado por NOMBRE (la CURP del documento no esta en la BD): "
                "confirma que sea la persona correcta.")
    nombre_bd = alumno.nombre_completo
    if min(similitud_nombres(nombre_leido or "", nombre_bd), similitud_nombres(nombre_bd, nombre_leido or "")) \
            < UMBRAL_NOMBRE:
        return "Alumno encontrado por NOMBRE, pero el nombre no coincide por completo: confirma la persona."
    curp_bd = (alumno.curp or "").strip().upper()
    if fecha_leida and fecha_leida != NO_ENCONTRADA and curp_valida(curp_bd):
        if fecha_desde_curp(curp_bd) != fecha_leida:
            return (f"Alumno encontrado por NOMBRE, pero la fecha de nacimiento del documento ({fecha_leida}) "
                    "no coincide con la de su CURP en la BD: revisa que sea la persona correcta.")
    return None
