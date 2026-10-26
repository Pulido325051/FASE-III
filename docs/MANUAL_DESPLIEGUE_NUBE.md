# Manual de despliegue en la nube — Fase II

Sistema de Expedientes con IA (API en Docker). Este manual explica, paso a paso, cómo publicar el sistema en la nube.

> **Alcance y honestidad técnica.** El procedimiento está redactado a partir de la documentación oficial de cada plataforma.
> **No se ejecutó en una cuenta de nube real** en esta fase (requiere una cuenta con método de pago). Lo que **sí se probó**
> en esta computadora es que la imagen cumple lo que esas plataformas exigen: arranca con el puerto de la variable `PORT`,
> responde al chequeo de salud, funciona sin base de datos y corre sin privilegios de administrador (ver sección 3.4).

## 1. Qué se va a desplegar

El proyecto tiene dos piezas:

| Pieza | Qué es | ¿Qué necesita en la nube? |
|---|---|---|
| **API** (`Dockerfile`) | La interfaz web y el servicio que clasifica y lee documentos | Un servicio que ejecute contenedores |
| **Base de datos** (MySQL) | Alumnos y registro de documentos | MySQL gestionado, o un contenedor en una máquina virtual |

Además, los PDFs guardados necesitan un **almacenamiento que no se borre** al reiniciar.

Los datos que trae el proyecto son **inventados**. **Nunca** se debe conectar un despliegue público a la base de datos real de Control Escolar.

## 2. Requerimientos técnicos

### 2.1 Del servicio (medidos en las pruebas)

| Concepto | Valor | Nota |
|---|---|---|
| Imagen Docker | 867 MB | Python 3.11-slim, Tesseract 5.5 (español e inglés), Poppler y el modelo |
| CPU | 1 a 2 vCPU | El OCR usa mucho procesador |
| Memoria | 2 GiB mínimo | El modelo y el OCR se cargan en memoria |
| Tiempo por documento | 3 a 9 s en las pruebas locales; hasta 40 s con escaneos grandes | Configurar un tiempo de espera de al menos 120 s |
| Puerto | El que indique la variable `PORT` (por omisión 8000) | La imagen ya lo respeta |
| Chequeo de salud | `GET /salud` | La imagen incluye `HEALTHCHECK` |
| Usuario del contenedor | `clasificador` (sin privilegios) | Buena práctica de seguridad |
| Tamaño máximo de PDF | 15 MB (`MAX_MB`) | Dentro del límite de peticiones de las plataformas (32 MiB en Cloud Run) |

### 2.2 Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `PORT` | La pone la plataforma | Puerto en el que escucha el servicio |
| `DB_HOST` | No | Servidor MySQL. **Si se omite, el servicio funciona solo como clasificador** (sin alumnos ni expedientes) |
| `DB_PORT`, `DB_NAME` | Con `DB_HOST` | Puerto (3306) y nombre de la base (`controlescolar_prueba`) |
| `DB_USER`, `DB_PASSWORD` | Con `DB_HOST` | Credenciales. En la nube se guardan como **secretos**, no en archivos |
| `ARCHIVOS_DIR` | No | Carpeta donde se guardan los PDFs (por omisión `/data/expedientes/archivos`) |
| `MAX_MB`, `MAX_CONCURRENCIA` | No | Límite de tamaño (15) y documentos leídos a la vez (2) |

### 2.3 Del equipo desde el que se despliega

- Docker Desktop (Windows o Mac) o Docker Engine (Linux), para probar la imagen antes de subirla.
- La herramienta de línea de comandos de la nube elegida (`gcloud` o `az`).
- Una cuenta en la plataforma con facturación activada y un proyecto o grupo de recursos creado.
- El código del proyecto (clon del repositorio o el ZIP extraído).

## 3. Estrategia de despliegue

### 3.1 Opciones comparadas

| Opción | Cómo es | Ventajas | Desventajas | Úsala cuando |
|---|---|---|---|---|
| **A. Contenedor sin servidores** (Google Cloud Run, Azure Container Apps) | Subes la imagen y la plataforma la ejecuta y la escala | Muy simple; paga solo cuando se usa; HTTPS incluido | El disco es temporal (los PDFs no se conservan sin configuración extra); la base de datos es aparte | Quieres una **demostración del clasificador** |
| **B. PaaS desde imagen o Git** (Render, Railway, Azure App Service) | Conectas el repositorio y construye solo | Aún más simple | Menos control; algunos planes gratuitos se duermen y tienen poca memoria para el OCR | Pruebas rápidas |
| **C. Máquina virtual con Docker Compose** (Compute Engine, EC2, Azure VM, DigitalOcean) | La misma `docker-compose.yml` de este proyecto en un servidor | **Sistema completo** (API + MySQL + PDFs en disco persistente) con cambios mínimos | Hay que administrar el servidor (actualizaciones, firewall, respaldos) | Quieres **todo funcionando**, incluida la base de datos |
| **D. Kubernetes** | Orquestador de contenedores | Escala grande | Complejo y costoso para este tamaño | No es necesario en esta fase |

### 3.2 Estrategia recomendada

- **Para presentar el proyecto en línea** con la base de datos y los expedientes: **Opción C** (máquina virtual con `docker compose`). Es la que mantiene todo igual que en la computadora local.
- **Para una demostración pública solo del clasificador** (sin datos): **Opción A** con Cloud Run, sin `DB_HOST`.

### 3.3 Arquitectura de cada opción

```
Opción A (solo clasificador)             Opción C (sistema completo)
Internet ── HTTPS ──> Cloud Run          Internet ── HTTPS ──> Proxy (Caddy) ──> VM
                      contenedor "api"                                          ├─ contenedor api
                      (sin base de datos)                                       ├─ contenedor db (MySQL)
                                                                                └─ disco: expedientes/ y datos de MySQL
```

### 3.4 Prueba de compatibilidad realizada (local)

Se ejecutó la imagen simulando lo que hace una plataforma en la nube: puerto asignado por variable y **sin** base de datos.

```bash
docker run -d --name prueba-nube -p 8050:8080 -e PORT=8080 clasificador-documentos:fase2
```

| Comprobación | Resultado |
|---|---|
| Estado del contenedor | `healthy` |
| `GET /salud` | `estado: ok`, `modelo_cargado: true`, `base_datos: desactivada` |
| `POST /clasificar` con el acta de ejemplo | Clasifica «Actas de nacimiento», lee la CURP, 2.8 s |
| Página principal | HTTP 200 |
| `GET /alumnos?q=...` sin base de datos | 503 con el mensaje «Este despliegue no tiene base de datos configurada (DB_HOST)» |
| Registro del servicio | `Sin base de datos (DB_HOST vacio): solo clasificacion` y `Uvicorn running on http://0.0.0.0:8080` |

## 4. Opción A — Google Cloud Run (solo clasificador)

### Paso 1. Preparar la cuenta

1. Crea una cuenta en <https://cloud.google.com/> y activa la facturación.
2. Crea un proyecto y anota su identificador (por ejemplo `fase2-expedientes`).
3. Instala la herramienta `gcloud`: <https://cloud.google.com/sdk/docs/install>

### Paso 2. Iniciar sesión y elegir el proyecto

```bash
gcloud auth login
gcloud config set project fase2-expedientes
```

### Paso 3. Activar los servicios necesarios

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### Paso 4. Desplegar

Desde la carpeta del proyecto (donde está el `Dockerfile`):

```bash
gcloud run deploy clasificador-documentos \
  --source . \
  --region us-central1 \
  --memory 2Gi --cpu 2 \
  --timeout 120 \
  --concurrency 4 \
  --max-instances 2 \
  --allow-unauthenticated
```

- `--source .` construye la imagen con el `Dockerfile` usando Cloud Build y la publica. La primera vez pregunta si crear un repositorio de imágenes: responde **Y**.
- `--max-instances 2` limita el gasto.
- `--allow-unauthenticated` hace público el servicio. **Úsalo solo con datos ficticios**: la aplicación todavía no tiene contraseña de acceso.

### Paso 5. Verificar

Al terminar, la herramienta muestra la dirección del servicio (`https://clasificador-documentos-xxxx.run.app`).

```bash
curl https://clasificador-documentos-xxxx.run.app/salud
```

Debe responder `"estado":"ok"` y `"base_datos":"desactivada"`. Abre la dirección en el navegador: la pantalla indica «Sin base de datos: solo clasificación».

### Paso 6. Actualizar, volver atrás y apagar

```bash
# Actualizar: vuelve a ejecutar el comando del paso 4
# Ver versiones y volver a una anterior:
gcloud run revisions list --service clasificador-documentos --region us-central1
gcloud run services update-traffic clasificador-documentos --region us-central1 --to-revisions=NOMBRE_DE_REVISION=100
# Eliminar el servicio para no generar costos:
gcloud run services delete clasificador-documentos --region us-central1
```

### Alternativa equivalente: Azure Container Apps

```bash
az login
az containerapp up --name clasificador-documentos --resource-group rg-clasificador \
  --location eastus --source . --ingress external --target-port 8000
```

## 5. Opción C — Máquina virtual con Docker Compose (sistema completo)

### Paso 1. Crear la máquina virtual

- Sistema: Ubuntu Server 22.04 o 24.04.
- Tamaño recomendado: 2 vCPU, 4 GB de RAM, 30 GB de disco.
- Reglas de red (firewall): permitir **22** (SSH) y **80/443** (web). **No abrir el puerto 3307**: es la base de datos y no debe estar en internet.

### Paso 2. Instalar Docker en la máquina

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# cierra la sesión SSH y vuelve a entrar
docker compose version
```

### Paso 3. Llevar el proyecto a la máquina

```bash
git clone https://github.com/Pulido325051/FASE-II.git
cd FASE-II
```

Si el repositorio es privado, usa un token de acceso personal de GitHub como contraseña, o copia el ZIP con `scp` y descomprímelo (`unzip FASE-II.zip`).

### Paso 4. Configurar contraseñas y puerto

```bash
cp .env.example .env
nano .env
```

Cambia `DB_ROOT_PASSWORD` y `DB_PASSWORD` por contraseñas largas y únicas. Para una prueba rápida **sin HTTPS** pon `API_PUERTO=80`; si vas a usar HTTPS (paso 7), deja `API_PUERTO=8000`.

### Paso 5. Encender

```bash
docker compose up --build -d
docker compose ps        # api y db deben decir "healthy"
curl http://localhost:8000/salud     # (o http://localhost/salud si pusiste API_PUERTO=80)
```

La primera vez tarda de 5 a 15 minutos (descarga e instalación de la imagen).

### Paso 6. Probar desde internet

Abre `http://IP_DE_LA_MAQUINA/` (con `API_PUERTO=80`) en el navegador. Debe mostrar la pantalla «Expedientes - Control Escolar» conectada a la base de datos de prueba.

### Paso 7. HTTPS (recomendado)

Con un dominio apuntando a la máquina, instala un proxy inverso como Caddy, que obtiene el certificado solo. La API se queda en el puerto 8000 (no la expongas en el firewall) y Caddy atiende el 80 y el 443:

```
# Caddyfile
mi-dominio.com {
    reverse_proxy localhost:8000
}
```

### Paso 8. Respaldos manuales (mientras no exista el botón de respaldo)

```bash
# Base de datos
docker compose exec -T db sh -c 'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" controlescolar_prueba' > respaldo.sql
# Archivos de los alumnos
tar czf expedientes.tgz expedientes/
```

### Paso 9. Actualizar y apagar

```bash
git pull && docker compose up --build -d     # actualizar
docker compose down                          # apagar (conserva datos)
docker compose down -v                       # apagar y BORRAR la base de datos
```

## 6. Si se usa una base de datos gestionada (Cloud SQL, Azure Database for MySQL)

1. Crea una instancia MySQL 8.
2. Carga `db/init/01_esquema.sql` y `db/init/02_datos.sql` con la herramienta de importación de la plataforma.
3. Pasa los datos de conexión al servicio como variables y secretos (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).
4. Permite la conexión solo desde el servicio (red privada o direcciones autorizadas), nunca desde cualquier dirección.
5. Los PDFs guardados necesitan un volumen persistente (en Cloud Run, un volumen de Cloud Storage; en una máquina virtual, el disco).

Ejemplo en Cloud Run, con la contraseña como secreto:

```bash
gcloud run services update clasificador-documentos --region us-central1 \
  --set-env-vars DB_HOST=IP_PRIVADA,DB_PORT=3306,DB_NAME=controlescolar_prueba,DB_USER=clasificador \
  --set-secrets DB_PASSWORD=db-password:latest
```

## 7. Seguridad antes de publicar

| Aspecto | Acción |
|---|---|
| Datos | Usar **solo datos ficticios** en un despliegue público |
| Acceso | La aplicación **aún no tiene contraseña de acceso** (pendiente para la Fase III): no publicarla con datos reales |
| Secretos | Contraseñas en el gestor de secretos de la nube, no en el código ni en el repositorio |
| Red | No exponer el puerto de MySQL; limitar el acceso a la base |
| HTTPS | Activo en Cloud Run y Azure por omisión; en una máquina virtual, con Caddy |
| Costos | Limitar instancias máximas, poner alertas de presupuesto y borrar lo que no se use |

## 8. Solución de problemas

| Problema | Causa probable | Solución |
|---|---|---|
| El servicio no arranca y el registro dice que no escucha | La plataforma pone el puerto en `PORT` | La imagen ya lo respeta; revisa que no se haya forzado otro puerto |
| Error `502/504` al leer un documento | Tiempo de espera o memoria insuficientes | Subir el tiempo de espera a 120 s y la memoria a 2 GiB o más |
| La pantalla dice «Sin base de datos» | No se definió `DB_HOST` | Es lo esperado en la Opción A; en la C revisa el `.env` y `docker compose logs db` |
| Los PDFs guardados desaparecen | Disco temporal del servicio | Usar volumen persistente (Cloud Storage) o la Opción C |
| No conecta a la base de datos gestionada | Red o credenciales | Revisar las direcciones autorizadas y los secretos; ver `docker compose logs api` |

## 9. Uso de herramientas de documentación

Para elaborar y mantener la documentación de este proyecto se usaron estas herramientas:

| Herramienta | Para qué se usó |
|---|---|
| **Claude Code (Anthropic)**, asistente de IA | Apoyo en la redacción del `README`, de este manual y del documento de validación, y en la generación de pruebas y código. Todo se revisó y se probó ejecutándolo |
| **Swagger UI / OpenAPI** (generada por FastAPI en `/docs`) | Documentación interactiva de la API que se mantiene sola con el código |
| **pytest** (`-v`) | Reporte legible de las pruebas automáticas |
| **Markdown en GitHub** (`README.md`, `docs/`) | Documentación versionada junto al código |
| **GitHub Copilot** (alternativa equivalente) | Servicio similar de asistencia por IA que también puede usarse para documentar y comentar código |

La IA se usó como **apoyo**: las instrucciones y resultados de este manual que se pudieron comprobar localmente se ejecutaron y están registrados en el documento de validación.
