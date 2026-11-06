# Clasificador de Documentos Escolares — API en Docker

Servicio web que recibe un documento escolar escaneado en PDF y:

1. identifica el **tipo de documento** (acta de nacimiento, CURP, certificado de
   secundaria, certificado final, certificado parcial o equivalencia), con el modelo
   **TF-IDF + LinearSVC** entrenado en `02_Entrenamiento_Modelo.ipynb`;
2. extrae la **CURP** (validada con su dígito verificador), el **nombre** y la
   **fecha de nacimiento** con **OCR (Tesseract)**;
3. busca al **alumno** en la base de datos por su CURP y, opcionalmente, **guarda el
   documento en su expediente** (`<idAlumno>_<TIPO>.pdf` + registro en la tabla `archivos`).

Es el mismo motor que usa el *Sistema de Expedientes* de escritorio de Control
Escolar, empaquetado como API REST en contenedores Docker.

## Arquitectura

```
Navegador / cliente HTTP
        │  POST /clasificar (PDF)
        ▼
┌──────── contenedor "api" (python:3.11-slim) ────────┐       ┌──── contenedor "db" (mysql:8.0) ────┐
│  FastAPI + Uvicorn (app/main.py)                    │       │  controlescolar_prueba              │
│   1. PDF → imagen ............ Poppler               │       │   alumnos  (100 ficticios)          │
│   2. Imagen → texto .......... Tesseract OCR         │ SQL   │   archivos (278 ficticios)          │
│   3. Texto → tipo ............ TF-IDF + LinearSVC    │──────▶│                                     │
│   4. Texto → CURP/nombre/fecha  reglas + validación  │       └─────────────────────────────────────┘
│   5. CURP → alumno → expediente (opcional)           │
│  Volumen /data/expedientes: PDFs y 'eliminados'      │
└─────────────────────────────────────────────────────┘
```

La base de datos es **opcional**: sin las variables `DB_*` la API solo clasifica
(así se puede desplegar en la nube sin base de datos).

| Ruta | Método | Para qué |
|---|---|---|
| `/` | GET | Pantalla web (equivalente a la ventana de escritorio): lista por lotes, revisión, guardar y expedientes |
| `/clasificar` | POST | Clasifica un PDF (campo `archivo`; `guardar=true` para guardarlo en el expediente) |
| `/guardar` | POST | Guarda un PDF ya revisado: `modo` = `nuevo`, `reemplazar` (con `reemplazar_id`), `adicional` o `personalizado` (duplicado con `nombre`, que debe empezar con el id del alumno) |
| `/alumnos/{id}/curp` | POST | **Fase III.** Corrige la CURP del alumno en la BD: exige formato y dígito verificador válidos y que nadie más la tenga; queda en `registro_cambios_curp.csv` |
| `/respaldo/bd`, `/respaldo/archivos` | POST | **Fase III.** Respaldo en segundo plano de la base de datos (.sql, una lectura consistente) o de los PDF (.zip). Un solo respaldo a la vez |
| `/respaldo/estado`, `/respaldo/cancelar`, `/respaldo/descargar/{nombre}` | GET / POST | **Fase III.** Avance, cancelación y descarga (solo archivos `BD_*` y `Archivos_*` hechos por el sistema) |
| `/api/login`, `/api/logout`, `/api/sesion` | POST / GET | **Fase III.** Entrar con uno de los 3 usuarios (administrador, operador, consultor) con sesión por cookie. `/api/sesion` (pública) dice si hay que entrar, con qué usuarios y qué permisos tiene quien ya entró |
| `/alumnos?q=...` | GET | Busca alumnos por nombre, CURP o matrícula |
| `/alumnos/por-curp/{curp}` | GET | Alumno(s) con esa CURP (valida el formato) |
| `/alumnos/{id}/destino?categoria=...` | GET | Nombre con el que se guardaría el archivo y documentos que ya tiene de ese tipo |
| `/alumnos/{id}/expediente` | GET | Documentos del alumno (orden: CURP, secundaria, acta, demás) |
| `/alumnos/{id}/expediente/{doc}/pdf` | GET | Abre el PDF de un documento del expediente |
| `/alumnos/{id}/expediente/{doc}` | DELETE | Elimina el registro y mueve el PDF a la carpeta de eliminados (con bitácora) |
| `/tipos` | GET | Tipos de documento que maneja el sistema |
| `/salud` | GET | Estado del servicio y de la base de datos |
| `/docs` | GET | Documentación interactiva de la API (Swagger) |

Ejemplo de respuesta de `/clasificar` con base de datos:

```json
{
  "archivo": "constancia_curp_ficticia.pdf",
  "tipo_documento": "CURP",
  "curp": "EELM060312MCHJPRA0",
  "curp_verificada": true,
  "nombre": "MARIA FERNANDA EJEMPLO LOPEZ",
  "fecha_nacimiento": "12 DE MARZO DE 2006",
  "segundos": 13.3,
  "alumno": { "id": 1, "nombre_completo": "MARIA FERNANDA EJEMPLO LOPEZ", "curp": "EELM060312MCHJPRA0",
              "matricula": "210808025613", "generacion": "2021-2024", "escuela": "TELEBACHILLERATO COMUNITARIO 8662" },
  "encontrado_por": "curp",
  "documentos_del_mismo_tipo": [],
  "guardado_como": "1_CURP.pdf",
  "aviso": null
}
```

Reglas para guardar (las mismas del sistema de escritorio): solo se guarda
automáticamente si el alumno se encontró **por CURP con dígito verificador válido** y
**no tiene ya** un documento de ese tipo (reconociendo variantes como "ACT NAC" o
"CERT SEC"). En otro caso se informa en `aviso` y no se escribe nada.

## Estructura

```
docker_api/
├── app/
│   ├── main.py              API (FastAPI)
│   ├── motor_ocr.py         Clasificación + OCR + extracción   ┐ mismos módulos que el
│   ├── base_datos.py        Consultas a MySQL                  │ sistema de escritorio
│   ├── almacenamiento.py    Guardar PDF + registro             ┘
│   └── static/index.html    Página de prueba
├── modelo/                  modelo_clasificador.pkl y vectorizador.pkl
├── db/
│   ├── generar_base_prueba.py   Genera la base de prueba (datos ficticios)
│   └── init/                    01_esquema.sql, 02_datos.sql (MySQL los carga al iniciar)
├── ejemplos/                PDFs FICTICIOS para probar (y el script que los genera)
├── tests/                   test_api.py (8 pruebas) y test_bd.py (5 pruebas con base de datos)
├── Dockerfile
├── docker-compose.yml       api + db
├── .env.example             (opcional) Contraseñas y puertos personalizados (copiar como .env)
├── herramientas/            anonimizar_vectorizador.py (quita datos personales del modelo)
├── requirements.txt         Dependencias (versiones fijas)
└── requirements-dev.txt     + herramientas de prueba
```

## Base de datos de prueba (datos ficticios)

`db/init/` contiene la **misma estructura** que las tablas `alumnos` y `archivos`
de Control Escolar, con **datos 100 % ficticios**:

- **100 alumnos** con nombres comunes combinados al azar, CURP generada con la
  regla oficial (iniciales, fecha, sexo, estado y dígito verificador válido),
  matrícula, generación, escuela, correo `@ejemplo.com` y teléfono `614555xxxx`.
- **278 registros de archivos** (CURP, certificado de secundaria, acta, certificado
  final) con las variantes de captura reales ("ACT NAC", "CERT SEC", "CUPR"…).
- El alumno **id 1** es la alumna de los PDFs de ejemplo (*MARIA FERNANDA EJEMPLO
  LOPEZ*, CURP `EELM060312MCHJPRA0`) y empieza **sin documentos**, para la demostración.

No contiene datos reales de alumnos. Para regenerarla: `python db/generar_base_prueba.py`
y luego `docker compose down -v` + `docker compose up`.

## 1. Instalar Docker (Windows)

1. Abrir **PowerShell como administrador** y ejecutar `wsl --install`. Reiniciar.
2. Descargar e instalar **Docker Desktop**: https://www.docker.com/products/docker-desktop/
   (dejar marcada la opción *Use WSL 2*).
3. Abrir Docker Desktop y esperar a que diga *Engine running*.
4. Comprobar en una terminal: `docker --version` y `docker compose version`.

## 2. Ejecutar en local

Desde la carpeta `docker_api`:

```bash
docker compose up --build
```

La primera vez tarda unos minutos (descarga Python, Tesseract, MySQL y las
librerías; MySQL carga los datos de prueba). Cuando el log diga `Modelo listo`, abrir:

- http://localhost:8000 — página de prueba
- http://localhost:8000/docs — documentación interactiva

**Demostración de punta a punta:**
1. Marcar *Guardar en el expediente del alumno*.
2. Arrastrar `ejemplos/constancia_curp_ficticia.pdf` → se clasifica como **CURP**, se
   encuentra a la alumna **id 1** por CURP y se guarda como `1_CURP.pdf`.
3. Arrastrar el mismo PDF otra vez → **no se duplica** ("ya tiene un documento de este tipo").
4. Arrastrar `ejemplos/acta_nacimiento_ficticia.pdf` → se guarda como `1_ACTA DE NAC.pdf`.
5. En *Consultar expediente* buscar `EJEMPLO` → aparecen sus documentos en orden.

Para ver la base con DBeaver: host `localhost`, puerto **3307**, base
`controlescolar_prueba`, usuario y contraseña de prueba (por defecto `clasificador` / `prueba-2026`, o los de tu `.env`).

Para detener: `Ctrl + C` y `docker compose down`
(`docker compose down -v` borra también la base y los PDFs guardados, para empezar de cero).

## 3. Validar el funcionamiento

**a) Estado de los contenedores** (ambos deben decir `healthy`):

```bash
docker compose ps
```

**b) Pruebas automáticas dentro del contenedor** (38 pruebas):

```bash
docker compose run --rm api pytest -v
```

- `test_api.py` (8): estado, página y documentación; clasificación correcta de una
  constancia CURP y de un acta (CURP, nombre, fecha); rechazo de archivos que no son
  PDF, demasiado grandes o dañados.
- `test_bd.py` (5): conexión a la base; búsqueda de alumnos; expediente en orden
  CURP → secundaria → acta; clasificar **y guardar** en el expediente sin duplicar;
  clasificar sin guardar no escribe nada. Estas pruebas dejan la base como estaba.

**c) Prueba manual con curl:**

```bash
curl http://localhost:8000/salud
curl -F "archivo=@ejemplos/acta_nacimiento_ficticia.pdf" http://localhost:8000/clasificar
curl "http://localhost:8000/alumnos?q=EJEMPLO"
curl http://localhost:8000/alumnos/1/expediente
```

**d) Logs:** `docker compose logs -f api`

## 4. Desplegar en la nube

La imagen ya está preparada para la nube:

- escucha en el puerto que indique `PORT`;
- tiene `HEALTHCHECK`;
- corre con un usuario sin privilegios;
- se configura solo con variables de entorno.

Recursos recomendados: **2 GB de RAM y 1–2 vCPU** (el OCR usa mucho CPU).

**Base de datos en la nube:** si no se configuran las variables `DB_*`, el servicio
funciona solo como clasificador, que es suficiente para demostrar el modelo. Para
incluir la base de prueba, crear un MySQL administrado (Cloud SQL, Azure Database
for MySQL…), cargar `db/init/01_esquema.sql` y `02_datos.sql`, y pasar `DB_HOST`,
`DB_USER`, `DB_PASSWORD` y `DB_NAME` como variables de entorno o secretos del servicio.
**Nunca** conectar el despliegue público a la base real de Control Escolar.

### Opción A — Google Cloud Run

```bash
gcloud auth login
gcloud config set project MI-PROYECTO
gcloud run deploy clasificador-documentos \
    --source . \
    --region us-central1 \
    --memory 2Gi --cpu 2 --timeout 120 \
    --allow-unauthenticated
```

### Opción B — Azure Container Apps

```bash
az login
az containerapp up \
    --name clasificador-documentos \
    --resource-group rg-clasificador \
    --location eastus \
    --source . \
    --ingress external --target-port 8000
```

### Opción C — Subir la imagen a Docker Hub (sirve para cualquier nube)

```bash
docker login
docker tag clasificador-documentos:fase3 MI-USUARIO/clasificador-documentos:fase3
docker push MI-USUARIO/clasificador-documentos:fase3
```

## Configuración (variables de entorno)

| Variable | Por defecto | Descripción |
|---|---|---|
| `PORT` | `8000` | Puerto del servicio (la nube lo asigna) |
| `MAX_MB` | `15` | Tamaño máximo de PDF aceptado |
| `MAX_CONCURRENCIA` | `2` | Documentos procesados al mismo tiempo |
| `DB_HOST` | *(vacío = sin base)* | Servidor MySQL |
| `DB_PORT`, `DB_NAME` | `3306`, `controlescolar_prueba` | Puerto y nombre de la base |
| `DB_USER`, `DB_PASSWORD` | — | Credenciales (en local, desde `.env`) |
| `ARCHIVOS_DIR` | `/data/expedientes/archivos` | Carpeta donde se guardan los PDFs (la carpeta de *eliminados* queda al lado: `archivos_eliminados`) |
| `API_PUERTO`, `DB_PUERTO` | `8000`, `3307` | Puertos en tu computadora (en `.env`, solo si están ocupados) |
| `CLAVE_ADMINISTRADOR`, `CLAVE_OPERADOR`, `CLAVE_CONSULTOR` | *(vacías = sin login)* | **Fase III.** Contraseña de cada usuario fijo: texto tal cual o el hash `pbkdf2_sha256$...` de `config.ini` del programa de escritorio. `docker-compose.yml` trae contraseñas **de demostración**; cámbialas con datos reales. Si no se define ninguna, la web queda abierta |
| `HORAS_SESION` | `10` | Duración de la sesión si hay contraseña |
| `RESPALDOS_DIR` | *(vacío = sin respaldos)* | Carpeta del servidor donde se guardan los respaldos (`/data/expedientes/respaldos` en docker-compose) |

## Seguridad y privacidad

- **Solo datos ficticios:** la base de prueba, los PDFs de ejemplo y las pruebas
  usan alumnos inventados. El despliegue **no se conecta** a la base ni a la carpeta
  reales de Control Escolar, que están en la red privada de la escuela.
- Los PDF se procesan en **archivos temporales con nombre aleatorio** que se borran
  al terminar, aunque haya error. Solo se conservan si se pide `guardar=true` y el
  alumno se encontró por CURP verificada.
- Se valida el tamaño y que el archivo sea realmente un PDF antes de procesarlo.
- Todas las consultas SQL usan parámetros (sin concatenar texto del usuario).
- La imagen corre con un usuario sin privilegios (`clasificador`).
- Las contraseñas de la base de prueba tienen un valor por defecto (solo sirven para datos inventados). Si se
  personalizan en `.env`, ese archivo **no** se incluye en la imagen (`.dockerignore`) ni se sube a Git (`.gitignore`).
- El vectorizador del modelo se publica **sin CURPs ni folios** (`herramientas/anonimizar_vectorizador.py`).
- Eliminar un documento **no borra el PDF**: se mueve a `archivos_eliminados` con una bitácora (`registro_eliminados.csv`).
- **Fase III: usuarios y roles.** Tres usuarios fijos: **administrador** (todo, incluidos los respaldos), **operador** (todo menos respaldos) y **consultor**
  (solo consultar y ver PDF). Cada ruta exige un permiso: `consultar` (ver), `capturar` (subir, guardar, eliminar, corregir CURP) o `respaldar`; el **servidor** responde
  `401` sin sesión y `403` si el rol no alcanza (no depende de que la pantalla oculte botones). La cookie es `HttpOnly` y `SameSite=Strict`; 5 intentos fallidos
  bloquean la IP 5 minutos; las contraseñas viven en variables de entorno (o como hash), no en el código. Las bitácoras y la descripción de cada archivo guardado
  llevan el nombre del usuario. Con datos reales hay que cambiar las contraseñas de demostración y usar HTTPS.
- Los **respaldos** contienen datos personales: solo se habilitan si se define `RESPALDOS_DIR`, solo se descargan archivos con el patrón de nombre que genera el
  sistema (no se acepta ninguna ruta) y, con contraseña activa, requieren sesión.
- Los **duplicados** se guardan con un nombre que debe empezar con el id del alumno (se valida en el servidor, no solo en la pantalla).

## Regenerar los datos ficticios

```bash
python ejemplos/generar_ejemplos.py      # PDFs de ejemplo
python db/generar_base_prueba.py         # base de datos de prueba
```
