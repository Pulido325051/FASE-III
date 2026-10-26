-- Base de datos de PRUEBA (datos ficticios). Misma estructura que Control Escolar.
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
