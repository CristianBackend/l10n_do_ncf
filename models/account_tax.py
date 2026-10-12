# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountTax(models.Model):
    _inherit = 'account.tax'

    dgii_606_bucket = fields.Selection([
        ('itbis_retenido', 'ITBIS Retenido (606 col 12)'),
        ('itbis_percibido', 'ITBIS Percibido (606 col 16)'),
        ('isr_retenido', 'ISR Retenido (606 col 18)'),
        ('isr_percibido', 'ISR Percibido (606 col 19)'),
    ], string='Columna DGII 606')

    dgii_retention_type = fields.Selection([
        ('itbis', 'ITBIS'),
        ('isr', 'ISR'),
    ], string='Tipo Retención DGII')

    is_dgii_retention = fields.Boolean(
        string='Es Retención DGII',
        compute='_compute_is_dgii_retention',
        store=True
    )

    dgii_itbis_zero_type = fields.Selection([
        ('zero_rated', 'ITBIS 0 % (gravado a tasa cero)'),
        ('exempt', 'Exento de ITBIS'),
    ], string='Tipo ITBIS 0 %',
       help='Solo aplica a impuestos con tasa 0 %. Distingue una operación '
            'gravada a tasa cero de una exenta: en el e-CF son indicadores '
            'de facturación distintos (3 = ITBIS 0 %, 4 = Exento).')

    @api.depends('amount', 'dgii_606_bucket')
    def _compute_is_dgii_retention(self):
        for tax in self:
            tax.is_dgii_retention = tax.amount < 0 and tax.dgii_606_bucket
