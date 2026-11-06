# -*- coding: utf-8 -*-
# Migración 19.0.3.4.0
#
# Las bases que ya tenían el módulo nunca pasaron por la configuración DGII
# deducible del plan contable l10n_do (impuestos por xmlid, ITBIS 0 %
# exportación, forma de pago de los diarios): post_init_hook solo corre al
# instalar. Aquí se aplica una vez; solo llena lo que esté vacío.
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    l10n_do_autoconfig.autoconfigure(env)
