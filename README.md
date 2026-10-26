# FASE II — Sistema de Expedientes con IA (versión web en Docker)

> 🚧 **Estado: Fase II = avance del proyecto, no la versión final.** Funciona de punta a punta con una base de datos
> **de prueba** (datos inventados). Más abajo, en [Estado de esta fase](#estado-de-esta-fase), se explica qué ya está
> hecho y qué falta para el proyecto final.

Este proyecto es un **programa que lee documentos escolares escaneados** (en PDF) y dice
automáticamente:

- **qué documento es**: acta de nacimiento, CURP, certificado de secundaria,
  certificado final, certificado parcial o equivalencia;
- **la CURP, el nombre y la fecha de nacimiento** de la persona;
- **a qué alumno pertenece**, buscándolo en una base de datos de prueba;
- y, después de que una persona lo revisa, **lo guarda en el expediente del alumno**.

Es la **versión web, en Docker, del *Sistema de Expedientes* de escritorio (Fase I)**: tiene la
**misma pantalla y el mismo flujo de trabajo** (lista de documentos por lotes, estados de colores,
revisión, guardar, consultar expediente), pero se abre en el navegador y se instala con **un solo comando**.

Todo funciona dentro de **Docker**. Docker es un programa que crea "cajas" (llamadas
**contenedores**) con todo lo necesario ya instalado. Así el sistema funciona igual en
cualquier computadora, sin instalar Python, el lector de texto (OCR) ni la base de datos.

> **Importante:** este proyecto usa **solo datos inventados** (alumnos y documentos de
> ejemplo ficticios). No contiene información real de alumnos. Si agregas tus propios datos (ver sección 8), quedan solo en tu computadora.

### Estado de esta fase

| ✅ Ya está en la Fase II | ⏳ Falta para el proyecto final |
|---|---|
| Modelo de IA que clasifica 6 tipos de documento (~97 % de exactitud) | Conectarlo a la base de datos **real** de Control Escolar (hoy solo usa la de prueba) |
| Lectura de CURP, nombre y fecha con OCR | Contraseña de acceso y HTTPS (la app de escritorio ya pide contraseña) |
| Pantalla web igual a la app de escritorio (lotes, colores, revisión) | Usuarios y permisos distintos |
| Guardar, reemplazar, adicional, consultar y eliminar con papelera | Respaldos automáticos de los expedientes |
| Todo en Docker con un solo comando, base de datos de prueba incluida | Publicarlo en un servidor de la escuela o en la nube |
| 17 pruebas automáticas y esta guía | |

### ⚡ Resumen para quien ya sabe Docker

```bash
git clone https://github.com/Pulido325051/FASE-II.git && cd FASE-II
docker compose up --build        # primera vez: 5–15 min
# abrir http://localhost:8000
docker compose run --rm api pytest -v     # debe terminar con "17 passed"
```

No hace falta crear ningún archivo `.env`: trae contraseñas de prueba por defecto.

---

## Índice

1. [Lo que necesitas antes de empezar](#1-lo-que-necesitas-antes-de-empezar)
2. [Instalar WSL (una sola vez)](#2-instalar-wsl-una-sola-vez)
3. [Instalar Docker Desktop (una sola vez)](#3-instalar-docker-desktop-una-sola-vez)
4. [Descargar este proyecto](#4-descargar-este-proyecto)
5. [Encender el sistema](#5-encender-el-sistema)
6. [Usar el sistema en el navegador](#6-usar-el-sistema-en-el-navegador)
7. [Dónde se guardan los archivos de los alumnos](#7-dónde-se-guardan-los-archivos-de-los-alumnos)
8. [La base de datos de prueba](#8-la-base-de-datos-de-prueba)
9. [Comprobar que todo funciona (pruebas automáticas)](#9-comprobar-que-todo-funciona-pruebas-automáticas)
10. [Apagar y volver a encender](#10-apagar-y-volver-a-encender)
11. [Si algo sale mal](#11-si-algo-sale-mal)
12. [¿Qué hay en cada carpeta?](#12-qué-hay-en-cada-carpeta)
13. [Fase I (escritorio) frente a Fase II (web)](#13-fase-i-escritorio-frente-a-fase-ii-web)
14. [Palabras que quizá no conozcas](#14-palabras-que-quizá-no-conozcas)

### 📄 Documentación de la Fase II

| Documento | Qué contiene |
|---|---|
| [`docs/EVIDENCIA_INTEGRACION.md`](docs/EVIDENCIA_INTEGRACION.md) | Evidencia de integración: cada endpoint de la API con peticiones y respuestas reales |
| [`docs/MANUAL_DESPLIEGUE_NUBE.md`](docs/MANUAL_DESPLIEGUE_NUBE.md) (también en `.docx`) | Manual de despliegue en la nube: requerimientos, estrategia y pasos (Cloud Run, Azure, máquina virtual) |
| [`docs/VALIDACION_Y_PRUEBAS.md`](docs/VALIDACION_Y_PRUEBAS.md) (también en `.docx`) | Validación y pruebas: pruebas funcionales, 34 casos extremos, resultados y conclusiones, con capturas |
| [`docs/DETALLES_TECNICOS.md`](docs/DETALLES_TECNICOS.md) | Detalle técnico: arquitectura, API, seguridad |

---

## 1. Lo que necesitas antes de empezar

- Una computadora con **Windows 10/11** de 64 bits, o una **Mac** (con chip Apple o Intel). En Linux también funciona con Docker.
- Al menos **8 GB de memoria RAM** y **10 GB libres** en el disco.
- **Internet** (la primera vez se descargan unos 2 GB).
- Unos **30 minutos** la primera vez. Después, encenderlo toma menos de un minuto.

---

## 2. Instalar WSL (una sola vez)

> **Este paso es solo para Windows.** Si usas **Mac**, sáltalo y ve directo a la sección «En Mac» dentro del paso 3.

WSL es una función de Windows que Docker necesita para trabajar.

1. Haz clic en el botón **Inicio** de Windows y escribe `PowerShell`.
2. Sobre **Windows PowerShell**, haz clic derecho y elige **"Ejecutar como administrador"**.
   Acepta el mensaje que aparece.
3. En la ventana azul, escribe esto y presiona **Enter**:

   ```
   wsl --install
   ```

4. Espera a que termine (puede tardar varios minutos).
5. **Reinicia la computadora.**

> Si al reiniciar se abre una ventana que pide crear un usuario de "Ubuntu", puedes
> escribir cualquier nombre y contraseña sencillos (no se usan para este proyecto) o
> simplemente cerrarla.

---

## 3. Instalar Docker Desktop (una sola vez)

> **Mac:** los pasos de esta sección son para **Windows**. Los de Mac están más abajo, en «En Mac».

1. Entra a **https://www.docker.com/products/docker-desktop/**
2. Haz clic en **"Download for Windows – AMD64"**.
3. Abre el archivo descargado (`Docker Desktop Installer.exe`).
4. Deja marcada la opción **"Use WSL 2 instead of Hyper-V"** y haz clic en **OK**.
5. Al terminar, si lo pide, **cierra sesión o reinicia** la computadora.
6. Abre **Docker Desktop** desde el menú Inicio.
   - Acepta los términos de uso.
   - Si pide iniciar sesión o crear una cuenta, puedes hacer clic en **"Skip"** (omitir).
7. Espera a que abajo a la izquierda aparezca **"Engine running"** en verde.

**Para comprobar que quedó bien:**

1. Abre el menú Inicio, escribe `cmd` y abre **Símbolo del sistema** (normal, **no** como administrador).
2. Escribe esto y presiona **Enter**:

   ```
   docker --version
   ```

3. Debe aparecer algo como `Docker version 29.x.x`. ¡Listo!

---

### En Mac

El sistema es el mismo; cambia solo cómo se instala Docker y cómo se abre la terminal. (Está probado en Windows; en Mac debe funcionar igual,
porque las imágenes que usa tienen versión para chips Apple e Intel.)

**1. Saber qué chip tiene tu Mac.** Menú de la **manzana** (arriba a la izquierda de la pantalla) → **Acerca de esta Mac**. Dice *Chip Apple M1/M2/M3…* o *Intel*.

**2. Instalar Docker Desktop.**

1. Entra a **https://www.docker.com/products/docker-desktop/** y descarga la versión de **tu chip** (*Apple Silicon* o *Intel*).
2. Abre el archivo `.dmg` y **arrastra Docker a la carpeta Aplicaciones**.
3. Abre **Docker** desde Aplicaciones. Acepta los términos y, si pide la contraseña de tu Mac, escríbela. Si pide iniciar sesión, elige **Skip**.
4. Espera a que abajo a la izquierda diga **"Engine running"**.

**3. Abrir la Terminal.** Presiona **Cmd + Espacio**, escribe `Terminal` y presiona Enter. Comprueba que Docker quedó bien:

```
docker --version
docker compose version
```

**4. Descargar el proyecto.**

- *Con el ZIP:* haz doble clic en `FASE-II.zip` (se descomprime solo), mueve la carpeta **`FASE-II`** a tu carpeta personal (la de tu usuario, no a Escritorio ni Documentos si usas iCloud).
- *O con Git:* `git clone https://github.com/Pulido325051/FASE-II.git`

**5. Encender el sistema.** En la Terminal, entra a la carpeta y enciende (en lugar de `cd C:\FASE-II` se usa `cd ~/FASE-II`):

```
cd ~/FASE-II
docker compose up --build -d
docker compose ps
```

Espera a que `api` y `db` digan **(healthy)** (la primera vez tarda de 5 a 15 minutos) y abre **http://localhost:8000** en Safari, Chrome o Firefox.

**6. Probar y apagar.** Todo lo demás del manual es igual: las pruebas (`docker compose run --rm api pytest -v`), apagar (`docker compose down`) y encender (`docker compose up -d`).
Para copiar el archivo de ajustes usa `cp .env.example .env` en lugar de `copy`. La carpeta `expedientes` aparece en el Finder dentro de `FASE-II`.

**Problemas frecuentes en Mac:**

| Lo que pasa | Qué hacer |
|---|---|
| macOS dice que no puede abrir Docker "porque es de un desarrollador no identificado" | **Ajustes del Sistema → Privacidad y seguridad** → junto al aviso de Docker, pulsa **Abrir de todos modos** |
| Error `no matching manifest for linux/arm64` | En Docker Desktop: **Settings → General → Use Rosetta for x86_64/amd64 emulation** y vuelve a ejecutar `docker compose up --build -d` |
| No guarda los PDFs en `expedientes` | Mueve el proyecto a tu carpeta personal (fuera de iCloud) y revisa en **Settings → Resources → File sharing** que esté permitida |
| Un documento tarda mucho en leerse | En **Settings → Resources** dale más CPU y memoria a Docker (recomendado 2 CPU y 2 GB) |

---

## 4. Descargar este proyecto

> **Mac:** los pasos de descarga y encendido para Mac están en «En Mac», dentro del paso 3.

El repositorio es **público**: no necesitas invitación ni cuenta de GitHub para descargarlo.

**Forma fácil (sin programas extra):**

1. Entra a la página del repositorio en GitHub.
2. Haz clic en el botón verde **"<> Code"** y luego en **"Download ZIP"**.
3. Abre la carpeta **Descargas**, haz clic derecho sobre el ZIP y elige **"Extraer todo…"**.
4. Mueve la carpeta extraída al disco `C:` y cámbiale el nombre a **`FASE-II`**.
   Debe quedar así: `C:\FASE-II` (dentro deben verse `Dockerfile`, `docker-compose.yml`, `app`, etc.).

> Recomendado: guárdala en el disco `C:` y **no** en una memoria USB. Docker trabaja
> más rápido y sin errores desde el disco de la computadora.

**Forma con Git (si ya lo usas):**

```
cd C:\
git clone https://github.com/Pulido325051/FASE-II.git
```

---

## 5. Encender el sistema

> **Mac:** usa `cd ~/FASE-II` en la Terminal (ver «En Mac», paso 3).

1. Asegúrate de que **Docker Desktop esté abierto** y diga **"Engine running"**.
2. Abre **Símbolo del sistema** (`cmd`), entra a la carpeta del proyecto y enciende:

   ```
   cd C:\FASE-II
   docker compose up --build -d
   ```

3. **La primera vez tarda entre 5 y 15 minutos**, porque descarga todo lo necesario.
   Verás muchas líneas de texto: es normal. Espera a que vuelva a aparecer la línea
   para escribir (`C:\FASE-II>`).
4. Revisa que todo esté encendido con:

   ```
   docker compose ps
   ```

   Deben aparecer **dos** servicios y los dos deben decir **(healthy)**:

   | Servicio | Qué es |
   |---|---|
   | `api` | El programa que lee y clasifica los documentos (la página web) |
   | `db` | La base de datos de prueba con 100 alumnos inventados |

   > Si dice **(health: starting)**, espera 30 segundos y vuelve a escribir el comando.

> **No necesitas crear ningún archivo de contraseñas.** El sistema trae contraseñas de prueba por defecto
> (la base solo contiene datos inventados). Si quieres cambiarlas o cambiar los puertos,
> copia `.env.example` como `.env` (`copy .env.example .env`) y edítalo.

---

## 6. Usar el sistema en el navegador

Abre tu navegador (Chrome, Edge, Firefox…) y entra a:

### 👉 http://localhost:8000

Verás la pantalla **"Expedientes - Control Escolar"**. Arriba a la derecha debe decir
**"Conectado a controlescolar_prueba: 100 alumnos, … archivos"**. Si dice *Cargando modelo…*, espera unos segundos.

### Cómo se ve y qué hace cada parte

| Parte de la pantalla | Para qué sirve |
|---|---|
| **Agregar PDFs…** / **Agregar carpeta…** | Cargar documentos (también puedes **arrastrarlos a cualquier parte de la ventana**, incluso carpetas completas) |
| **Lista de documentos** | Cada PDF con su estado, tipo detectado, CURP, alumno encontrado y una nota |
| **Documento seleccionado** | Detalle del documento: puedes **cambiar el tipo**, **corregir la CURP** y buscar al alumno por CURP o por nombre |
| **Guardar en expediente** | Guarda el documento seleccionado (`<idAlumno>_<TIPO>.pdf`) |
| **Guardar todos los 'Listo'** | Guarda de una vez todos los documentos en verde |
| **Consultar expediente…** | Busca un alumno (nombre, CURP o matrícula) y muestra sus documentos; ahí se puede **abrir** o **eliminar** un documento |

### Qué significan los colores

| Color | Estado | Significado |
|---|---|---|
| ⚪ sin color | En cola / Leyendo… | Esperando o procesándose |
| 🟩 verde | **Listo** | Todo coincide: se puede guardar |
| 🟨 amarillo | **Revisar** | Hay una duda (se explica en la columna *Nota*): confirma o corrige antes de guardar |
| 🟦 azul | **Guardado** | Ya está en el expediente del alumno |
| 🟥 rojo | **Error** | No se pudo leer o guardar (la nota dice por qué) |

### Prueba guiada con los documentos de ejemplo

En la carpeta `ejemplos` hay dos documentos **inventados** de la alumna ficticia
*MARIA FERNANDA EJEMPLO LOPEZ*, que existe en la base de prueba y empieza sin documentos.

1. **Arrastra** a la ventana `ejemplos\constancia_curp_ficticia.pdf` y `ejemplos\acta_nacimiento_ficticia.pdf`
   (o usa **Agregar PDFs…**). Cada uno tarda entre 10 y 40 segundos en leerse.
2. Aparecerán en **verde (Listo)**: tipo detectado, CURP y la alumna encontrada en la base de datos.
3. Haz clic en la primera fila: abajo verás el detalle y **"Se guardará como: 1_CURP.pdf"**.
4. Pulsa **Guardar todos los 'Listo'** → **Sí**. Pasan a **azul (Guardado)**, en orden: `1_CURP.pdf` y `1_ACTA DE NAC.pdf`.
5. Pulsa **Consultar expediente…**, escribe `EJEMPLO` y **Buscar**, y selecciona a la alumna.
   → Verás sus documentos en orden (CURP, certificado de secundaria, acta).
6. **Doble clic** sobre un documento para abrir su PDF.

### Pruebas extra (para ver todo lo que hace)

- **Reemplazar o adicional:** quita los documentos guardados de la lista (**Quitar guardados de la lista**), carga otra vez
  `constancia_curp_ficticia.pdf` y pulsa **Guardar en expediente**: como la alumna ya tiene su CURP, el sistema pregunta
  **Reemplazar / Guardar como adicional / Cancelar**. (En *Guardar todos* estos casos se dejan en amarillo para decidir uno por uno.)
- **Corregir datos:** selecciona un documento, cambia el **Tipo de documento** o escribe otra **CURP** y pulsa
  **Buscar alumno por CURP**. Si el documento no tiene CURP legible, usa **Buscar por nombre…** y elige al alumno.
- **Eliminar sin perder:** en *Consultar expediente…*, elige un documento y pulsa **Eliminar documento…**. Se quita del
  expediente, pero el PDF **no se borra**: se mueve a la carpeta de *eliminados* y se anota en una bitácora
  (`registro_eliminados.csv`: quién, cuándo y qué).

### Otras páginas útiles

| Dirección | Para qué sirve |
|---|---|
| http://localhost:8000/docs | Documentación de la API: puedes probar cada función con el botón **"Try it out"** |
| http://localhost:8000/salud | Muestra si el servicio y la base de datos están funcionando |

> **localhost** significa "esta misma computadora". Estas direcciones solo funcionan
> mientras **Docker Desktop está abierto** y el sistema está encendido.

---

## 7. Dónde se guardan los archivos de los alumnos

Cuando pulsas **Guardar en expediente**, el PDF se guarda en la carpeta **`expedientes`** que está dentro del proyecto
(por ejemplo `C:\FASE-II\expedientes`). Es una carpeta normal de tu computadora: ábrela con el Explorador de Windows.

```
expedientes/
├── archivos/               PDFs guardados, con el nombre <idAlumno>_<TIPO>.pdf   (ej. 1_CURP.pdf, 1_ACTA DE NAC.pdf)
└── archivos_eliminados/    PDFs que se eliminaron desde "Consultar expediente"
    └── registro_eliminados.csv   quién, cuándo y qué se eliminó
```

- Las carpetas `archivos` y `archivos_eliminados` se crean solas.
- La carpeta `expedientes` **sí existe en GitHub, pero su contenido no se sube** (los PDFs de los alumnos se quedan en tu computadora).
- `docker compose down` y `docker compose down -v` **no** borran estos PDFs. Si quieres empezar de cero, borra también el contenido
  de `archivos` y `archivos_eliminados` (la base de datos y los PDFs deben reiniciarse juntos).
- A qué alumno pertenece cada PDF lo dice la **base de datos**, en la tabla `archivos` (siguiente sección).

---

## 8. La base de datos de prueba

El sistema necesita una base de datos para saber **quiénes son los alumnos** y **qué documentos tiene cada uno**.
En esta fase se usa una base **inventada**, que viene incluida y se crea **sola** la primera vez que enciendes el sistema
(el contenedor `db` carga los archivos de la carpeta `db/init/`). No tienes que instalar MySQL ni hacer nada.

**Qué contiene** (base `controlescolar_prueba`):

| Tabla | Qué guarda | Cuántos registros |
|---|---|---|
| `alumnos` | Nombre, apellidos, CURP, matrícula, generación, escuela, correo… | **100 alumnos inventados** (nombres comunes al azar, CURP con dígito verificador válido) |
| `archivos` | Un renglón por documento: nombre del PDF, tipo (`CURP`, `ACTA DE NAC`, `CERT DE SEC`…), alumno, fecha | **278** registros inventados (sin PDF real detrás) |

- La alumna **id 1**, *MARIA FERNANDA EJEMPLO LOPEZ* (CURP `EELM060312MCHJPRA0`), empieza **sin documentos**: es la de los PDFs de la demostración.
- Tiene **la misma estructura** que las tablas reales de Control Escolar, y **no** se conecta a la base real ni a ninguna base de la escuela.

**Cómo verla** (opcional, solo si quieres curiosear):

- *Con DBeaver o MySQL Workbench:* servidor `localhost`, puerto **3307**, base `controlescolar_prueba`, usuario `clasificador`, contraseña `prueba-2026`
  (o los datos de tu `.env` si los cambiaste).
- *Sin instalar nada*, desde la terminal dentro de `C:\FASE-II`:

  ```
  docker compose exec db mysql -uclasificador -pprueba-2026 controlescolar_prueba -e "SELECT id, nombre, apaterno, curp FROM alumnos LIMIT 5;"
  docker compose exec db mysql -uclasificador -pprueba-2026 controlescolar_prueba -e "SELECT id, nombre, tipoArchivo, idAlumno FROM archivos WHERE idAlumno = 1;"
  ```

**Cómo agregar tus propios datos** (por ejemplo tu nombre y CURP, para probar con tus documentos):

1. Copia `db/init/03_mis_datos.sql.example` como `db/init/03_mis_datos.sql` y cambia los datos (lo importante son el nombre y la CURP).
2. Reinicia la base (ver abajo). Ese archivo está en `.gitignore`: **tus datos se quedan en tu computadora y no se suben a GitHub**.

Después puedes cargar un documento tuyo (un acta o tu CURP en PDF) y el sistema te encontrará por tu CURP.

**Cómo reiniciarla** (volver a los 100 alumnos y 278 archivos originales, más tus datos si agregaste el archivo `03`):

```
docker compose down -v
docker compose up -d
```

Y borra después el contenido de `expedientes\archivos` y `expedientes\archivos_eliminados` para que los PDFs coincidan con la base.

**Cómo cambiar los datos de prueba:** `python db/generar_base_prueba.py` genera de nuevo `db/init/01_esquema.sql` y `02_datos.sql`;
luego reinicia con los dos comandos de arriba.

> La base solo se carga cuando está **vacía** (la primera vez o después de `down -v`). Si cambias los archivos de `db/init/`
> o las contraseñas del `.env`, hay que reiniciarla con `docker compose down -v`.

---

## 9. Comprobar que todo funciona (pruebas automáticas)

El proyecto trae **17 pruebas automáticas** que revisan todo el sistema por ti.

En **Símbolo del sistema**, dentro de `C:\FASE-II`, escribe:

```
docker compose run --rm api pytest -v
```

Espera menos de un minuto. Al final debe decir:

```
17 passed
```

Qué revisan las pruebas:

- que el servicio, la página y la documentación respondan;
- que una CURP y un acta de ejemplo se clasifiquen bien y se lean su CURP, nombre y fecha;
- que se rechacen archivos que no son PDF, demasiado grandes o dañados;
- que se pueda buscar alumnos y ver su expediente en orden;
- que se guarde un documento en el expediente **sin duplicarlo**, y que funcionen **reemplazar**, **adicional**,
  **abrir PDF** y **eliminar** (con el PDF conservado en *eliminados*).

Las pruebas dejan la base de datos como estaba.

---

## 10. Apagar y volver a encender

| Quiero… | Escribe (dentro de `C:\FASE-II`) |
|---|---|
| **Apagar** el sistema | `docker compose down` |
| **Encenderlo** otra vez | `docker compose up -d` |
| Ver si está encendido | `docker compose ps` |
| Ver qué está haciendo (mensajes) | `docker compose logs -f api` (para salir: **Ctrl + C**) |
| **Empezar de cero** (reinicia la base de prueba) | `docker compose down -v`, luego `docker compose up -d`, y borra el contenido de `expedientes\archivos` |

> Si apagas la computadora, el sistema se enciende solo la próxima vez que abras
> **Docker Desktop**.

---

## 11. Si algo sale mal

| Lo que pasa | Qué hacer |
|---|---|
| *(Solo Mac)* macOS bloquea Docker, falla `arm64` o no guarda PDFs | Ver la tabla «Problemas frecuentes en Mac», dentro del paso 3 |
| `docker` no se reconoce como comando | Cierra y vuelve a abrir el Símbolo del sistema. Si sigue, revisa que Docker Desktop esté instalado (paso 3). |
| Error que menciona **"daemon"** o **"pipe"** | Docker Desktop no está abierto. Ábrelo y espera a que diga **"Engine running"**. |
| La página http://localhost:8000 no abre | Escribe `docker compose ps`. Si no aparece nada, enciéndelo con `docker compose up -d`. Si dice *starting*, espera un minuto. |
| Error **"port is already allocated"** (puerto ocupado) | Otro programa usa el puerto 8000 o 3307. Copia `.env.example` como `.env`, cambia `API_PUERTO` (por ejemplo a `8080`) y/o `DB_PUERTO`, enciende de nuevo y abre `http://localhost:8080`. |
| Error **"container name ... is already in use"** | Hay contenedores de otro proyecto con el mismo nombre. Apágalos con `docker compose down` en la carpeta de ese proyecto. |
| Arriba dice **"Sin conexión a la base de datos"** | La base aún está iniciando (puede tardar un minuto la primera vez). Espera y recarga la página. Si sigue: `docker compose logs db`. |
| Docker Desktop dice que **WSL** no está instalado o está desactualizado | Abre PowerShell como administrador, escribe `wsl --update` y reinicia. |
| La primera vez tarda muchísimo | Es normal: descarga cerca de 2 GB. Revisa tu conexión a internet. |
| Un documento tarda mucho en leerse | Es normal: el OCR usa mucho procesador (10 a 40 segundos por PDF; se leen 2 a la vez). En Docker Desktop → *Settings → Resources* puedes darle más CPU y memoria. |
| Un documento sale con datos "(no se pudo leer)" | Puede pasar con escaneos borrosos, documentos escritos a mano o sellos encima de los datos. Corrige la CURP a mano o usa *Buscar por nombre…*. |
| Cambié las contraseñas del `.env` y ahora la base no conecta | La base guardó las contraseñas anteriores. Escribe `docker compose down -v` y luego `docker compose up -d`. |
| Al guardar un documento dice que no se pudo escribir en la carpeta | Revisa que la carpeta `expedientes` exista dentro del proyecto y que Docker Desktop tenga acceso al disco (*Settings → Resources → File sharing*). En Linux: `chmod 777 expedientes`. |

---

## 12. ¿Qué hay en cada carpeta?

| Carpeta o archivo | Qué contiene |
|---|---|
| `app/` | El programa: la pantalla web (`static/index.html`) y el código que lee y clasifica los documentos |
| `modelo/` | El **modelo de inteligencia artificial** ya entrenado que reconoce el tipo de documento |
| `db/` | La base de datos de prueba: estructura de las tablas y 100 alumnos **inventados** (ver sección 8) |
| `expedientes/` | **Aquí se guardan los PDFs de los alumnos** al pulsar *Guardar en expediente* (ver sección 7). Su contenido no se sube a GitHub |
| `ejemplos/` | Dos documentos PDF **inventados** para probar |
| `tests/` | Las 17 pruebas automáticas |
| `herramientas/` | `anonimizar_vectorizador.py`: quita datos personales del modelo antes de publicarlo (ver abajo) |
| `docs/` | Documentación: evidencia de integración, manual de despliegue en la nube, validación y pruebas (Markdown y Word, con capturas en `docs/capturas/`) y detalle técnico |
| `Dockerfile` | Las instrucciones para armar el contenedor del programa |
| `docker-compose.yml` | Las instrucciones para encender juntos el programa y la base de datos |
| `docker-compose.muestra.yml` | Opcional: arranca con una muestra propia en lugar de la base inventada (los datos reales **nunca** se suben a GitHub) |
| `.env.example` | **Opcional**: contraseñas y puertos personalizados (copiar como `.env`) |

### Privacidad del modelo

El modelo guarda solo estadísticas de **palabras sueltas**, no documentos. Aun así, el vectorizador entrenado con
documentos reales había capturado algunas CURP y folios; se **eliminaron** con `herramientas/anonimizar_vectorizador.py`
(las predicciones quedan idénticas). **Si vuelves a entrenar el modelo**, ejecuta antes de subirlo a GitHub:

```
python herramientas/anonimizar_vectorizador.py vectorizador.pkl modelo/vectorizador.pkl
```

---

## 13. Fase I (escritorio) frente a Fase II (web)

| | Fase I — Escritorio | **Fase II — Web (este proyecto)** |
|---|---|---|
| Se usa en | Ventana de Windows (`.exe`) | Navegador |
| Instalación | Tesseract + Poppler + `config.ini` en cada PC | **Docker**: `docker compose up` |
| Base de datos | MySQL real de Control Escolar | MySQL de **prueba** (datos inventados) incluida; la conexión a la real queda para el proyecto final |
| Pantalla y flujo | Lista por lotes, estados de colores, revisión, expediente | **El mismo** |
| Reemplazar / adicional / eliminar (con papelera) | Sí | Sí |
| Contraseña de acceso | Sí | **Pendiente** (hay que agregarla antes de usar datos reales) |
| Otros programas pueden usarlo (API) | No | Sí (`/docs`) |

---

## 14. Palabras que quizá no conozcas

| Palabra | Qué significa |
|---|---|
| **Docker** | Programa que crea "cajas" con todo lo necesario para que otro programa funcione igual en cualquier computadora. |
| **Contenedor** | Cada una de esas "cajas" encendidas. Aquí hay dos: el programa y la base de datos. |
| **Imagen** | La "plantilla" con la que se crea un contenedor. |
| **WSL** | Función de Windows que permite usar programas de Linux. Docker la necesita. |
| **localhost** | Tu propia computadora. `localhost:8000` es la "puerta" 8000 de tu computadora. |
| **OCR** | Tecnología que "lee" el texto que aparece en una imagen o documento escaneado. |
| **CURP** | Clave Única de Registro de Población. Tiene 18 caracteres y el último sirve para comprobar que está bien escrita (dígito verificador). |
| **API** | Forma en que otros programas pueden usar este sistema enviándole documentos. |
| **Expediente** | El conjunto de documentos registrados de un alumno. En este proyecto los PDFs están en la carpeta `expedientes/`. |
| **Base de datos de prueba** | Una base con datos inventados para practicar sin tocar información real. |
| **Modelo** | El programa de inteligencia artificial entrenado con ejemplos para reconocer cada tipo de documento. |
