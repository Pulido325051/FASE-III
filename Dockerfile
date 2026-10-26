# ==========================================================================
# Clasificador de Documentos Escolares - API web
# Imagen: Python 3.11 + Tesseract OCR (espanol/ingles) + Poppler + modelo
# ==========================================================================
FROM python:3.11-slim

# Sin archivos .pyc y con salida inmediata de logs (para ver los logs en Docker/la nube)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# Dependencias del sistema: OCR (Tesseract con idiomas) y Poppler (PDF -> imagen)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Primero solo los requisitos: si el codigo cambia, Docker reutiliza esta capa
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

# Codigo, modelo entrenado, ejemplos ficticios y pruebas
COPY app ./app
COPY modelo ./modelo
COPY ejemplos ./ejemplos
COPY tests ./tests
COPY pytest.ini ./

# Usuario sin privilegios (buena practica de seguridad) y carpeta para los PDFs guardados
RUN useradd --create-home --uid 1000 clasificador \
 && mkdir -p /data/expedientes/archivos && chown -R clasificador:clasificador /data
USER clasificador

EXPOSE 8000

# Docker revisa cada 30 s que el servicio responda
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/salud', timeout=4)" || exit 1

# La nube (Cloud Run, Azure, Render...) indica el puerto con la variable PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
