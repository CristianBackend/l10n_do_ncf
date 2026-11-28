# -*- coding: utf-8 -*-
# Migracion 19.0.4.2.10
#
# - Secuencias NCF: recalcular los campos guardados que dependen de
#   current_number (porcentaje de uso, semaforo y estado). El numero se
#   escribe por SQL dentro del bloqueo de concurrencia y el ORM no se
#   enteraba, asi que en las bases que vienen de antes esos campos se quedaron
#   con el valor que tenian: el panel ensena 0 % y verde para siempre, el
#   filtro "Stock Bajo" no encuentra nada y una secuencia agotada sigue
#   figurando como activa. El arreglo esta en el codigo; esto pone al dia lo
#   que ya estaba guardado.
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['l10n_do_ncf.sequence']._l10n_do_recompute_current_number_fields()
