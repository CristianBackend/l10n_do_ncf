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

    @api.depends('amount', 'dgii_606_bucket')
    def _compute_is_dgii_retention(self):
        for tax in self:
            tax.is_dgii_retention = tax.amount < 0 and tax.dgii_606_bucket


def configure_dgii_retention_taxes(env):
    """Configurar automáticamente los impuestos de retención DGII"""
    # ITBIS retenciones
    itbis_taxes = env['account.tax'].search([
        ('amount', '<', 0),
        '|', ('name', 'ilike', 'ITBIS'), ('name', 'ilike', 'itbis')
    ])
    itbis_taxes.write({
        'dgii_retention_type': 'itbis',
        'dgii_606_bucket': 'itbis_retenido'
    })
    
    # ISR retenciones
    isr_taxes = env['account.tax'].search([
        ('amount', '<', 0),
        '|', ('name', 'ilike', 'ISR'), ('name', 'ilike', 'isr')
    ])
    isr_taxes.write({
        'dgii_retention_type': 'isr',
        'dgii_606_bucket': 'isr_retenido'
    })
