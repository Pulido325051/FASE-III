# Carpeta `expedientes/`

Aquí es donde el sistema **guarda los documentos de los alumnos** cuando pulsas *Guardar en expediente*.
Es una carpeta normal de tu computadora: puedes abrirla con el Explorador de Windows.

```
expedientes/
├── archivos/               PDFs guardados, con el nombre <idAlumno>_<TIPO>.pdf   (ej. 1_CURP.pdf)
└── archivos_eliminados/    PDFs que se eliminaron desde "Consultar expediente"
    └── registro_eliminados.csv   quién, cuándo y qué se eliminó
```

- Estas carpetas se crean solas la primera vez que guardas un documento.
- **No se suben a GitHub**: solo esta carpeta y este aviso. Los PDFs se quedan en tu computadora.
- `docker compose down` y `docker compose down -v` **no** borran estos archivos. Para empezar de cero, borra también
  el contenido de `archivos/` y `archivos_eliminados/`.
- El registro de cada documento (a qué alumno pertenece) está en la base de datos de prueba, tabla `archivos`.
