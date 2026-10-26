"""Genera PDFs de ejemplo con datos FICTICIOS para probar la API sin usar
documentos reales de alumnos.

    python ejemplos/generar_ejemplos.py
"""

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.motor_ocr import digito_verificador  # noqa: E402

AQUI = Path(__file__).resolve().parent
ANCHO, ALTO = 2550, 3300          # carta a 300 dpi

# Alumna ficticia (la CURP tiene formato y digito verificador validos, pero es inventada)
NOMBRE, AP1, AP2 = "MARIA FERNANDA", "EJEMPLO", "LOPEZ"
CURP17 = "EELM060312MCHJPRA"
CURP = CURP17 + digito_verificador(CURP17)


def fuente(tam, negrita=False):
    for nombre in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if negrita else ("arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def texto(d, xy, t, tam=42, negrita=False, centro=False):
    f = fuente(tam, negrita)
    x, y = xy
    if centro:
        x = (ANCHO - d.textlength(t, font=f)) / 2
    d.text((x, y), t, fill="black", font=f)


def parrafo(d, y, lineas, tam=38, x=220, salto=58):
    for linea in lineas:
        texto(d, (x, y), linea, tam)
        y += salto
    return y


def constancia_curp():
    im = Image.new("RGB", (ANCHO, ALTO), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((120, 120, ANCHO - 120, 1250), outline=(40, 110, 60), width=10)
    texto(d, (0, 220), "ESTADOS UNIDOS MEXICANOS", 78, True, True)
    texto(d, (0, 330), "CONSTANCIA DE LA CLAVE UNICA", 60, False, True)
    texto(d, (0, 410), "DE REGISTRO DE POBLACION", 60, False, True)
    texto(d, (500, 560), "Clave:", 44, True)
    texto(d, (500, 620), CURP, 70, True)
    texto(d, (500, 760), "Nombre", 44, True)
    texto(d, (500, 820), f"{NOMBRE} {AP1} {AP2}", 64, True)
    texto(d, (500, 990), "Fecha de inscripcion        Folio              Entidad de registro", 40, True)
    texto(d, (500, 1050), "12/04/2006                  000000001        CHIHUAHUA", 40)
    texto(d, (220, 1450), f"{NOMBRE} {AP1} {AP2}", 40, True)
    texto(d, (220, 1560), "PRESENTE", 40)
    parrafo(d, 1680, [
        "El derecho a la identidad esta consagrado en nuestra Constitucion. En la Secretaria de",
        "Gobernacion trabajamos todos los dias para garantizar que las y los mexicanos gocen de",
        "este derecho plenamente; y de esta forma puedan acceder de manera mas sencilla a",
        "tramites y servicios.",
        "",
        "Nuestro objetivo es que el uso y adopcion de la Clave Unica de Registro de Poblacion",
        "(CURP) permita a la poblacion tener una sola llave de acceso a servicios",
        "gubernamentales.",
        "",
        "La impresion de la constancia CURP en papel bond, a color o blanco y negro, es valida",
        "y debe ser aceptada para realizar todo tramite. TRAMITE GRATUITO.",
    ])
    texto(d, (0, 3150), "DOCUMENTO FICTICIO PARA PRUEBAS - SIN VALIDEZ", 34, True, True)
    return im


def acta_nacimiento():
    im = Image.new("RGB", (ANCHO, ALTO), "white")
    d = ImageDraw.Draw(im)
    texto(d, (1500, 260), "Clave Unica de Registro de Poblacion", 40)
    texto(d, (1500, 320), CURP, 48, True)
    texto(d, (300, 520), "Estados Unidos Mexicanos", 72, True)
    texto(d, (420, 620), "Acta de Nacimiento", 64, True)
    texto(d, (1500, 520), "Entidad de Registro", 40)
    texto(d, (1500, 580), "CHIHUAHUA", 44, True)
    texto(d, (1500, 660), "Municipio de Registro", 40)
    texto(d, (1500, 720), "CHIHUAHUA", 44, True)
    texto(d, (0, 900), "Datos de la Persona Registrada", 46, True, True)
    texto(d, (300, 1000), f"{NOMBRE}             {AP1}                {AP2}", 46, True)
    texto(d, (300, 1070), "Nombre(s)                           Primer Apellido              Segundo Apellido", 36)
    texto(d, (300, 1200), "MUJER         12 DE MARZO DE 2006         CHIHUAHUA, CHIHUAHUA", 46, True)
    texto(d, (300, 1270), "Sexo            Fecha de Nacimiento            Lugar de Nacimiento", 36)
    texto(d, (0, 1420), "Datos de Filiacion de la Persona Registrada", 46, True, True)
    texto(d, (300, 1520), "JOSE LUIS              EJEMPLO              RUIZ              MEXICANA", 44, True)
    texto(d, (300, 1590), "Nombre(s) Padre      Primer Apellido      Segundo Apellido      Nacionalidad", 34)
    texto(d, (300, 1700), "ROSA MARIA             LOPEZ                SANCHEZ           MEXICANA", 44, True)
    texto(d, (300, 1770), "Nombre(s) Madre      Primer Apellido      Segundo Apellido      Nacionalidad", 34)
    parrafo(d, 2000, [
        "LA PRESENTE CERTIFICACION ES UN EXTRACTO DEL ACTA CUYOS DATOS ARRIBA SE",
        "PRECISAN Y QUE SE EXPIDE FIRMADA ELECTRONICAMENTE, CON FUNDAMENTO EN LOS",
        "ARTICULOS 49 DEL CODIGO CIVIL DEL ESTADO DE CHIHUAHUA Y 2 DEL REGLAMENTO",
        "INTERIOR DEL REGISTRO CIVIL DEL ESTADO DE CHIHUAHUA.",
    ], 38, 300)
    texto(d, (0, 2600), "DIRECTORA DEL REGISTRO CIVIL", 40, False, True)
    texto(d, (0, 3150), "DOCUMENTO FICTICIO PARA PRUEBAS - SIN VALIDEZ", 34, True, True)
    return im


if __name__ == "__main__":
    for nombre, generar in [("constancia_curp_ficticia.pdf", constancia_curp),
                            ("acta_nacimiento_ficticia.pdf", acta_nacimiento)]:
        ruta = AQUI / nombre
        generar().save(ruta, "PDF", resolution=300)
        print("Generado:", ruta, f"(CURP ficticia {CURP})")
