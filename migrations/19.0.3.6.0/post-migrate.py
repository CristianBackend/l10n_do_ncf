# -*- coding: utf-8 -*-
# Migración 19.0.3.6.0
#
# Contacto "Gastos menores" de cada compañía dominicana (facturas de proveedor
# E43/B13). Repite la configuración deducible, que es idempotente.
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    l10n_do_autoconfig.autoconfigure(env)
