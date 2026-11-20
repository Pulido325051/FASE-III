# Escalabilidad, costos y fairness (Actividad 9)

Scripts que sustentan el análisis de escalabilidad, optimización de costos y gobernanza del sistema. Todo es reproducible y usa solo
los PDF ficticios de `ejemplos/`; el dataset real de entrenamiento **no** se sube a GitHub.

| Archivo | Para qué sirve |
|---|---|
| `medir_rendimiento.py` | Mide latencia (p50 y p95), documentos por minuto y uso de CPU y memoria con 1, 2 y 4 CPU, con distinta concurrencia, con 1 a 4 contenedores (escalado vertical y horizontal) y con `OMP_THREAD_LIMIT=1` |
| `fairness.py` | Evalúa el modelo por tipo de documento, calidad del escaneo, sexo y entidad inferidos de la CURP legible; guarda **solo resultados agregados** |
| `graficas.py` | Genera las gráficas del anexo (throughput, latencia, vertical frente a horizontal y fairness) |
| `diagramas.py` | Dibuja el diagrama del sistema actual y del sistema propuesto (Cloud Run + Cloud SQL) |
| `resultados/` | Resultados de las mediciones (`mediciones_rendimiento.json`), gráficas y diagramas |

## Cómo reproducirlo

```bash
# 1. Encender la base de datos de prueba del monitoreo
docker compose -p fase3mon -f docker-compose.monitoreo.yml up -d --build

# 2. Rendimiento (prueba corta; sin --docs usa 24 documentos por experimento y toda la serie tarda unos 30 min)
pip install requests pillow
python escalabilidad/medir_rendimiento.py --serie omp --docs 6
python escalabilidad/medir_rendimiento.py --serie todo

# 3. Fairness (necesita el dataset de entrenamiento, que no está en el repositorio)
pip install scikit-learn pandas
python escalabilidad/fairness.py ruta/al/dataset.csv

# 4. Gráficas y diagramas
pip install matplotlib
python escalabilidad/graficas.py
python escalabilidad/diagramas.py
```

En Windows define antes `POPPLER` con la carpeta de Poppler (por ejemplo `set POPPLER=C:\poppler\Library\bin`).

## Qué se encontró (resumen)

- El OCR (Tesseract) crea un hilo por núcleo del equipo; en un contenedor con la CPU limitada esos hilos se estorban. Con
  `OMP_THREAD_LIMIT=1` el mismo código pasó de 3,7 a 40 documentos por minuto con 1 CPU, con resultados idénticos.
- Escalar vertical u horizontalmente rinde lo mismo con la misma CPU total; se propone horizontal (Cloud Run) por disponibilidad y pago por uso.
- Medido en contenedores con la CPU limitada, no en Cloud Run real: falta confirmarlo en un despliegue de prueba.
- Los resultados de fairness (`resultados/fairness.json`) se generan localmente y no se versionan.
