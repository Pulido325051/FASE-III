# Imagen unica de las herramientas de monitoreo: servidor MLflow, monitor de deriva y receptor de alertas
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install mlflow==2.16.2 scikit-learn==1.9.1 numpy==2.3.5 scipy==1.17.1 joblib==1.6.0 pandas prometheus-client==0.26.0 matplotlib requests "sqlalchemy<2.1"
WORKDIR /monitoreo
COPY *.py ./
