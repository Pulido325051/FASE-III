"""Diagramas de arquitectura (sistema actual y sistema propuesto) para el analisis de escalabilidad. Salida: resultados/diagramas/*.png"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import os

SAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados", "diagramas")
os.makedirs(SAL, exist_ok=True)
AZUL, AZUL2, AZULC = "#1a5490", "#2f7bc8", "#dce9f7"
VERDE, VERDEC = "#2e8b57", "#d9f0d9"
AMA, AMAC = "#c98a00", "#fff0c2"
ROJO, ROJOC = "#b3261e", "#f7dcdc"
LILA, LILAC = "#6b46b8", "#e7e2f6"
GRIS, GRISC, TXT = "#5d6b7c", "#eef2f7", "#17212e"
plt.rcParams["font.family"] = "DejaVu Sans"


def caja(ax, x, y, w, h, titulo, lineas=(), fc=AZULC, ec=AZUL, tc=TXT, ts=10.5, ls=8.2, radio=0.02):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.004,rounding_size={radio}", fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h - 0.028, titulo, ha="center", va="top", fontsize=ts, fontweight="bold", color=tc)
    for i, l in enumerate(lineas):
        ax.text(x + w / 2, y + h - 0.075 - i * 0.04, l, ha="center", va="top", fontsize=ls, color=GRIS)


def flecha(ax, p, q, color=GRIS, estilo="-|>", lw=1.5, rad=0.0, texto=None, tpos=0.5, tdx=0, tdy=0.018, ts=7.8):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=estilo, mutation_scale=13, color=color, lw=lw,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if texto:
        mx = p[0] + (q[0] - p[0]) * tpos + tdx
        my = p[1] + (q[1] - p[1]) * tpos + tdy
        ax.text(mx, my, texto, ha="center", va="bottom", fontsize=ts, color=color, fontweight="bold",
                bbox=dict(fc="white", ec="none", pad=1.2, alpha=.9))



NARANJA, NARANJAC = "#d9730d", "#fde8d2"


def actual():
    fig, ax = plt.subplots(figsize=(11.5, 6.4)); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.text(0.5, 0.975, "SISTEMA ACTUAL — un solo equipo con Docker Compose", ha="center", va="top", fontsize=13.5, fontweight="bold", color=AZUL)
    caja(ax, 0.02, 0.60, 0.15, 0.24, "Usuarios", ["Administrador", "Operador", "Consultor", "(navegador)"], fc=GRISC, ec=GRIS)
    # host
    ax.add_patch(FancyBboxPatch((0.23, 0.12), 0.75, 0.74, boxstyle="round,pad=0.004,rounding_size=0.02", fc="#fafbfd", ec=GRIS, lw=1.6, ls="--"))
    ax.text(0.605, 0.845, "Un equipo (PC o VM): 12 CPU / 3,8 GiB para Docker · sin redundancia", ha="center", va="top", fontsize=9.5, color=GRIS, style="italic")
    caja(ax, 0.26, 0.45, 0.32, 0.33, "Contenedor API (FastAPI)", ["Poppler + Tesseract (OCR)", "TF-IDF + LinearSVC (6 clases)", "reglas CURP / nombre / fecha",
                                                              "semáforo: 2 lecturas a la vez", "roles y sesiones en memoria"], fc=AZULC, ec=AZUL)
    caja(ax, 0.63, 0.55, 0.30, 0.23, "Contenedor MySQL 8", ["alumnos y archivos", "datos de prueba"], fc=GRISC, ec=GRIS)
    caja(ax, 0.63, 0.37, 0.30, 0.14, "Disco local", ["expedientes/ (PDF)", "respaldos .sql y .zip a mano"], fc=AMAC, ec=AMA)
    caja(ax, 0.26, 0.14, 0.67, 0.19, "Monitoreo (opcional, mismo equipo)", ["Prometheus · Grafana · Alertmanager · MLflow · responder.py", "métricas, alertas y respuesta automática del servicio"],
         fc=VERDEC, ec=VERDE)
    flecha(ax, (0.17, 0.72), (0.26, 0.64), texto="HTTP :8000", tpos=0.5, tdy=0.02)
    flecha(ax, (0.58, 0.68), (0.63, 0.68)); flecha(ax, (0.58, 0.50), (0.63, 0.44))
    flecha(ax, (0.42, 0.45), (0.42, 0.33), color=VERDE, texto="/metrics")
    # limitaciones
    lim = ["Punto único de falla: si cae el equipo, cae todo", "Escala solo hacia arriba (más CPU); sin autoescalado",
           "Latencia 8 a 16 s por documento con pocas CPU", "PDF en disco local; respaldo manual", "Pago fijo de hardware aunque no haya carga"]
    ax.add_patch(FancyBboxPatch((0.02, -0.07), 0.96, 0.15, boxstyle="round,pad=0.003,rounding_size=0.01", fc=ROJOC, ec=ROJO, lw=1.2))
    ax.text(0.5, 0.062, "Limitaciones:  " + lim[0] + "   ·   " + lim[1], ha="center", va="center", fontsize=8, color=ROJO)
    ax.text(0.5, 0.020, lim[2] + "   ·   " + lim[3], ha="center", va="center", fontsize=8, color=ROJO)
    ax.text(0.5, -0.022, lim[4], ha="center", va="center", fontsize=8, color=ROJO)
    fig.savefig(os.path.join(SAL, "diagrama_actual.png"), dpi=200, bbox_inches="tight", facecolor="white"); plt.close(fig)


def propuesto():
    fig, ax = plt.subplots(figsize=(11.5, 7.4)); ax.set_xlim(0, 1); ax.set_ylim(0, 1.06); ax.axis("off")
    ax.text(0.5, 1.03, "SISTEMA PROPUESTO — Google Cloud Run + Cloud SQL con gobernanza integrada", ha="center", va="top", fontsize=13.5, fontweight="bold", color=AZUL)
    caja(ax, 0.01, 0.66, 0.12, 0.24, "Usuarios", ["Admin", "Operador", "Consultor"], fc=GRISC, ec=GRIS)
    caja(ax, 0.16, 0.66, 0.13, 0.24, "HTTPS", ["URL de Cloud Run", "TLS gestionado", "(Cloud Armor", "opcional)"], fc=GRISC, ec=GRIS)
    # nucleo
    ax.add_patch(FancyBboxPatch((0.32, 0.44), 0.40, 0.50, boxstyle="round,pad=0.004,rounding_size=0.02", fc="#f4f8fd", ec=AZUL2, lw=1.6, ls="--"))
    ax.text(0.52, 0.925, "Cómputo con autoescalado (horizontal)", ha="center", va="top", fontsize=9.2, color=AZUL, style="italic")
    caja(ax, 0.34, 0.60, 0.36, 0.28, "Cloud Run: servicio API", ["1 vCPU · 1 GiB · 1 lectura por instancia", "0 a 3 instancias (escala a cero)", "OMP_THREAD_LIMIT=1 (OCR de 1 hilo)",
                                                                "modelo cargado al arrancar (~8 s)"], fc=AZULC, ec=AZUL)
    caja(ax, 0.34, 0.46, 0.17, 0.11, "Cloud Tasks", ["cola de lotes"], fc=AZULC, ec=AZUL2, ts=9, ls=7.6)
    caja(ax, 0.53, 0.46, 0.17, 0.11, "Cloud Run job", ["lotes grandes"], fc=AZULC, ec=AZUL2, ts=9, ls=7.6)
    caja(ax, 0.75, 0.74, 0.24, 0.17, "Cloud SQL MySQL", ["db-f1-micro → g1-small", "respaldos automáticos"], fc=GRISC, ec=GRIS, ts=9.5)
    caja(ax, 0.75, 0.50, 0.24, 0.21, "Cloud Storage", ["PDF de expedientes", "versionado · ciclo de vida", "Standard → Nearline"], fc=AMAC, ec=AMA, ts=9.5)
    caja(ax, 0.75, 0.32, 0.24, 0.15, "Secret Manager", ["claves y roles fuera", "del código"], fc=GRISC, ec=GRIS, ts=9.5, ls=7.6)
    flecha(ax, (0.13, 0.78), (0.16, 0.78)); flecha(ax, (0.29, 0.78), (0.34, 0.78))
    flecha(ax, (0.70, 0.82), (0.75, 0.82)); flecha(ax, (0.70, 0.68), (0.75, 0.64)); flecha(ax, (0.70, 0.62), (0.75, 0.45))
    flecha(ax, (0.51, 0.60), (0.51, 0.57), lw=1.1)
    # observabilidad y respuesta
    caja(ax, 0.01, 0.185, 0.30, 0.235, "Observabilidad", ["Cloud Monitoring (métricas)", "Cloud Logging (logs JSON)", "mismas métricas expedientes_*", "MLflow: modelos y deriva"], fc=VERDEC, ec=VERDE, ts=9.5, ls=7.6)
    caja(ax, 0.33, 0.185, 0.30, 0.235, "Respuesta automatizada", ["alerta → Pub/Sub → Cloud Function", "reinicio · modo seguro · respaldo", "con guardas y escalamiento"], fc=VERDEC, ec=VERDE, ts=9.5, ls=7.6)
    caja(ax, 0.65, 0.185, 0.34, 0.14, "CI/CD", ["Artifact Registry + Cloud Build", "pruebas → despliegue por revisión"], fc=GRISC, ec=GRIS, ts=9.5, ls=7.6)
    flecha(ax, (0.40, 0.60), (0.20, 0.42), color=VERDE, texto="métricas y logs", tpos=0.55, tdx=-0.04)
    flecha(ax, (0.31, 0.30), (0.33, 0.30), color=VERDE)
    # gobierno
    ax.add_patch(FancyBboxPatch((0.01, 0.02), 0.98, 0.15, boxstyle="round,pad=0.003,rounding_size=0.012", fc=LILAC, ec=LILA, lw=1.5))
    ax.text(0.5, 0.157, "Capa de gobernanza responsable (transversal)", ha="center", va="top", fontsize=10, fontweight="bold", color=LILA)
    ax.text(0.5, 0.118, "IAM de mínimo privilegio y 3 roles  ·  Cloud Audit Logs (quién vio o guardó qué)  ·  revisión humana obligatoria (modo seguro)  ·  retención y borrado de datos",
            ha="center", va="top", fontsize=7.8, color=TXT)
    ax.text(0.5, 0.082, "Monitoreo de fairness por tipo de documento y calidad de escaneo  ·  tarjeta del modelo y registro de versiones  ·  presupuestos y alertas de costo (FinOps) con etiquetas",
            ha="center", va="top", fontsize=7.8, color=TXT)
    ax.text(0.5, 0.046, "Región fija en Norteamérica con cifrado en reposo y en tránsito  ·  aviso de privacidad y base legal (datos de menores de edad)", ha="center", va="top", fontsize=7.8, color=TXT)
    fig.savefig(os.path.join(SAL, "diagrama_propuesto.png"), dpi=200, bbox_inches="tight", facecolor="white"); plt.close(fig)


if __name__ == "__main__":
    actual(); propuesto(); print("diagramas listos")
