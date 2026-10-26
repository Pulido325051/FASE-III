"""Genera la base de datos de PRUEBA con datos 100% FICTICIOS.

Misma estructura que las tablas reales `alumnos` y `archivos` de Control Escolar,
pero con alumnos inventados: nombres comunes combinados al azar y CURPs generadas
con la regla oficial (iniciales, fecha, sexo, estado y digito verificador valido),
para que el sistema las procese igual que las reales sin exponer datos personales.

    python db/generar_base_prueba.py      -> db/init/01_esquema.sql y db/init/02_datos.sql
"""

import random
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
from app.motor_ocr import digito_verificador  # noqa: E402

TOTAL_ALUMNOS = 100
random.seed(2026)   # siempre genera los mismos datos

NOMBRES_M = ["MARIA FERNANDA", "ANA SOFIA", "DANIELA", "VALERIA", "XIMENA", "CAMILA", "REGINA", "ANDREA",
             "PAULINA", "ITZEL", "KARLA", "JIMENA", "LUCIA", "GUADALUPE", "ALEJANDRA", "NATALIA", "ESTEFANIA",
             "MONSERRAT", "DULCE MARIA", "VANESSA", "ARELY", "YARETZI", "BRENDA", "MARISOL", "LIZBETH"]
NOMBRES_H = ["JOSE LUIS", "JUAN CARLOS", "LUIS ANGEL", "DIEGO", "SANTIAGO", "EMILIANO", "MATEO", "ADRIAN",
             "JESUS", "MIGUEL ANGEL", "OSCAR", "RICARDO", "CRISTIAN", "EDUARDO", "FERNANDO", "HECTOR",
             "IVAN", "JORGE", "KEVIN", "MANUEL", "OMAR", "RAUL", "SERGIO", "URIEL", "ALEXIS"]
APELLIDOS = ["HERNANDEZ", "GARCIA", "MARTINEZ", "LOPEZ", "GONZALEZ", "RODRIGUEZ", "PEREZ", "SANCHEZ",
             "RAMIREZ", "TORRES", "FLORES", "RIVERA", "GOMEZ", "DIAZ", "CRUZ", "MORALES", "REYES", "ORTIZ",
             "GUTIERREZ", "CHAVEZ", "RAMOS", "MENDOZA", "RUIZ", "AGUILAR", "CASTILLO", "JIMENEZ", "MORENO",
             "ROMERO", "ALVAREZ", "VAZQUEZ", "DOMINGUEZ", "HOLGUIN", "CHAPARRO", "LOYA", "OLIVAS", "CARRASCO"]
# Municipios reales de Chihuahua; escuelas con numero ficticio
MUNICIPIOS = ["CHIHUAHUA", "JUAREZ", "CUAUHTEMOC", "DELICIAS", "PARRAL", "GUACHOCHI", "BOCOYNA",
              "BATOPILAS", "MADERA", "JIMENEZ", "CAMARGO", "GUERRERO", "URIQUE", "MORELOS", "BALLEZA"]
# Variantes de captura manual que existen en la BD real, con pesos parecidos a la realidad
# (la forma mas comun domina; los errores de dedo son pocos). Sirven para probar los duplicados.
VARIANTES = {
    "CURP": {"CURP": 95, " CURP": 3, "CUPR": 2},
    "ACTA": {"ACTA DE NAC": 40, "ACT NAC": 35, "ACTA NAC": 17, "ACTA NACIMIENTO": 5, "ACT DE NAC": 3},
    "SEC": {"CERT DE SEC": 50, "CERT SEC": 45, "CERT. SEC": 3, "CERT  SEC": 2},
    "FINAL": {"CERT FINAL": 90, "FINAL": 7, "CERT. FINAL": 3},
}
VOCALES = "AEIOU"
PALABRAS_ALTISONANTES = {"BUEI", "CACA", "CAGA", "COGE", "COJA", "CULO", "FETO", "JOTO", "KAKA", "MAME",
                         "MEAR", "MEON", "MOCO", "PEDO", "PENE", "PUTA", "PUTO", "RATA", "RUIN", "KULO"}

# Alumna ficticia de los PDFs de ejemplo (ejemplos/*.pdf), para la demostracion de punta a punta
ALUMNA_DEMO = dict(nombre="MARIA FERNANDA", apaterno="EJEMPLO", amaterno="LOPEZ", sexo="Femenino",
                   fecha_nac=date(2006, 3, 12), curp="EELM060312MCHJPRA0")


def sin_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def primera_vocal_interna(p):
    return next((c for c in p[1:] if c in VOCALES), "X")


def primera_consonante_interna(p):
    return next((c for c in p[1:] if c not in VOCALES), "X")


def generar_curp(nombre, ap1, ap2, nacimiento, sexo, estado="CH"):
    nombres = nombre.split()
    # Con MARIA o JOSE compuestos, la CURP usa el segundo nombre
    nom = nombres[1] if len(nombres) > 1 and nombres[0] in ("MARIA", "JOSE") else nombres[0]
    ap1, ap2, nom = sin_acentos(ap1), sin_acentos(ap2), sin_acentos(nom)
    inicio = ap1[0] + primera_vocal_interna(ap1) + ap2[0] + nom[0]
    if inicio in PALABRAS_ALTISONANTES:
        inicio = inicio[0] + "X" + inicio[2:]
    homoclave = "A" if nacimiento.year >= 2000 else "0"
    curp17 = (inicio + nacimiento.strftime("%y%m%d") + ("M" if sexo == "Femenino" else "H") + estado +
              primera_consonante_interna(ap1) + primera_consonante_interna(ap2) + primera_consonante_interna(nom) +
              homoclave)
    return curp17 + digito_verificador(curp17)


def fecha_aleatoria(desde, hasta):
    return desde + timedelta(days=random.randint(0, (hasta - desde).days))


def sql(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def generar():
    alumnos, curps, matriculas = [], set(), set()
    while len(alumnos) < TOTAL_ALUMNOS:
        if not alumnos:
            a = dict(ALUMNA_DEMO)
        else:
            sexo = random.choice(["Femenino", "Masculino"])
            a = dict(nombre=random.choice(NOMBRES_M if sexo == "Femenino" else NOMBRES_H),
                     apaterno=random.choice(APELLIDOS), amaterno=random.choice(APELLIDOS), sexo=sexo,
                     fecha_nac=fecha_aleatoria(date(2004, 1, 1), date(2009, 12, 31)))
            a["curp"] = generar_curp(a["nombre"], a["apaterno"], a["amaterno"], a["fecha_nac"], sexo)
        if a["curp"] in curps:
            continue
        ingreso_anio = a["fecha_nac"].year + 15
        matricula = f"{str(ingreso_anio)[2:]}08080{random.randint(10000, 99999)}"
        if matricula in matriculas:
            continue
        curps.add(a["curp"]); matriculas.add(matricula)
        municipio = random.choice(MUNICIPIOS)
        a.update(
            id=len(alumnos) + 1,
            matricula=matricula,
            generacion=f"{ingreso_anio}-{ingreso_anio + 3}",
            fechaIngreso=date(ingreso_anio, 8, random.randint(20, 31)),
            email=f"alumno{len(alumnos) + 1:03d}@ejemplo.com",
            telefono=f"614555{random.randint(1000, 9999)}",   # 555: numeros ficticios
            escuela=f"TELEBACHILLERATO COMUNITARIO {random.randint(8000, 8999)}",
            municipio=municipio,
            localidad=municipio,
        )
        alumnos.append(a)

    archivos = []
    for a in alumnos[1:]:   # la alumna de la demo empieza sin documentos
        tipos = [t for t, p in (("CURP", .9), ("SEC", .8), ("ACTA", .75), ("FINAL", .25)) if random.random() < p]
        momento = datetime.combine(a["fechaIngreso"], datetime.min.time()) + timedelta(hours=9)
        for t in tipos:   # en orden CURP -> SEC -> ACTA -> FINAL, como se suben
            momento += timedelta(minutes=random.randint(1, 4), seconds=random.randint(0, 59))
            tipo = random.choices(list(VARIANTES[t]), weights=list(VARIANTES[t].values()))[0]
            archivos.append(dict(id=len(archivos) + 1, nombre=f"{a['id']}_{tipo.strip()}.pdf", tipoArchivo=tipo,
                                 descripcion=None, idAlumno=a["id"], fecha=momento))
    return alumnos, archivos


ESQUEMA = """-- Base de datos de PRUEBA (datos ficticios). Misma estructura que Control Escolar.
CREATE DATABASE IF NOT EXISTS controlescolar_prueba CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE controlescolar_prueba;

CREATE TABLE IF NOT EXISTS `alumnos` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(50) DEFAULT NULL,
  `apaterno` varchar(50) DEFAULT NULL,
  `amaterno` varchar(50) DEFAULT NULL,
  `sexo` varchar(20) DEFAULT NULL,
  `fecha_nac` date DEFAULT NULL,
  `matricula` varchar(45) DEFAULT NULL,
  `curp` varchar(45) DEFAULT NULL,
  `foto` varchar(100) DEFAULT NULL,
  `nss` varchar(100) DEFAULT NULL,
  `generacion` varchar(50) DEFAULT NULL,
  `fechaIngreso` date DEFAULT NULL,
  `email` varchar(80) DEFAULT NULL,
  `telefono` varchar(15) DEFAULT NULL,
  `escuela` varchar(150) DEFAULT NULL,
  `municipio` varchar(150) DEFAULT NULL,
  `localidad` varchar(150) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `matricula_UNIQUE` (`matricula`),
  UNIQUE KEY `curp_UNIQUE` (`curp`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `archivos` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(100) DEFAULT NULL,
  `tipoArchivo` varchar(20) DEFAULT NULL,
  `descripcion` varchar(100) DEFAULT NULL,
  `idAlumno` int(11) DEFAULT NULL,
  `fecha` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def escribir(alumnos, archivos):
    init = AQUI / "init"
    init.mkdir(exist_ok=True)
    (init / "01_esquema.sql").write_text(ESQUEMA, encoding="utf-8")
    cols_a = ["id", "nombre", "apaterno", "amaterno", "sexo", "fecha_nac", "matricula", "curp", "generacion",
              "fechaIngreso", "email", "telefono", "escuela", "municipio", "localidad"]
    cols_f = ["id", "nombre", "tipoArchivo", "descripcion", "idAlumno", "fecha"]
    lineas = ["-- Datos 100% FICTICIOS generados por db/generar_base_prueba.py", "USE controlescolar_prueba;", "",
              f"INSERT INTO alumnos ({', '.join(cols_a)}) VALUES"]
    lineas.append(",\n".join("(" + ", ".join(sql(a[c]) for c in cols_a) + ")" for a in alumnos) + ";")
    lineas += ["", f"INSERT INTO archivos ({', '.join(cols_f)}) VALUES"]
    lineas.append(",\n".join("(" + ", ".join(sql(f[c]) for c in cols_f) + ")" for f in archivos) + ";")
    (init / "02_datos.sql").write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    alumnos, archivos = generar()
    escribir(alumnos, archivos)
    print(f"{len(alumnos)} alumnos y {len(archivos)} archivos ficticios -> {AQUI / 'init'}")
    print("Alumna de la demo:", ALUMNA_DEMO["nombre"], ALUMNA_DEMO["apaterno"], ALUMNA_DEMO["amaterno"], ALUMNA_DEMO["curp"])
