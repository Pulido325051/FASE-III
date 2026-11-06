"""Configuracion de las pruebas.

docker-compose define las contrasenas de los 3 usuarios de la demo (CLAVE_*). Las pruebas normales
trabajan con la web ABIERTA (sin login); las pruebas de roles activan los usuarios a proposito
(ver test_roles.py). Por eso aqui se quitan esas variables ANTES de que se importe la aplicacion.
"""

import os

for rol in ("ADMINISTRADOR", "OPERADOR", "CONSULTOR"):
    os.environ.pop(f"CLAVE_{rol}", None)
