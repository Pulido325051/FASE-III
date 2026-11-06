# Novedades de la Fase III (frente a la Fase II)

La Fase II dejó funcionando la versión web del *Sistema de Expedientes* con una base de datos de prueba. La Fase III **no
cambia el modelo ni el flujo base**: agrega las mejoras que salieron de usar el sistema de escritorio con la base real
(documentos duplicados, CURP mal escritas en la BD, listas largas que hay que limpiar a mano) y las que la Fase II dejó
pendientes (contraseña de acceso, respaldos).

## Resumen

| # | Novedad | Para qué sirve |
|---|---|---|
| 1 | **Aviso de «ya tiene este documento»** al leer el PDF (fila **turquesa**) | Antes solo se descubría al pulsar *Guardar*; ahora se ve en la lista desde que se lee |
| 2 | **Duplicado con nombre**: el id del alumno va **fijo** al inicio | Los nombres escritos a mano (`Duplicado.pdf`) chocaban entre alumnos porque todos los PDF comparten una carpeta |
| 3 | Categoría **«Duplicado»** que se elige **a mano** | La IA nunca puede decir «duplicado» (el PDF de un duplicado no lo dice y se ve igual que un certificado de término) |
| 4 | Botones **Quitar los que ya están cargados** y **Quitar los que no están en la BD** | Limpiar la lista de golpe en vez de uno por uno |
| 5 | **Alumno por nombre sin CURP** deja de pedir revisión si el nombre coincide y la fecha concuerda | Muchas actas no traen CURP legible pero sí el nombre |
| 6 | **Corregir la CURP del alumno en la BD** | Hay CURP mal escritas en la base y por eso no se encontraba al alumno |
| 7 | **Respaldos** de la base de datos (.sql) y de los PDF (.zip) desde la pantalla | Respaldos manuales, con descarga |
| 8 | **Contraseña de acceso** opcional (`APP_CLAVE`) | Era el pendiente principal de la Fase II; protege también los respaldos y la corrección de CURP |
| 9 | Botones con **tonos suaves de color** y leyenda de colores | Identificar más rápido para qué sirve cada botón |

## Detalle

### 1. «Ya tiene este documento» (fila turquesa)
Al terminar de leer cada PDF, el servidor ya devuelve los documentos del mismo tipo que el alumno tiene registrados
(`documentos_del_mismo_tipo`). La pantalla los usa para pasar el documento a **Revisar** con una fila turquesa distinta del amarillo
de «Revisar» y una nota que dice cuál archivo ya existe. Se vuelve a revisar si se cambia el alumno o el tipo a mano.

![Fila turquesa: el alumno ya tiene ese documento](capturas/07_ya_tiene_documento.png)

Al guardar aparece una ventana con tres opciones claras:

![Ventana: este alumno ya tiene este documento](capturas/08_dialogo_ya_existe.png)

### 2. Duplicado con nombre (id fijo)
Si se elige *Guardarlo también, con otro nombre*, el número del alumno (`1_`) aparece fijo y no se puede quitar; la persona solo escribe el resto
(se propone `DUPLICADO`, luego `DUPLICADO 2`, etc.). El servidor lo **valida de nuevo**: vacío, símbolos prohibidos (`/ \ : * ? " < > |`),
más de 100 caracteres, sin el id del alumno o nombre ya usado (en la carpeta o en la BD) se rechazan con un mensaje claro.

![Nombre del duplicado con el id fijo](capturas/09_nombre_duplicado.png)

### 3. Categoría «Duplicado»
Es un tipo más de la lista *Tipo de documento*, pero **no es una clase del modelo**: `/tipos` la marca `manual: true` y `/salud` no la lista entre las
categorías de la IA. Se guarda como `<id>_DUPLICADO.pdf` con tipo `DUPLICADO` (igual que los duplicados del sistema anterior), no cuenta como
«ya tiene este documento» y no se tiene en cuenta como documento faltante en el resumen del expediente.

### 4. Limpiar la lista
Una fila de botones, cada uno con el color de lo que quita: **guardados** (azul), **ya cargados** (turquesa) y **no están en la BD** (amarillo). Piden
confirmación mostrando la lista y **no borran nada** del expediente ni de los PDF originales.

### 5. Alumno por nombre sin CURP
Antes, todo alumno encontrado solo por nombre quedaba en *Revisar*. Ahora pasa a *Listo* solo si: el documento **no trae CURP**, el nombre coincide
casi completo **en los dos sentidos** (≥ 80 %) y, si se leyó la fecha de nacimiento, **concuerda con la CURP del alumno**. Si algo no cuadra
(nombre parcial, fecha distinta, CURP leída pero no registrada) sigue en *Revisar* y la nota dice por qué (`reglas.py`, con pruebas).

### 6. Corregir la CURP del alumno en la BD
`POST /alumnos/{id}/curp`. Exige una CURP con **formato y dígito verificador válidos**, que **ningún otro alumno** la tenga y que la CURP en la BD siga siendo
la que se vio (no pisa un cambio hecho por otra persona). Cada cambio queda en `registro_cambios_curp.csv` (fecha, usuario, alumno, CURP anterior y nueva).

![Confirmación para corregir la CURP](capturas/10_corregir_curp.png)

### 7. Respaldos
La BD se exporta a un `.sql` con **una lectura consistente** (aunque otra persona esté guardando) y los PDF a un `.zip`; ambos se hacen en segundo plano con avance,
se pueden cancelar y se descargan desde la misma pantalla. Se guardan en `expedientes/respaldos`. Solo se habilitan si se define `RESPALDOS_DIR`.

![Respaldos](capturas/11_respaldos.png)

### 8. Contraseña de acceso
Con `APP_CLAVE` definida, la página pide nombre y contraseña; todas las rutas (salvo la página, `/salud` y el inicio de sesión) exigen sesión. Admite la contraseña
tal cual o el hash `pbkdf2_sha256$...` del programa de escritorio. Cinco intentos fallidos bloquean la IP cinco minutos. El nombre que se escribe queda
registrado en las bitácoras y en la descripción de los archivos guardados.

![Pantalla de entrada](capturas/12_contrasena.png)

## Cómo se comprobó

- **28 pruebas automáticas** (`docker compose run --rm api pytest -v`): las 17 de la Fase II más 11 nuevas (duplicados con nombre, categoría Duplicado, corregir CURP,
  respaldos, contraseña, reglas de alumno por nombre).
- **Prueba en navegador real** (Microsoft Edge): subir los PDF de ejemplo, ya cargado → turquesa, duplicado con nombre y errores de nombre, categoría Duplicado,
  los dos botones de limpiar, corregir CURP (y restaurarla), respaldo de la BD con descarga, y entrar/salir con contraseña. Se encontró y corrigió un error
  (con contraseña, la lista de tipos no cargaba tras entrar).

## Archivos que cambiaron

| Archivo | Cambio |
|---|---|
| `app/main.py` | Tipo Duplicado, modo `personalizado`, `/alumnos/{id}/curp`, respaldos, contraseña, versión 3.0.0 |
| `app/almacenamiento.py`, `app/base_datos.py` | Nombre con prefijo, validación, `actualizar_curp`, usuario en bitácoras (mismo código que el programa de escritorio) |
| `app/respaldos.py` *(nuevo)* | Respaldo de la BD y de los archivos |
| `app/reglas.py` *(nuevo)* | Reglas de «alumno por nombre» |
| `app/static/index.html` | Pantalla: colores, ventanas nuevas, botones de limpiar, respaldos y entrada |
| `docker-compose.yml`, `.env.example` | `RESPALDOS_DIR`, `APP_CLAVE`, imagen `fase3` |
| `tests/` | 11 pruebas nuevas |

## Lo que sigue pendiente

Conectarlo a la base de datos **real** (hoy solo usa la de prueba), HTTPS, usuarios con permisos distintos, respaldos programados y publicarlo en un servidor.
