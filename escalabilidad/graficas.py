"""Genera las graficas del anexo (throughput, latencia, vertical frente a horizontal y fairness) a partir de los resultados de
escalabilidad/resultados/. La grafica de fairness solo se hace si existe fairness.json.   Salida: resultados/graficas/*.png"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(AQUI, "resultados")
SAL = os.path.join(RES, "graficas")
os.makedirs(SAL, exist_ok=True)
AZUL, GRIS, VERDE, ROJO = "#1a5490", "#5d6b7c", "#2e8b57", "#b3261e"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

EXP = {r["experimento"]: r for r in json.load(open(os.path.join(RES, "mediciones_rendimiento.json"), encoding="utf-8"))["experimentos"]}
g = EXP.__getitem__

# 1. throughput segun CPU, con y sin OMP_THREAD_LIMIT=1
cpus = [1, 2, 4]
sin = [g(f"B. Vertical: {c} CPU, 2 lecturas")["docs_por_min"] for c in cpus]
con = [g("E. OMP_THREAD_LIMIT=1: 1 CPU, 1 lectura")["docs_por_min"], g("E. OMP_THREAD_LIMIT=1: 2 CPU, 2 lecturas")["docs_por_min"],
       g("E. OMP_THREAD_LIMIT=1: 4 CPU, 4 lecturas")["docs_por_min"]]
fig, ax = plt.subplots(figsize=(6.4, 3.6))
ax.plot(cpus, sin, "o-", color=GRIS, lw=2.2, label="Configuración actual (Tesseract con todos los hilos)")
ax.plot(cpus, con, "o-", color=AZUL, lw=2.4, label="Optimizada (OMP_THREAD_LIMIT=1)")
for x, y in zip(cpus, sin):
    ax.annotate(f"{y:g}", (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color=GRIS)
for x, y in zip(cpus, con):
    ax.annotate(f"{y:g}", (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color=AZUL, fontweight="bold")
ax.set_xticks(cpus); ax.set_xlabel("CPU asignadas al contenedor"); ax.set_ylabel("Documentos por minuto"); ax.set_ylim(0, 150)
ax.set_title("Throughput según CPU (escalado vertical)", fontsize=11, loc="left"); ax.legend(frameon=False, fontsize=8.5, loc="upper left")
fig.tight_layout(); fig.savefig(os.path.join(SAL, "g_throughput.png"), dpi=200); plt.close(fig)

# 2. latencia p50 / p95
claves = [("A. Base: 1 CPU, 1 lectura a la vez", "1 CPU\nactual"), ("E. OMP_THREAD_LIMIT=1: 1 CPU, 1 lectura", "1 CPU\noptimizada"),
          ("B. Vertical: 4 CPU, 2 lecturas", "4 CPU\nactual"), ("E. OMP_THREAD_LIMIT=1: 4 CPU, 2 lecturas", "4 CPU\noptimizada")]
p50, p95 = [g(c)["lat_p50"] for c, _ in claves], [g(c)["lat_p95"] for c, _ in claves]
colores = [GRIS, AZUL, GRIS, AZUL]
fig, ax = plt.subplots(figsize=(6.4, 3.4))
ax.bar([i - 0.2 for i in range(4)], p50, 0.4, color=colores)
ax.bar([i + 0.2 for i in range(4)], p95, 0.4, color=colores, alpha=0.5, hatch="//", edgecolor="white")
for i, (a, b) in enumerate(zip(p50, p95)):
    ax.text(i - 0.2, a + 0.4, f"{a:g}", ha="center", fontsize=8.5); ax.text(i + 0.2, b + 0.4, f"{b:g}", ha="center", fontsize=8.5)
ax.axhline(45, color=ROJO, lw=1.2, ls="--"); ax.text(3.45, 46, "SLO: 45 s", color=ROJO, fontsize=8.5, ha="right")
ax.set_xticks(range(4)); ax.set_xticklabels([n for _, n in claves], fontsize=8.5); ax.set_ylabel("Segundos por documento"); ax.set_ylim(0, 52)
ax.set_title("Latencia por documento (barra sólida p50, rayada p95)", fontsize=11, loc="left")
fig.tight_layout(); fig.savefig(os.path.join(SAL, "g_latencia.png"), dpi=200); plt.close(fig)

# 3. vertical frente a horizontal con la misma CPU total
val = [g("B. Vertical: 2 CPU, 2 lecturas")["docs_por_min"], g("D. Horizontal: 2 contenedores x 1 CPU")["docs_por_min"],
       g("B. Vertical: 4 CPU, 2 lecturas")["docs_por_min"], g("D. Horizontal: 4 contenedores x 1 CPU")["docs_por_min"]]
fig, ax = plt.subplots(figsize=(6.4, 3.3))
ax.bar(range(4), val, color=[AZUL, VERDE, AZUL, VERDE], width=0.55)
for i, v in enumerate(val):
    ax.text(i, v + 0.3, f"{v:g}", ha="center", fontsize=9)
ax.set_xticks(range(4)); ax.set_xticklabels(["2 CPU\n1 contenedor", "2 CPU\n2 contenedores", "4 CPU\n1 contenedor", "4 CPU\n4 contenedores"], fontsize=8.5)
ax.set_ylabel("Documentos por minuto"); ax.set_ylim(0, 18)
ax.set_title("Vertical (azul) frente a horizontal (verde), misma CPU total", fontsize=11, loc="left")
fig.tight_layout(); fig.savefig(os.path.join(SAL, "g_horizontal.png"), dpi=200); plt.close(fig)

# 4. fairness (opcional)
ruta_f = os.path.join(RES, "fairness.json")
if os.path.exists(ruta_f):
    F = json.load(open(ruta_f, encoding="utf-8"))
    fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.5), gridspec_kw={"width_ratios": [1.25, 1]})
    c = F["por_clase"]
    nom, f1 = list(c.keys()), [v["f1"] * 100 for v in c.values()]
    axs[0].barh([n.replace("Certificados ", "Cert. ").replace("Certificado ", "Cert. ") for n in nom], f1, color=[ROJO if v == min(f1) else AZUL for v in f1])
    for i, v in enumerate(f1):
        axs[0].text(v + 0.15, i, f"{v:.1f}", va="center", fontsize=8.5)
    axs[0].set_xlim(90, 101); axs[0].invert_yaxis(); axs[0].set_xlabel("F1 (%)"); axs[0].set_title("Por tipo de documento", fontsize=10.5, loc="left")
    q = F["por_calidad_cobertura"]["grupos"]
    etq = ["baja", "media", "alta"]
    ac, bc = [q[k]["exactitud"] * 100 for k in etq], [q[k]["baja_confianza"] * 100 for k in etq]
    axs[1].bar(range(3), ac, color=[ROJO, GRIS, AZUL], width=0.55)
    for i, v in enumerate(ac):
        axs[1].text(i, v + 0.15, f"{v:.1f} %", ha="center", fontsize=8.5)
    axs[1].set_ylim(94, 100.5); axs[1].set_xticks(range(3)); axs[1].set_xticklabels([f"{e}\n(baja conf. {b:.1f} %)" for e, b in zip(etq, bc)], fontsize=8)
    axs[1].set_ylabel("Exactitud (%)"); axs[1].set_title("Por cobertura del vocabulario", fontsize=10.5, loc="left")
    fig.tight_layout(); fig.savefig(os.path.join(SAL, "g_fairness.png"), dpi=200); plt.close(fig)
print("Graficas en", SAL)
