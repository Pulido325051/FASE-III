"""Acceso a MySQL (WAMP).

- La tabla de alumnos SOLO se lee.
- En la tabla de archivos solo se inserta / actualiza el registro del documento.
- Todas las consultas usan parametros (%s): nunca se concatena texto del usuario.
"""

import difflib
import re
from dataclasses import dataclass

import pymysql


def categoria_de_tipo(texto):
    """Interpreta un tipoArchivo capturado a mano ("ACT NAC", "CERT. SEC", "CUPR"...)
    y regresa la categoria del modelo, o None si es otro tipo (NSS, DUPLICADO, FICHA...)."""
    t = re.sub(r"[^A-Z ]", " ", (texto or "").upper())
    t = re.sub(r"\s+", " ", t).strip()
    palabras = t.split()
    if not palabras or re.search(r"DUPLICAD|CUPLICAD|DUPICAD|CANCELAD|COPIA|HIST|FICHA|NSS|NUM S|REV", t):
        return None
    if re.search(r"EQUIV|EQUI", t):
        return "Equivalencia"
    if any(difflib.SequenceMatcher(None, p, "CURP").ratio() >= 0.75 for p in palabras):
        return "CURP"
    if re.search(r"SEC|SC$|SECU", t):
        return "Certificados Secundaria"
    if re.search(r"PAR|PACIAL", t):
        return "Certificado Parcial"
    if re.search(r"F\s?I*\s?N|FNAL|FIANL", t):
        return "Certificado Final"
    if re.search(r"N\s?A\s?C|NACIM|MAC|ANC|ANACIM|ACT", t):
        return "Actas de nacimiento"
    return None


@dataclass
class Alumno:
    id: int
    nombre: str
    apaterno: str
    amaterno: str
    curp: str
    matricula: str
    generacion: str
    escuela: str

    @property
    def nombre_completo(self):
        return " ".join(p for p in (self.nombre, self.apaterno, self.amaterno) if p)


@dataclass
class ArchivoRegistrado:
    id: int
    nombre: str
    tipo: str
    fecha: object


class ErrorBaseDatos(Exception):
    pass


class BaseDatos:

    COLUMNAS_ALUMNO = "id, nombre, apaterno, amaterno, curp, matricula, generacion, escuela"

    def __init__(self, config):
        self.config = config
        self.t_alumnos = f"`{config.tabla_alumnos}`"
        self.t_archivos = f"`{config.tabla_archivos}`"

    def _conectar(self):
        # Una conexion por operacion: si se cae la red, la siguiente operacion reconecta
        try:
            return pymysql.connect(
                host=self.config.mysql_host,
                port=self.config.mysql_puerto,
                user=self.config.mysql_usuario,
                password=self.config.mysql_contrasena,
                database=self.config.mysql_base,
                charset="utf8mb4",
                connect_timeout=8,
                read_timeout=30,
                write_timeout=30,
                autocommit=False,
            )
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"No se pudo conectar a MySQL ({self.config.mysql_host}): {e}") from e

    @staticmethod
    def _a_alumno(fila):
        return Alumno(*[("" if v is None else v) for v in fila])

    def probar_conexion(self):
        con = self._conectar()
        try:
            with con.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self.t_alumnos}")
                total = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {self.t_archivos}")
                return total, cur.fetchone()[0]
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"Error al consultar las tablas: {e}") from e
        finally:
            con.close()

    def alumno_por_id(self, id_alumno):
        con = self._conectar()
        try:
            with con.cursor() as cur:
                cur.execute(f"SELECT {self.COLUMNAS_ALUMNO} FROM {self.t_alumnos} WHERE id = %s", (id_alumno,))
                fila = cur.fetchone()
                return self._a_alumno(fila) if fila else None
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"Error al buscar el alumno: {e}") from e
        finally:
            con.close()

    def buscar_por_curp(self, curp):
        con = self._conectar()
        try:
            with con.cursor() as cur:
                cur.execute(
                    f"SELECT {self.COLUMNAS_ALUMNO} FROM {self.t_alumnos} "
                    f"WHERE UPPER(TRIM(curp)) = %s",
                    (curp.strip().upper(),),
                )
                return [self._a_alumno(f) for f in cur.fetchall()]
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"Error al buscar la CURP: {e}") from e
        finally:
            con.close()

    def buscar_por_nombre(self, texto, limite=50):
        palabras = [p for p in texto.upper().split() if len(p) >= 2][:6]
        if not palabras:
            return []
        # Cada palabra debe aparecer en nombre + apellidos (en cualquier orden)
        condiciones = " AND ".join(
            ["UPPER(CONCAT_WS(' ', nombre, apaterno, amaterno)) LIKE %s"] * len(palabras)
        )
        parametros = [f"%{p}%" for p in palabras] + [limite]
        con = self._conectar()
        try:
            with con.cursor() as cur:
                cur.execute(
                    f"SELECT {self.COLUMNAS_ALUMNO} FROM {self.t_alumnos} "
                    f"WHERE {condiciones} ORDER BY apaterno, amaterno, nombre LIMIT %s",
                    parametros,
                )
                return [self._a_alumno(f) for f in cur.fetchall()]
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"Error al buscar por nombre: {e}") from e
        finally:
            con.close()

    def buscar_alumnos(self, texto, limite=50):
        """Busqueda general: CURP (18 caracteres), matricula/id (solo numeros) o nombre."""
        texto = texto.strip()
        compacto = texto.replace(" ", "").upper()
        if len(compacto) == 18 and compacto.isalnum() and not compacto.isdigit():
            return self.buscar_por_curp(compacto)
        if compacto.isdigit():
            con = self._conectar()
            try:
                with con.cursor() as cur:
                    cur.execute(
                        f"SELECT {self.COLUMNAS_ALUMNO} FROM {self.t_alumnos} "
                        f"WHERE TRIM(matricula) = %s OR id = %s LIMIT %s",
                        (compacto, int(compacto), limite),
                    )
                    return [self._a_alumno(f) for f in cur.fetchall()]
            except pymysql.MySQLError as e:
                raise ErrorBaseDatos(f"Error al buscar por matricula: {e}") from e
            finally:
                con.close()
        return self.buscar_por_nombre(texto, limite)

    def archivos_del_alumno(self, id_alumno, categoria=None):
        """Archivos registrados del alumno. Con 'categoria' filtra por tipo de documento
        reconociendo las variantes capturadas a mano ("ACT NAC" = "ACTA DE NAC")."""
        con = self._conectar()
        try:
            with con.cursor() as cur:
                cur.execute(
                    f"SELECT id, nombre, tipoArchivo, fecha FROM {self.t_archivos} "
                    f"WHERE idAlumno = %s ORDER BY fecha, id",
                    (id_alumno,),
                )
                archivos = [ArchivoRegistrado(*f) for f in cur.fetchall()]
            if categoria is not None:
                archivos = [a for a in archivos if categoria_de_tipo(a.tipo) == categoria]
            return archivos
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"Error al consultar los archivos del alumno: {e}") from e
        finally:
            con.close()

    def contar_referencias(self, nombre_archivo):
        """Cuantos registros apuntan a ese mismo archivo (para no mover un PDF que otro registro usa)."""
        con = self._conectar()
        try:
            with con.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self.t_archivos} WHERE nombre = %s", (nombre_archivo,))
                return cur.fetchone()[0]
        except pymysql.MySQLError as e:
            raise ErrorBaseDatos(f"Error al consultar el archivo: {e}") from e
        finally:
            con.close()

    def eliminar_archivo(self, id_archivo, id_alumno):
        """Borra UN registro de la tabla de archivos (solo si pertenece a ese alumno)."""
        con = self._conectar()
        try:
            with con.cursor() as cur:
                borrados = cur.execute(
                    f"DELETE FROM {self.t_archivos} WHERE id = %s AND idAlumno = %s LIMIT 1",
                    (id_archivo, id_alumno),
                )
            if borrados != 1:
                con.rollback()
                raise ErrorBaseDatos("El registro ya no existe o no pertenece a este alumno.")
            con.commit()
        except pymysql.MySQLError as e:
            con.rollback()
            raise ErrorBaseDatos(f"Error al eliminar el registro: {e}") from e
        finally:
            con.close()

    def registrar_archivo(self, id_alumno, nombre_archivo, tipo, descripcion, reemplazar_id=None):
        """Inserta el registro (o actualiza el indicado en reemplazar_id). Regresa el id."""
        con = self._conectar()
        try:
            with con.cursor() as cur:
                if reemplazar_id is None:
                    cur.execute(
                        f"INSERT INTO {self.t_archivos} (nombre, tipoArchivo, descripcion, idAlumno, fecha) "
                        f"VALUES (%s, %s, %s, %s, NOW())",
                        (nombre_archivo, tipo, descripcion, id_alumno),
                    )
                    nuevo_id = cur.lastrowid
                else:
                    cur.execute(
                        f"UPDATE {self.t_archivos} SET nombre = %s, descripcion = %s, fecha = NOW() "
                        f"WHERE id = %s AND idAlumno = %s",
                        (nombre_archivo, descripcion, reemplazar_id, id_alumno),
                    )
                    nuevo_id = reemplazar_id
            con.commit()
            return nuevo_id
        except pymysql.MySQLError as e:
            con.rollback()
            raise ErrorBaseDatos(f"Error al registrar el archivo: {e}") from e
        finally:
            con.close()
