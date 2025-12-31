# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/registro_unico.py
# Descripción: B12 - Registro Único de Ingresos
# Versión: 19.0.3.0.0 - Corregido para Odoo 19

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, timedelta
import logging

_logger = logging.getLogger(__name__)


class L10nDoRegistroUnico(models.Model):
    """
    B12 - Registro Único de Ingresos
    
    Consolida ventas diarias de bajo monto (retail, colmados, etc.)
    en un solo comprobante fiscal por día.
    """
    _name = 'l10n_do_ncf.registro.unico'
    _description = 'B12 - Registro Único de Ingresos'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Número',
        readonly=True,
        copy=False,
        default='Nuevo'
    )

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )

    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )

    # NCF B12
    l10n_do_ncf_number = fields.Char(
        string='NCF B12',
        readonly=True,
        copy=False,
        tracking=True
    )

    l10n_do_ncf_seq_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia',
        readonly=True
    )

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmado'),
        ('posted', 'Publicado'),
        ('cancelled', 'Cancelado'),
    ], string='Estado', default='draft', tracking=True)

    # Totales
    total_transactions = fields.Integer(
        string='Cantidad Transacciones',
        compute='_compute_totals',
        store=True
    )

    amount_untaxed = fields.Monetary(
        string='Base Imponible',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    amount_tax = fields.Monetary(
        string='ITBIS',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    amount_total = fields.Monetary(
        string='Total',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    amount_cash = fields.Monetary(
        string='Efectivo',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    amount_card = fields.Monetary(
        string='Tarjeta',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    amount_other = fields.Monetary(
        string='Otros Pagos',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        store=True
    )

    # Líneas de detalle
    line_ids = fields.One2many(
        'l10n_do_ncf.registro.unico.line',
        'registro_id',
        string='Transacciones'
    )

    # Órdenes POS relacionadas
    pos_order_ids = fields.One2many(
        'pos.order',
        'l10n_do_registro_unico_id',
        string='Órdenes POS'
    )

    # Para 607
    l10n_do_reported_607 = fields.Boolean(
        string='Reportado en 607',
        default=False,
        tracking=True
    )

    notes = fields.Text(string='Notas')

    # Constraint usando el método Odoo 19
    @api.constrains('date', 'company_id')
    def _check_unique_date_company(self):
        for record in self:
            existing = self.search([
                ('id', '!=', record.id),
                ('date', '=', record.date),
                ('company_id', '=', record.company_id.id),
                ('state', '!=', 'cancelled'),
            ])
            if existing:
                raise ValidationError(_(
                    'Ya existe un Registro Único (B12) para la fecha %s en esta compañía.'
                ) % record.date)

    @api.depends('line_ids', 'line_ids.amount_total', 'line_ids.amount_tax',
                 'line_ids.payment_method')
    def _compute_totals(self):
        for record in self:
            lines = record.line_ids
            record.total_transactions = len(lines)
            record.amount_tax = sum(lines.mapped('amount_tax'))
            record.amount_untaxed = sum(lines.mapped('amount_untaxed'))
            record.amount_total = sum(lines.mapped('amount_total'))
            record.amount_cash = sum(lines.filtered(
                lambda l: l.payment_method == 'cash').mapped('amount_total'))
            record.amount_card = sum(lines.filtered(
                lambda l: l.payment_method == 'card').mapped('amount_total'))
            record.amount_other = sum(lines.filtered(
                lambda l: l.payment_method not in ('cash', 'card')).mapped('amount_total'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_do_ncf.registro.unico') or 'Nuevo'
        return super().create(vals_list)

    def action_confirm(self):
        """Confirmar registro"""
        for record in self:
            if not record.line_ids:
                raise UserError(_('Debe agregar al menos una transacción.'))
            record.state = 'confirmed'

    def action_post(self):
        """Publicar y generar NCF B12"""
        for record in self:
            if record.state != 'confirmed':
                raise UserError(_('Debe confirmar primero.'))

            # Generar NCF B12
            record._generate_b12_ncf()
            record.state = 'posted'

    def action_cancel(self):
        """Cancelar registro"""
        for record in self:
            if record.l10n_do_reported_607:
                raise UserError(_('No puede cancelar un B12 ya reportado en 607.'))
            record.state = 'cancelled'

    def action_draft(self):
        """Volver a borrador"""
        for record in self:
            if record.state == 'cancelled':
                record.state = 'draft'

    def _generate_b12_ncf(self):
        """Generar NCF tipo B12"""
        self.ensure_one()

        if self.l10n_do_ncf_number:
            return

        NcfType = self.env['l10n_do_ncf.type']
        ncf_type = NcfType.search([('code', '=', '12')], limit=1)

        if not ncf_type:
            raise UserError(_('No existe tipo NCF B12. Configure en NCF → Tipos.'))

        sequence = self.env['l10n_do_ncf.sequence'].search([
            ('ncf_type_id', '=', ncf_type.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'active'),
        ], limit=1)

        if not sequence:
            raise UserError(_('No hay secuencia activa para B12.'))

        if sequence.current_number > sequence.final_number:
            raise UserError(_('Secuencia B12 agotada.'))

        prefix = ncf_type.prefix  # B12
        ncf = '%s%08d' % (prefix, sequence.current_number)

        self.write({
            'l10n_do_ncf_number': ncf,
            'l10n_do_ncf_seq_id': sequence.id,
        })

        sequence.sudo().write({'current_number': sequence.current_number + 1})
        _logger.info('B12 NCF generado: %s | Fecha: %s', ncf, self.date)

    def _get_607_line_data(self):
        """Datos para línea 607"""
        self.ensure_one()
        return {
            'rnc_cedula': '',  # B12 no tiene RNC cliente
            'tipo_id': '',
            'ncf': self.l10n_do_ncf_number or '',
            'ncf_modificado': '',
            'fecha_comprobante': self.date,
            'itbis_facturado': self.amount_tax,
            'monto_facturado': self.amount_total,
            'forma_pago': self._get_forma_pago_607(),
            'cantidad_transacciones': self.total_transactions,
        }

    def _get_forma_pago_607(self):
        """Determinar forma de pago predominante"""
        if self.amount_cash >= self.amount_card and self.amount_cash >= self.amount_other:
            return '01'  # Efectivo
        elif self.amount_card >= self.amount_other:
            return '03'  # Tarjeta
        return '07'  # Mixto

    @api.model
    def get_or_create_for_date(self, date_val, company_id=None):
        """Obtener o crear registro único para una fecha."""
        company_id = company_id or self.env.company.id
        
        registro = self.search([
            ('date', '=', date_val),
            ('company_id', '=', company_id),
            ('state', '!=', 'cancelled'),
        ], limit=1)

        if not registro:
            registro = self.create({
                'date': date_val,
                'company_id': company_id,
            })

        return registro

    @api.model
    def consolidate_pos_orders(self, date_from=None, date_to=None):
        """Consolidar órdenes POS en registros únicos."""
        date_from = date_from or date.today()
        date_to = date_to or date.today()

        PosOrder = self.env['pos.order']
        
        orders = PosOrder.search([
            ('date_order', '>=', date_from),
            ('date_order', '<=', date_to),
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('l10n_do_registro_unico_id', '=', False),
            ('l10n_do_use_b12', '=', True),
        ])

        if not orders:
            return {'created': 0, 'orders_processed': 0}

        grouped = {}
        for order in orders:
            key = (order.date_order.date(), order.company_id.id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(order)

        created = 0
        processed = 0

        for (order_date, company_id), order_list in grouped.items():
            registro = self.get_or_create_for_date(order_date, company_id)
            
            if registro.state == 'posted':
                _logger.warning('B12 %s ya publicado, saltando órdenes', registro.name)
                continue

            for order in order_list:
                self.env['l10n_do_ncf.registro.unico.line'].create({
                    'registro_id': registro.id,
                    'pos_order_id': order.id,
                    'reference': order.pos_reference or order.name,
                    'amount_untaxed': order.amount_total - order.amount_tax,
                    'amount_tax': order.amount_tax,
                    'amount_total': order.amount_total,
                    'payment_method': order._get_payment_method_type(),
                    'date_time': order.date_order,
                })
                
                order.l10n_do_registro_unico_id = registro.id
                processed += 1

            if registro.id not in [r.id for r in self.browse([])]:
                created += 1

        return {'created': created, 'orders_processed': processed}


class L10nDoRegistroUnicoLine(models.Model):
    """Líneas de detalle del Registro Único"""
    _name = 'l10n_do_ncf.registro.unico.line'
    _description = 'Línea de Registro Único B12'
    _order = 'date_time desc'

    registro_id = fields.Many2one(
        'l10n_do_ncf.registro.unico',
        string='Registro Único',
        required=True,
        ondelete='cascade'
    )

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Orden POS'
    )

    reference = fields.Char(string='Referencia')
    
    date_time = fields.Datetime(
        string='Fecha/Hora',
        default=fields.Datetime.now
    )

    amount_untaxed = fields.Monetary(
        string='Base',
        currency_field='currency_id'
    )

    amount_tax = fields.Monetary(
        string='ITBIS',
        currency_field='currency_id'
    )

    amount_total = fields.Monetary(
        string='Total',
        currency_field='currency_id'
    )

    payment_method = fields.Selection([
        ('cash', 'Efectivo'),
        ('card', 'Tarjeta'),
        ('transfer', 'Transferencia'),
        ('other', 'Otro'),
    ], string='Método Pago', default='cash')

    currency_id = fields.Many2one(
        'res.currency',
        related='registro_id.currency_id'
    )

    notes = fields.Char(string='Notas')


class PosOrderB12(models.Model):
    """Extensión POS para B12"""
    _inherit = 'pos.order'

    l10n_do_registro_unico_id = fields.Many2one(
        'l10n_do_ncf.registro.unico',
        string='Registro Único B12',
        readonly=True
    )

    l10n_do_use_b12 = fields.Boolean(
        string='Usar B12',
        default=True,
        help='Si está activo, esta venta se consolida en B12'
    )

    def _get_payment_method_type(self):
        """Determinar tipo de pago para B12"""
        self.ensure_one()
        payments = self.payment_ids
        
        cash_amount = sum(payments.filtered(
            lambda p: p.payment_method_id.is_cash_count).mapped('amount'))
        total = sum(payments.mapped('amount'))
        
        if cash_amount >= total * 0.5:
            return 'cash'
        elif any(p.payment_method_id.use_payment_terminal for p in payments):
            return 'card'
        return 'other'