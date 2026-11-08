"""Generador de trafico para las simulaciones de monitoreo (usa SOLO los 2 PDF ficticios de ejemplos/).

  python generar_trafico.py normal 40            documentos limpios (variaciones minimas)
  python generar_trafico.py degradado 25         escaneos de mala calidad (borrosos, bajo contraste, reducidos)
  python generar_trafico.py fuera 15             documentos de otro tipo (no son del dominio)
  python generar_trafico.py lento 6 --retardo 20 inyecta 20 s en el OCR y manda 6 documentos
  python generar_trafico.py corregir 8           simula que la persona cambia la categoria propuesta
  python generar_trafico.py bd_caida 30          peticiones a /alumnos con la BD detenida (respuestas 503)
  python generar_trafico.py reposo 30            sin carga (solo salud)
"""
import argparse
import io
import os
import random
import subprocess
import sys
import tempfile
import time

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

BASE = os.getenv("API", "http://localhost:8200")
EJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ejemplos")
POPPLER = os.getenv("POPPLER", "")      # carpeta de Poppler en Windows; vacio = usa pdftoppm del PATH
random.seed(7)


def paginas(nombre):
    with tempfile.TemporaryDirectory() as d:
        exe = os.path.join(POPPLER, "pdftoppm.exe") if POPPLER else "pdftoppm"
        subprocess.run([exe, "-r", "150", "-png", os.path.join(EJ, nombre), os.path.join(d, "p")],
                       check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return [Image.open(os.path.join(d, f)).convert("RGB").copy() for f in sorted(os.listdir(d))]


def a_pdf(img):
    b = io.BytesIO()
    img.save(b, "PDF", resolution=150)
    return b.getvalue()


def normal(img):
    return ImageEnhance.Brightness(img).enhance(random.uniform(0.97, 1.03))


def degradado(img):
    w, h = img.size
    f = random.uniform(0.22, 0.32)
    im = img.resize((int(w * f), int(h * f))).resize((w, h))
    im = im.filter(ImageFilter.GaussianBlur(random.uniform(1.8, 3.2)))
    im = ImageEnhance.Contrast(im).enhance(random.uniform(0.35, 0.55))
    return im.rotate(random.uniform(-4, 4), fillcolor="white")


def fuera(img):
    im = Image.new("RGB", img.size, "white")
    d = ImageDraw.Draw(im)
    for i in range(random.randint(6, 12)):
        d.text((60, 80 + i * 70), "OFERTA ESPECIAL " + "XQZ " * random.randint(2, 6) + str(random.randint(100, 999)), fill="black")
    return im


def sesion():
    s = requests.Session()
    r = s.post(BASE + "/api/login", json={"usuario": "administrador", "clave": "admin-2026"}, timeout=20)
    r.raise_for_status()
    return s


def enviar(s, pdf, nombre="doc.pdf"):
    t = time.time()
    r = s.post(BASE + "/clasificar", files={"archivo": (nombre, pdf, "application/pdf")}, data={"guardar": "false"}, timeout=180)
    return r, time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("escenario")
    ap.add_argument("n", type=int, nargs="?", default=10)
    ap.add_argument("--retardo", type=float, default=20)
    ap.add_argument("--pausa", type=float, default=0.8)
    a = ap.parse_args()
    s = sesion()
    if a.escenario == "reposo":
        for _ in range(a.n):
            s.get(BASE + "/salud", timeout=10)
            time.sleep(1)
        return
    if a.escenario == "bd_caida":
        for _ in range(a.n):
            r = s.get(BASE + "/alumnos", params={"q": "MARIA"}, timeout=30)
            print(r.status_code, end=" ", flush=True)
            time.sleep(0.5)
        print()
        return
    base_imgs = [paginas("acta_nacimiento_ficticia.pdf")[0], paginas("constancia_curp_ficticia.pdf")[0]]
    if a.escenario == "lento":
        s.post(BASE + "/admin/fallas", json={"retardo_ocr_s": a.retardo}, timeout=10)
    try:
        for i in range(a.n):
            # carga de demo: 5 de cada 6 documentos son el acta ficticia y 1 la constancia de CURP ficticia
            img = base_imgs[1 if i % 6 == 5 else 0]
            if a.escenario == "normal":
                img = normal(img)
            elif a.escenario == "degradado":
                img = degradado(img)
            elif a.escenario == "fuera":
                img = fuera(img)
            elif a.escenario == "corregir":
                img = normal(img)
            r, seg = enviar(s, a_pdf(img))
            info = r.json() if r.ok else {}
            print(f"{i + 1:>3}/{a.n} {r.status_code} {seg:5.1f}s {info.get('tipo_documento', '-'):<22} margen={info.get('margen')}", flush=True)
            if a.escenario == "corregir" and r.ok:
                otra = "Equivalencia" if info.get("tipo_documento") != "Equivalencia" else "CURP"
                s.post(BASE + "/feedback/categoria", json={"de": info["tipo_documento"], "a": otra}, timeout=10)
            time.sleep(a.pausa)
    finally:
        if a.escenario == "lento":
            s.post(BASE + "/admin/fallas", json={"retardo_ocr_s": 0}, timeout=10)


if __name__ == "__main__":
    sys.exit(main())
