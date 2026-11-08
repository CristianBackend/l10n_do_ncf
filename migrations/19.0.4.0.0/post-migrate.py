# -*- coding: utf-8 -*-
# Migración 19.0.4.0.0: una sola fuente de verdad para las retenciones de
# compras, los impuestos de retención de las líneas (los que generan asiento).
#
# - Las facturas de proveedor ya confirmadas (o anuladas) con filas en la
#   pestaña "Retenciones" quedan como "anteriores": sus reportes conservan lo
#   que tenía la pestaña. Su asiento no se toca.
# - Los borradores con filas escritas a mano pasan a impuesto de línea solo si
#   el tipo de retención tiene su impuesto equivalente indicado y el monto da
#   igual; si no, la factura sigue avisando y no se confirma hasta corregirla.
# - Configuración deducible (idempotente): el tipo 606 de ISR de los impuestos
#   de la plantilla l10n_do donde es inequívoco. No se crean impuestos.
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE account_move m
           SET l10n_do_retention_legacy = TRUE
         WHERE m.move_type IN ('in_invoice', 'in_refund')
           AND m.state IN ('posted', 'cancel')
           AND EXISTS (SELECT 1 FROM l10n_do_ncf_move_retention r WHERE r.move_id = m.id)
    """)
    _logger.info('l10n_do_ncf: %s facturas de proveedor con retenciones anteriores', cr.rowcount)
    env = api.Environment(cr, SUPERUSER_ID, {})
    l10n_do_autoconfig.autoconfigure(env)
    # Los borradores (no anteriores) recalculan sus columnas de retención
    # desde los impuestos de las líneas.
    Move = env['account.move']
    drafts = Move.search([('move_type', 'in', ('in_invoice', 'in_refund')),
                          ('state', '=', 'draft'), ('l10n_do_retention_legacy', '=', False)])
    for name in ('l10n_do_itbis_retenido', 'l10n_do_itbis_percibido', 'l10n_do_isr_retenido',
                 'l10n_do_isr_percibido', 'l10n_do_total_isr_retention',
                 'l10n_do_total_itbis_retention', 'l10n_do_gross_total', 'l10n_do_amount_to_pay'):
        env.add_to_compute(Move._fields[name], drafts)
    drafts.flush_recordset()
    converted = Move._l10n_do_convert_tab_retentions()
    _logger.info('l10n_do_ncf: %s borradores con retenciones pasados a impuesto de línea',
                 len(converted))
