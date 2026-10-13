# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/chart_template.py
# Descripción: Datos demo de contabilidad en compañías dominicanas
# Compatibilidad: Odoo 19

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _post_load_demo_data(self, company=False):
        """Preparar las facturas demo antes de que Odoo las confirme.

        Odoo carga las facturas demo en _install_demo y las confirma aquí. En
        una compañía dominicana cada una necesita un NCF, y una base demo no
        tiene secuencias: sin esto todas fallan con "Error while posting demo
        data". Solo se ejecuta al cargar datos demo; nunca en una base real.
        """
        company = company or self.env.company
        if company.country_id.code != 'DO':
            return super()._post_load_demo_data(company)

        refunds = self._l10n_do_prepare_demo_moves(company)
        result = super()._post_load_demo_data(company)

        # El NCF de la factura origen no existía hasta confirmarla
        for refund in refunds:
            origin = refund.l10n_do_origin_move_id
            if not refund.l10n_do_ncf_origin and origin.l10n_do_ncf_number:
                refund.l10n_do_ncf_origin = origin.l10n_do_ncf_number
        return result

    def _l10n_do_prepare_demo_moves(self, company):
        """Secuencias NCF demo y origen de las notas de crédito demo.

        Devuelve las notas de crédito a las que se les asignó factura origen.
        """
        drafts = self.env['account.move'].sudo().with_company(company).search([
            ('company_id', '=', company.id),
            ('state', '=', 'draft'),
            ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
        ])

        # Solo los tipos que estas facturas van a usar
        numbered = drafts.filtered(lambda m: (
            m.move_type in ('out_invoice', 'out_refund') and m.l10n_do_ncf_required
        ) or (
            m.move_type in ('in_invoice', 'in_refund')
            and m.l10n_do_fiscal_type in ('informal', 'minor_expense')
        ))
        sequences = self.env['l10n_do_ncf.sequence']._create_demo_sequences(
            company, numbered.l10n_do_ncf_type_id,
        )
        if sequences:
            _logger.info(
                'l10n_do_ncf: secuencias NCF demo creadas para %s: %s',
                company.name, ', '.join(sequences.mapped('prefix')),
            )

        # Las notas de crédito demo no traen factura origen ni motivo, y sin
        # ellos no se pueden confirmar. Se enlazan a una factura demo del
        # mismo cliente.
        invoices = drafts.filtered(
            lambda m: m.move_type == 'out_invoice' and not m.l10n_do_is_debit_note
        )
        used = self.env['account.move']
        prepared = self.env['account.move']
        for refund in drafts.filtered(lambda m: m.move_type == 'out_refund'):
            if refund.l10n_do_ncf_origin or refund.l10n_do_origin_move_id:
                continue
            candidates = invoices.filtered(
                lambda m: m.commercial_partner_id == refund.commercial_partner_id
            )
            origin = (candidates - used)[:1] or candidates[:1]
            if not origin:
                continue
            used |= origin
            refund.write({
                'l10n_do_origin_move_id': origin.id,
                'l10n_do_credit_note_reason': refund.l10n_do_credit_note_reason or '03',
            })
            prepared |= refund
        return prepared
