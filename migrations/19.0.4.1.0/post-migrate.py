# -*- coding: utf-8 -*-
# Migración 19.0.4.1.0
#
# - El tipo de compra de un proveedor extranjero ya no es siempre "Pago al
#   exterior" (solo servicios sin ITBIS). Los borradores que ya existen
#   conservan el tipo que tienen: quedan como elegidos a mano.
# - Retención sugerida en el pago al exterior: el ISR 27 % de la plantilla
#   l10n_do, si la compañía no indicó otra (idempotente).
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE account_move
           SET l10n_do_purchase_kind_manual = TRUE
         WHERE move_type IN ('in_invoice', 'in_refund') AND state = 'draft'
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    l10n_do_autoconfig.autoconfigure(env)
