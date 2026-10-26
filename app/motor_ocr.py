"""Clasificacion del documento y extraccion de CURP, nombre y fecha de nacimiento.

Es la misma logica de 03_Clasificacion_Extraccion.ipynb, empaquetada para el programa.
"""

import difflib
import os
import re

import joblib
import numpy as np
import pytesseract
from PIL import Image, ImageOps
from pdf2image import convert_from_path, pdfinfo_from_path


# ----------------------------------------------------------------------------
# OCR y clasificacion
# ----------------------------------------------------------------------------
def limpiar_texto(texto):
    # Misma limpieza que en el entrenamiento del modelo
    texto = texto.upper()
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"[^A-Z0-9ÁÉÍÓÚÜÑ ]", " ", texto)
    return " ".join(p for p in texto.split() if len(p) > 2)


def _corridas(mascara, largo, eje):
    # Marca los pixeles que forman parte de una linea recta de >= 'largo' pixeles
    n = mascara.shape[eje]
    if n < largo:
        return np.zeros_like(mascara)
    c = np.cumsum(mascara.astype(np.int32), axis=eje)
    c = np.insert(c, 0, 0, axis=eje)
    ventana = c.take(range(largo, n + 1), axis=eje) - c.take(range(0, n - largo + 1), axis=eje)
    completa = (ventana == largo).astype(np.int32)
    c2 = np.insert(np.cumsum(completa, axis=eje), 0, 0, axis=eje)
    idx = np.arange(n)
    hi = np.minimum(idx, n - largo) + 1
    lo = np.clip(idx - largo + 1, 0, n - largo + 1)
    return (c2.take(hi, axis=eje) - c2.take(lo, axis=eje)) > 0


def preprocesar_fondo_rojo(imagen, umbral=150, largo_linea=120):
    # Fondo rojo/rosa de las actas: en el canal rojo queda casi blanco.
    # Ademas se quitan las lineas de las tablas, que confunden a Tesseract.
    rojo = np.asarray(imagen.convert("RGB"))[..., 0]
    oscuro = rojo < umbral
    lineas = _corridas(oscuro, largo_linea, 1) | _corridas(oscuro, largo_linea, 0)
    oscuro &= ~lineas
    return Image.fromarray(np.where(oscuro, 0, 255).astype(np.uint8))


def escala_grises(imagen, factor=1.6):
    # Escaneos deslavados/verdes: el texto es oscuro en todos los canales
    gris = Image.fromarray(np.asarray(imagen.convert("RGB")).min(axis=2))
    gris = ImageOps.autocontrast(gris, cutoff=1)
    return gris.resize((int(gris.width * factor), int(gris.height * factor)), Image.LANCZOS)


# ----------------------------------------------------------------------------
# CURP
# ----------------------------------------------------------------------------
ESTADOS_CURP = {
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG", "GT", "GR",
    "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC", "PL", "QT", "QR", "SP",
    "SL", "SR", "TC", "TS", "TL", "VZ", "YN", "ZS", "NE",
}
A_DIGITO = str.maketrans("OQDIL|SZBGT", "00011152867")
A_LETRA = str.maketrans("0158267", "OISBZGT")
DICCIONARIO_CURP = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
NO_ENCONTRADA = "NO ENCONTRADA"
NO_ENCONTRADO = "NO ENCONTRADO"


def digito_verificador(curp17):
    suma = sum(DICCIONARIO_CURP.index(c) * (18 - i) for i, c in enumerate(curp17))
    return str((10 - suma % 10) % 10)


def curp_valida(c):
    """Formato correcto (no garantiza que el digito verificador cuadre)."""
    if not re.fullmatch(r"[A-Z]{4}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d", c or ""):
        return False
    mes, dia = int(c[6:8]), int(c[8:10])
    return 1 <= mes <= 12 and 1 <= dia <= 31 and c[11:13] in ESTADOS_CURP


def curp_verificada(curp):
    return curp_valida(curp) and digito_verificador(curp[:17]) == curp[17]


def corregir_curp(c):
    # Corrige confusiones tipicas del OCR (O/0, I/1, S/5...) segun la posicion
    letras1 = c[0:4].translate(A_LETRA)
    fecha = c[4:10].translate(A_DIGITO)
    sexo = c[10]
    estado = c[11:13].translate(A_LETRA)
    consonantes = c[13:16].translate(A_LETRA)
    homoclave = c[16].replace("O", "0")  # la homoclave nunca usa la letra O
    verificador = c[17].translate(A_DIGITO)
    return letras1 + fecha + sexo + estado + consonantes + homoclave + verificador


def extraer_curp(texto):
    texto = texto.upper()
    candidatos = re.findall(r"(?<![A-Z0-9])[A-Z0-9|]{18}(?![A-Z0-9])", texto)
    # A veces el OCR mete un espacio en medio de la CURP
    candidatos += re.findall(r"[A-Z0-9]{4}\s?[A-Z0-9]{6}\s?[A-Z0-9]{8}", texto)

    validas = []
    for cand in candidatos:
        cand = re.sub(r"\s", "", cand)
        if len(cand) != 18:
            continue
        curp = corregir_curp(cand)
        if not curp_valida(curp):
            continue
        # La homoclave puede ser letra o digito: si no cuadra el verificador,
        # probar la confusion tipica (I<->1, S<->5...)
        if not curp_verificada(curp):
            alternativa = curp[16].translate(A_DIGITO) if curp[16].isalpha() else curp[16].translate(A_LETRA)
            curp_alt = curp[:16] + alternativa + curp[17]
            if curp_verificada(curp_alt):
                curp = curp_alt
        if curp not in validas:
            validas.append(curp)

    for curp in validas:
        if curp_verificada(curp):
            return curp
    return validas[0] if validas else NO_ENCONTRADA


# ----------------------------------------------------------------------------
# FECHA DE NACIMIENTO
# ----------------------------------------------------------------------------
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

PATRON_FECHA = re.compile(
    r"(\d{1,2})\s*[A-Z0-9]{1,3}\s+([A-ZÁÉÍÓÚ]{4,11})\s+[A-Z0-9]{1,3}\s+((?:19|20)\d{2})"
)
PATRON_FECHA_BARRAS = re.compile(
    r"(\d{1,2})\s*[/\-]\s*([A-ZÁÉÍÓÚ]{4,11}|\d{1,2})\s*[/\-]\s*((?:19|20)\d{2})"
)


def normalizar_fecha(dia, mes, anio):
    dia = int(dia)
    if mes.isdigit():
        mes = MESES[int(mes) - 1] if 1 <= int(mes) <= 12 else None
    else:
        mes = (difflib.get_close_matches(mes, MESES, n=1, cutoff=0.7) or [None])[0]
    if not mes or not 1 <= dia <= 31:
        return None
    return f"{dia:02d} DE {mes} DE {anio}"


def fechas_en(texto):
    encontradas = [
        (m.start(), normalizar_fecha(*m.groups()))
        for patron in (PATRON_FECHA, PATRON_FECHA_BARRAS)
        for m in patron.finditer(texto)
    ]
    return [f for _, f in sorted(encontradas) if f]


def fecha_desde_curp(curp):
    if not curp_valida(curp):
        return NO_ENCONTRADA
    aa, mm, dd = int(curp[4:6]), int(curp[6:8]), int(curp[8:10])
    # El caracter 17 es digito para nacidos antes del 2000 y letra despues
    anio = (2000 if curp[16].isalpha() else 1900) + aa
    return f"{dd:02d} DE {MESES[mm - 1]} DE {anio}"


def extraer_fecha(texto):
    texto = texto.upper()
    lineas = texto.splitlines()
    for m in re.finditer(r"FECHA\s*DE\s*NACIMIENTO", texto):
        fechas = fechas_en(texto[m.end():m.end() + 60])
        if fechas:
            return fechas[0]
    for i, linea in enumerate(lineas):
        if re.search(r"FECHA\s*DE\s*NACIMIENTO", linea) and i > 0:
            fechas = fechas_en(lineas[i - 1])
            if fechas:
                return fechas[0]
    return NO_ENCONTRADA


# ----------------------------------------------------------------------------
# NOMBRE
# ----------------------------------------------------------------------------
PALABRAS_ALTO = r"SEXO|FECHA|C\.?\s?R\.?\s?I\.?\s?P|CURP|EDAD|NACIONALIDAD|MEXICAN|PRESENTADO|LUGAR|HORA|DOMICILIO"
PATRON_ETIQUETA_NOMBRE = re.compile(
    r"N\s?[O0]\s?[MN]\s?[BP8]\s?R\s?E(?:\s+DEL\s+ALUMNO)?\s*[:;]\s*(.*)", re.IGNORECASE
)


def palabras_mayusculas(linea):
    # Solo palabras en MAYUSCULAS: el ruido del borde y la letra manuscrita
    # suelen salir con minusculas
    segmento = re.split(PALABRAS_ALTO, linea, flags=re.IGNORECASE)[0]
    palabras = [p for p in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", segmento)
                if p.isupper() and len(p) >= 2]
    while palabras and len(palabras[0]) <= 2:
        palabras.pop(0)
    while palabras and len(palabras[-1]) <= 2:
        palabras.pop()
    return palabras


def candidatos_nombre(texto):
    lineas = texto.splitlines()
    candidatos = []

    # "NOMBRE: ..." / "NOMBRE DEL ALUMNO: ..."
    for linea in lineas:
        m = PATRON_ETIQUETA_NOMBRE.search(linea)
        if m:
            palabras = palabras_mayusculas(m.group(1))
            if len(palabras) >= 2:
                candidatos.append(" ".join(palabras))

    for i, linea in enumerate(lineas):
        # Valor arriba de "Nombre(s) Primer Apellido" / "Nombre Completo"
        if i > 0 and re.search(r"APELLIDO|NOMBRE\s*COMPLETO", linea, re.IGNORECASE) \
                and not re.search(r"PADRE|MADRE", linea, re.IGNORECASE):
            palabras = palabras_mayusculas(lineas[i - 1])
            if len(palabras) >= 2:
                candidatos.append(" ".join(palabras))

        # "CERTIFICA QUE <NOMBRE>, con CURP" o el nombre en la siguiente linea
        m = re.search(r"CERTIFICA\s+QUE\W*(.*)", linea, re.IGNORECASE)
        if m:
            palabras = palabras_mayusculas(m.group(1).split(",")[0])
            if len(palabras) >= 2:
                candidatos.append(" ".join(palabras))
                continue
            for siguiente in lineas[i + 1:i + 3]:
                palabras = palabras_mayusculas(siguiente)
                if len(palabras) >= 2:
                    candidatos.append(" ".join(palabras))
                    break

        # Constancia CURP: nombre en la linea anterior a "PRESENTE"
        if i > 0 and re.match(r"\W*PRESENTE\b", linea.strip(), re.IGNORECASE):
            palabras = palabras_mayusculas(lineas[i - 1])
            if len(palabras) >= 2:
                candidatos.append(" ".join(palabras))

    return candidatos


def nombre_coincide_curp(nombre, curp):
    # CURP: [0]=inicial 1er apellido, [2]=inicial 2do apellido, [3]=inicial del nombre
    if not curp_valida(curp):
        return False
    palabras = nombre.replace("Ñ", "X").split()
    if len(palabras) < 3:
        return False
    iniciales = [p[0] for p in palabras]
    nombre_primero = (curp[3] in iniciales[:-2] and curp[0] in iniciales[1:]
                      and curp[2] in iniciales[2:])
    apellidos_primero = (iniciales[0] == curp[0] and curp[2] in iniciales[1:-1]
                         and curp[3] in iniciales[2:])
    return nombre_primero or apellidos_primero


# ----------------------------------------------------------------------------
# REGLAS DE TIPO (corrigen al modelo entre Final / Parcial / Equivalencia)
# ----------------------------------------------------------------------------
TIPOS_SIMILARES = {"Certificado Final", "Certificado Parcial", "Equivalencia"}


def ajustar_categoria(categoria, texto_primera_pagina):
    """El certificado final y el parcial usan la misma plantilla (solo cambia
    "ESTUDIOS COMPLETOS" / "INCOMPLETOS"), y la equivalencia trae anexado un
    certificado parcial. El modelo los confunde; la primera pagina lo aclara."""
    if categoria not in TIPOS_SIMILARES:
        return categoria
    t = re.sub(r"\s+", " ", texto_primera_pagina.upper())

    if re.search(r"PRE\s?DICTAM|DICTAMEN|EQUIVALENCIA DE ESTUDIOS|REVALIDACI", t):
        return "Equivalencia"
    if re.search(r"\bIN\s?COMPLET", t) or re.search(r"CERTIFICADO PARCIAL|PARCIAL DE ESTUDIOS", t):
        return "Certificado Parcial"
    if re.search(r"ESTUDIOS COMPLET|CERTIFICADO DE TERMINACI|TERMINACION DE ESTUDIOS", t):
        return "Certificado Final"
    return categoria


# ----------------------------------------------------------------------------
# MOTOR
# ----------------------------------------------------------------------------
CAMPOS_REQUERIDOS = {
    "Actas de nacimiento": ["nombre", "fecha"],
    "CURP": ["nombre", "curp"],
    "Certificado Final": ["nombre", "curp"],
    "Certificado Parcial": ["nombre", "curp"],
    "Certificados Secundaria": ["nombre", "curp"],
    "Equivalencia": ["nombre"],
}


class MotorOCR:
    """Carga el modelo una sola vez y procesa PDFs."""

    def __init__(self, ruta_modelo, ruta_vectorizador, tesseract, poppler):
        pytesseract.pytesseract.tesseract_cmd = tesseract
        # Tesseract incluido en la carpeta del programa: indicarle donde estan sus idiomas
        tessdata = os.path.join(os.path.dirname(tesseract), "tessdata")
        if os.path.isdir(tessdata):
            os.environ["TESSDATA_PREFIX"] = tessdata
        self.poppler = poppler
        self.modelo = joblib.load(ruta_modelo)
        self.vectorizador = joblib.load(ruta_vectorizador)
        self.pasadas_extra = [
            lambda p: pytesseract.image_to_string(p.convert("L"), lang="spa", config="--psm 4"),
            lambda p: pytesseract.image_to_string(preprocesar_fondo_rojo(p), lang="spa", config="--psm 6"),
            lambda p: pytesseract.image_to_string(preprocesar_fondo_rojo(p), lang="spa", config="--psm 4"),
            lambda p: pytesseract.image_to_string(escala_grises(p), lang="spa", config="--psm 4"),
            lambda p: pytesseract.image_to_string(escala_grises(p), lang="spa", config="--psm 6"),
        ]

    @property
    def categorias(self):
        return list(self.modelo.classes_)

    def convertir_pdf(self, pdf_path, dpi=300, ancho_max_pts=612):
        # Paginas enormes (ej. 1700x2338 pt) se bajan a tamano carta para no tardar minutos
        info = pdfinfo_from_path(pdf_path, poppler_path=self.poppler)
        ancho = float(info["Page size"].split()[0])
        if ancho > ancho_max_pts:
            dpi = int(dpi * ancho_max_pts / ancho)
        return convert_from_path(pdf_path, poppler_path=self.poppler, dpi=dpi)

    def clasificar(self, pdf_path):
        paginas = self.convertir_pdf(pdf_path)
        # Misma configuracion de OCR que en el entrenamiento (eng, psm 6)
        textos = [pytesseract.image_to_string(p, lang="eng", config="--psm 6") for p in paginas]
        texto = "\n".join(textos)
        vector = self.vectorizador.transform([limpiar_texto(texto)])
        categoria = ajustar_categoria(self.modelo.predict(vector)[0], textos[0])
        confianza = None
        if hasattr(self.modelo, "predict_proba"):
            confianza = float(max(self.modelo.predict_proba(vector)[0]))
        return categoria, confianza, texto, paginas

    @staticmethod
    def _resolver(textos):
        curps = [c for c in (extraer_curp(t) for t in textos) if c != NO_ENCONTRADA]
        curp = next((c for c in curps if curp_verificada(c)), curps[0] if curps else NO_ENCONTRADA)

        candidatos = [c for t in textos for c in candidatos_nombre(t)]
        nombre = next((c for c in candidatos if nombre_coincide_curp(c, curp)),
                      candidatos[0] if candidatos else NO_ENCONTRADO)

        fechas = [f for f in (extraer_fecha(t) for t in textos) if f != NO_ENCONTRADA]
        fecha = fechas[0] if fechas else fecha_desde_curp(curp)
        if curp_verificada(curp) and fecha != fecha_desde_curp(curp):
            fecha = fecha_desde_curp(curp)

        return {"curp": curp, "curp_verificada": curp_verificada(curp),
                "fecha": fecha, "nombre": nombre}

    @staticmethod
    def _completos(campos, num_pasadas, categoria):
        requeridos = CAMPOS_REQUERIDOS.get(categoria, ["nombre", "fecha", "curp"])
        if any(campos[c].startswith("NO ENCONTRAD") for c in requeridos):
            return False
        if campos["curp"] == NO_ENCONTRADA:
            return num_pasadas >= 3 or ("curp" not in requeridos and categoria != "Actas de nacimiento")
        return campos["curp_verificada"] and nombre_coincide_curp(campos["nombre"], campos["curp"])

    def extraer_datos(self, paginas, texto_base, categoria):
        textos = [texto_base]
        campos = self._resolver(textos)
        for pasada in self.pasadas_extra:
            if self._completos(campos, len(textos), categoria):
                break
            # Los datos vienen en la primera pagina
            textos.append(pasada(paginas[0]))
            campos = self._resolver(textos)
        return campos

    def procesar(self, pdf_path):
        categoria, confianza, texto, paginas = self.clasificar(pdf_path)
        datos = self.extraer_datos(paginas, texto, categoria)
        datos["categoria"] = categoria
        datos["confianza"] = confianza
        return datos
