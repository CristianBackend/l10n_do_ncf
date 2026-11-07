# -*- coding: utf-8 -*-
# Migración 19.0.3.5.0
#
# Tipo 606 de las cuentas del plan l10n_do cuya categoría es clara
# (l10n_do_autoconfig.ACCOUNT_TEMPLATE_606; tabla completa y motivos en
# docs/mapeo_cuentas_606.md). Repite toda la configuración deducible, que es
# idempotente y solo llena lo vacío.
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    l10n_do_autoconfig.autoconfigure(env)
