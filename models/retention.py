# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/retention.py
# Versión: 19.0.2.1.0 - Con buckets DGII 606

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class L10nDoRetentionType(models.Model):
    """
    Tipos de Retención RD con clasificación DGII 606

    IMPORTANTE: El campo dgii_606_bucket determina en qué columna
    del 606 aparece cada retención.
    """
    _name = 'l10n_do_ncf.retention.type'
    _description = 'Tipos de Retención RD'
    _order = 'sequence, code'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', required=True)
    sequence = fields.Integer(string='Secuencia', default=10)

    # Tipo base (ISR o ITBIS)
    retention_type = fields.Selection([
        ('isr', 'ISR - Impuesto Sobre la Renta'),
        ('itbis', 'ITBIS'),
    ], string='Tipo de Impuesto', required=True)

    # Bucket específico para 606
    dgii_606_bucket = fields.Selection([
        ('itbis_retenido', 'ITBIS Retenido (col 12)'),
        ('itbis_percibido', 'ITBIS Percibido (col 16)'),
        ('isr_retenido', 'ISR Retenido (col 18)'),
        ('isr_percibido', 'ISR Percibido (col 19)'),
    ], string='Columna 606',
       required=True,
       help='Determina en qué columna del 606 se reporta esta retención')

    rate = fields.Float(
        string='Tasa (%)',
        required=True,
        help='Porcentaje de retención. Ej: 10 para 10%, 100 para 100%'
    )

    # Tasa normalizada para cálculos
    rate_decimal = fields.Float(
        string='Tasa Decimal',
        compute='_compute_rate_decimal',
        store=True,
        help='Tasa en formato decimal (10% = 0.10)'
    )

    apply_on = fields.Selection([
        ('base', 'Sobre monto base (sin ITBIS)'),
        ('itbis', 'Sobre el ITBIS facturado'),
        ('total', 'Sobre el total'),
    ], string='Aplicar sobre', default='base', required=True)

    partner_type = fields.Selection([
        ('all', 'Todos'),
        ('person', 'Solo Personas Físicas'),
        ('company', 'Solo Empresas'),
    ], string='Aplica a', default='all')

    # Para B11/B13 específico
    for_informal = fields.Boolean(
        string='Para Compra Informal (B11)',
        default=False
    )

    for_minor_expense = fields.Boolean(
        string='Para Gasto Menor (B13)',
        default=False
    )

    is_perceived = fields.Boolean(
        string='Es Percepción',
        default=False,
        help='Marcar si es una percepción (el proveedor nos retiene) en lugar de retención (nosotros retenemos)'
    )
    description = fields.Text(string='Descripción/Base Legal')
    active = fields.Boolean(default=True)

    @api.depends('rate')
    def _compute_rate_decimal(self):
        for rec in self:
            rec.rate_decimal = rec.rate / 100.0 if rec.rate else 0.0

    @api.constrains('code')
    def _check_code_unique(self):
        for record in self:
            existing = self.search([
                ('code', '=', record.code),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(_('El código de retención debe ser único'))

    @api.onchange('retention_type')
    def _onchange_retention_type(self):
        """Auto-asignar bucket por defecto"""
        if self.retention_type == 'itbis':
            self.dgii_606_bucket = 'itbis_retenido'
        elif self.retention_type == 'isr':
            self.dgii_606_bucket = 'isr_retenido'


class AccountMoveRetention(models.Model):
    """
    Líneas de retención por factura
    """
    _name = 'l10n_do_ncf.move.retention'
    _description = 'Retenciones de Factura'

    move_id = fields.Many2one(
        'account.move',
        string='Factura',
        required=True,
        ondelete='cascade'
    )

    retention_type_id = fields.Many2one(
        'l10n_do_ncf.retention.type',
        string='Tipo de Retención',
        required=True
    )

    # Monto sobre el que se aplica
    base_amount = fields.Monetary(
        string='Monto Base',
        currency_field='currency_id',
        help='Monto sobre el que se calcula la retención'
    )

    # Rate viene del tipo
    rate = fields.Float(
        string='Tasa (%)',
        related='retention_type_id.rate',
        store=True
    )

    # Monto retenido calculado
    retention_amount = fields.Monetary(
        string='Monto Retenido',
        compute='_compute_retention_amount',
        store=True,
        currency_field='currency_id'
    )

    # Para reporting
    dgii_606_bucket = fields.Selection(
        related='retention_type_id.dgii_606_bucket',
        store=True,
        string='Columna 606'
    )

    currency_id = fields.Many2one('res.currency', related='move_id.currency_id')
    company_id = fields.Many2one('res.company', related='move_id.company_id')
    is_manual = fields.Boolean(
        string='Manual',
        default=False,
        help='Marcar si esta retención fue ajustada manualmente por el contador'
    )
    @api.depends('base_amount', 'rate')
    def _compute_retention_amount(self):
        for rec in self:
            # rate viene como porcentaje (10, 30, 100)
            # convertir a decimal para cálculo
            rec.retention_amount = rec.base_amount * (rec.rate / 100.0) if rec.rate else 0.0


class RetentionWizard(models.TransientModel):
    """
    Wizard para agregar retenciones manualmente
    """
    _name = 'l10n_do_ncf.retention.wizard'
    _description = 'Wizard Agregar Retención'

    move_id = fields.Many2one('account.move', string='Factura', required=True)
    retention_type_id = fields.Many2one(
        'l10n_do_ncf.retention.type',
        string='Tipo de Retención',
        required=True
    )

    base_amount = fields.Float(string='Monto Base Factura')
    itbis_amount = fields.Float(string='ITBIS Factura')

    apply_on = fields.Selection(related='retention_type_id.apply_on')
    rate = fields.Float(related='retention_type_id.rate')

    amount_to_retain = fields.Float(
        string='Monto a Aplicar',
        compute='_compute_amount_to_retain'
    )
    retention_amount = fields.Float(
        string='Retención Calculada',
        compute='_compute_retention_amount'
    )

    @api.depends('retention_type_id', 'base_amount', 'itbis_amount')
    def _compute_amount_to_retain(self):
        for rec in self:
            if rec.retention_type_id:
                if rec.retention_type_id.apply_on == 'base':
                    rec.amount_to_retain = rec.base_amount
                elif rec.retention_type_id.apply_on == 'itbis':
                    rec.amount_to_retain = rec.itbis_amount
                else:
                    rec.amount_to_retain = rec.base_amount + rec.itbis_amount
            else:
                rec.amount_to_retain = 0

    @api.depends('amount_to_retain', 'rate')
    def _compute_retention_amount(self):
        for rec in self:
            rec.retention_amount = rec.amount_to_retain * (rec.rate / 100.0) if rec.rate else 0.0

    def action_add(self):
        """Agregar la retención a la factura"""
        self.ensure_one()

        self.env['l10n_do_ncf.move.retention'].create({
            'move_id': self.move_id.id,
            'retention_type_id': self.retention_type_id.id,
            'base_amount': self.amount_to_retain,
        })

        return {'type': 'ir.actions.act_window_close'}