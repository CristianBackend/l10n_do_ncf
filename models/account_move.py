# -*- coding: utf-8 -*-
# modulo: l10n_do_ncf
# Archivo: models/account_move.py
# Versión: 19.0.3.0.0 - CASOS DE USO COMPLETOS - CORREGIDO
# Compatibilidad: Odoo 19

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, timedelta
import re
import logging

_logger = logging.getLogger(__name__)

# =========================================
# PATRONES Y CONSTANTES
# =========================================
NCF_PATTERN = r'^B(01|02|03|04|11|12|13|14|15|16|17)\d{8}$'
ECF_PATTERN = r'^E(31|32|33|34|41|42|43|44|45|46|47)\d{10}$'
NCF_FULL_PATTERN = r'^(B(01|02|03|04|11|12|13|14|15|16|17)\d{8}|E(31|32|33|34|41|42|43|44|45|46|47)\d{10})$'


class AccountMove(models.Model):
    _inherit = 'account.move'

    # =========================================
    # NCF ÚNICO
    # =========================================

    l10n_do_ncf_number = fields.Char(
        string='NCF', copy=False, readonly=True, tracking=True, index=True,
    )

    l10n_do_ncf_type_id = fields.Many2one(
        'l10n_do_ncf.type', string='Tipo NCF', tracking=True,
        compute='_compute_l10n_do_ncf_type_id', store=True, readonly=False,
    )

    l10n_do_ncf_seq_id = fields.Many2one(
        'l10n_do_ncf.sequence', string='Secuencia', readonly=True, copy=False,
    )

    l10n_do_ncf_expiration = fields.Date(related='l10n_do_ncf_seq_id.expiration_date', store=True)

    # =========================================
    # ESTADO FISCAL EXTENDIDO
    # =========================================

    l10n_do_fiscal_status = fields.Selection([
        ('draft', 'Borrador'),
        ('pending', 'Pendiente'),
        ('valid', 'Válido'),
        ('partial_credit', 'Parcialmente Acreditado'),
        ('annulled', 'Anulado'),
        ('credited', 'Con NC Total'),
        ('debited', 'Con ND'),
        ('rejected', 'Rechazado DGII'),
        ('error_reported', 'Error Reportado'),
    ], string='Estado Fiscal', default='draft', tracking=True)

    # Control de reporte DGII
    l10n_do_reported_606 = fields.Boolean(
        string='Reportado 606', default=False, tracking=True,
        help='Indica si este documento ya fue incluido en un reporte 606 enviado a DGII'
    )
    l10n_do_reported_607 = fields.Boolean(
        string='Reportado 607', default=False, tracking=True,
        help='Indica si este documento ya fue incluido en un reporte 607 enviado a DGII'
    )
    l10n_do_report_period = fields.Char(
        string='Período Reportado',
        help='Período fiscal en que se reportó (YYYYMM)'
    )

    # =========================================
    # NC/ND
    # =========================================

    l10n_do_ncf_origin = fields.Char(string='NCF Afectado', copy=False)
    l10n_do_origin_move_id = fields.Many2one(
        'account.move', string='Factura Origen', copy=False,
        domain="[('partner_id', '=', partner_id), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]"
    )
    l10n_do_credit_note_reason = fields.Selection([
        ('01', '01 - Anulación total'),
        ('02', '02 - Corrección de errores'),
        ('03', '03 - Devolución de bienes'),
        ('04', '04 - Descuento posterior'),
        ('05', '05 - Ajuste de precio'),
        ('06', '06 - Otros'),
    ], string='Motivo NC')

    # Monto acreditado acumulado
    l10n_do_credited_amount = fields.Monetary(
        string='Monto Acreditado',
        compute='_compute_credited_amount',
        store=True,
        currency_field='currency_id'
    )

    # B03 Nota Débito
    l10n_do_is_debit_note = fields.Boolean(string='Es Nota de Débito', default=False)
    l10n_do_debit_note_reason = fields.Selection([
        ('01', '01 - Intereses por mora'),
        ('02', '02 - Gastos adicionales'),
        ('03', '03 - Ajuste precio al alza'),
        ('04', '04 - Otros cargos'),
    ], string='Motivo ND')
    l10n_do_debit_origin_move_id = fields.Many2one('account.move', string='Factura Origen ND', copy=False)
    l10n_do_debit_ncf_origin = fields.Char(string='NCF Afectado ND', copy=False)

    # ND en Compras
    l10n_do_is_vendor_debit_note = fields.Boolean(string='Es ND de Proveedor', default=False)
    l10n_do_vendor_debit_ncf_origin = fields.Char(string='NCF Afectado (ND Proveedor)')

    l10n_do_ncf_required = fields.Boolean(string='Requiere NCF', default=False)

    # =========================================
    # COMPRAS
    # =========================================

    l10n_do_vendor_ncf = fields.Char(string='NCF Proveedor', copy=False, tracking=True)
    l10n_do_vendor_ncf_validated = fields.Boolean(default=False, copy=False)
    l10n_do_vendor_ncf_validation_source = fields.Selection([
        ('local', 'Local'), ('dgii', 'DGII'), ('manual', 'Manual')
    ], default='local')

    l10n_do_fiscal_type = fields.Selection([
        ('fiscal', 'Compra Fiscal'),
        ('informal', 'B11 - Compra Informal'),
        ('minor_expense', 'B13 - Gasto Menor'),
        ('exterior', 'B17 - Pago Exterior'),
        ('special', 'B14 - Régimen Especial'),
        ('governmental', 'B15 - Gubernamental'),
    ], string='Tipo Fiscal', default='fiscal', tracking=True)

    # =========================================
    # B11 - INFORMAL
    # =========================================

    l10n_do_informal_provider_name = fields.Char(string='Nombre Proveedor Informal')
    l10n_do_informal_provider_cedula = fields.Char(string='Cédula Proveedor')
    l10n_do_informal_rnc_verified = fields.Boolean(default=False)

    l10n_do_informal_service_type = fields.Selection([
        ('professional', 'Servicios Profesionales (ISR 10%)'),
        ('technical', 'Servicios Técnicos (ISR 2%)'),
        ('goods', 'Bienes (ISR 2%)'),
    ], string='Tipo Servicio Informal', default='professional')

    # =========================================
    # B13 - GASTOS MENORES
    # =========================================

    l10n_do_minor_expense_type = fields.Selection([
        ('toll', 'Peaje'),
        ('parking', 'Estacionamiento'),
        ('transport', 'Transporte'),
        ('consumables', 'Consumibles'),
        ('meals', 'Alimentación'),
        ('other', 'Otros'),
    ], string='Tipo Gasto Menor')
    l10n_do_minor_expense_employee = fields.Char(string='Empleado')
    l10n_do_minor_expense_document = fields.Char(string='Documento Soporte')

    # =========================================
    # B17 - PAGO EXTERIOR
    # =========================================

    l10n_do_exterior_service_type = fields.Selection([
        ('01', '01 - Servicios técnicos'),
        ('02', '02 - Servicios profesionales'),
        ('03', '03 - Regalías'),
        ('04', '04 - Intereses'),
        ('05', '05 - Dividendos'),
        ('06', '06 - Otros'),
    ], string='Tipo Servicio Exterior')

    # =========================================
    # MULTIMONEDA
    # =========================================

    l10n_do_exchange_rate = fields.Float(
        string='Tasa de Cambio', digits=(12, 4), default=1.0,
    )

    l10n_do_amount_dop = fields.Monetary(
        string='Monto en DOP', currency_field='l10n_do_dop_currency_id',
        compute='_compute_amount_dop', store=True,
    )

    l10n_do_dop_currency_id = fields.Many2one(
        'res.currency', compute='_compute_dop_currency', store=True
    )

    # =========================================
    # FORMA DE PAGO MIXTA
    # =========================================

    l10n_do_payment_cash = fields.Monetary(
        string='Efectivo', currency_field='currency_id', default=0.0
    )
    l10n_do_payment_bank = fields.Monetary(
        string='Cheque/Transferencia', currency_field='currency_id', default=0.0
    )
    l10n_do_payment_card = fields.Monetary(
        string='Tarjeta', currency_field='currency_id', default=0.0
    )
    l10n_do_payment_credit = fields.Monetary(
        string='Crédito', currency_field='currency_id', default=0.0
    )
    l10n_do_payment_bond = fields.Monetary(
        string='Bonos/Certificados', currency_field='currency_id', default=0.0
    )
    l10n_do_payment_swap = fields.Monetary(
        string='Permuta', currency_field='currency_id', default=0.0
    )
    l10n_do_payment_other = fields.Monetary(
        string='Otras Formas', currency_field='currency_id', default=0.0
    )

    l10n_do_forma_pago = fields.Selection([
        ('01', '01 - Efectivo'),
        ('02', '02 - Cheque/Transferencia'),
        ('03', '03 - Tarjeta'),
        ('04', '04 - Crédito'),
        ('05', '05 - Permuta'),
        ('06', '06 - Nota Crédito'),
        ('07', '07 - Mixto'),
    ], string='Forma Pago', compute='_compute_forma_pago', store=True)

    # =========================================
    # RETENCIÓN POSTERIOR (607)
    # =========================================

    l10n_do_is_credit_sale = fields.Boolean(string='Venta a Crédito', default=False)
    l10n_do_retention_date = fields.Date(string='Fecha Retención')
    l10n_do_third_party_retention_itbis = fields.Monetary(
        string='ITBIS Retenido por Tercero', currency_field='currency_id', default=0.0
    )
    l10n_do_third_party_retention_isr = fields.Monetary(
        string='ISR Retenido por Tercero', currency_field='currency_id', default=0.0
    )
    l10n_do_retention_reported = fields.Boolean(string='Retención Reportada 607', default=False)

    l10n_do_needs_607_retention_line = fields.Boolean(
        string='Requiere Línea Retención 607',
        compute='_compute_needs_607_retention', store=True
    )

    # =========================================
    # CLASIFICACIÓN 606 - BIENES/SERVICIOS AUTO
    # =========================================

    l10n_do_expense_type = fields.Selection([
        ('01', '01 - Gastos de Personal'),
        ('02', '02 - Gastos por Trabajos/Servicios'),
        ('03', '03 - Arrendamientos'),
        ('04', '04 - Gastos Activos Fijos'),
        ('05', '05 - Gastos Representación'),
        ('06', '06 - Otras Deducciones'),
        ('07', '07 - Gastos Financieros'),
        ('08', '08 - Gastos Extraordinarios'),
        ('09', '09 - Costo de Venta'),
        ('10', '10 - Adquisición Activos'),
        ('11', '11 - Gastos de Seguros'),
    ], string='Tipo Gasto', default='02')

    l10n_do_purchase_type = fields.Selection([
        ('01', '01 - Gastos personal'),
        ('02', '02 - Trabajos/servicios'),
        ('03', '03 - Arrendamientos'),
        ('04', '04 - Activos fijos'),
        ('05', '05 - Representación'),
        ('06', '06 - Otras deducciones'),
        ('07', '07 - Financieros'),
        ('08', '08 - Extraordinarios'),
        ('09', '09 - Costo venta'),
        ('10', '10 - Adquisición activos'),
        ('11', '11 - Seguros'),
    ], string='Tipo Compra (606)', default='02')

    # Split automático bienes/servicios
    l10n_do_606_monto_bienes = fields.Monetary(
        string='Monto Bienes', currency_field='currency_id',
        compute='_compute_606_split_bienes_servicios', store=True, readonly=False
    )
    l10n_do_606_monto_servicios = fields.Monetary(
        string='Monto Servicios', currency_field='currency_id',
        compute='_compute_606_split_bienes_servicios', store=True, readonly=False
    )

    # =========================================
    # CAMPOS 606
    # =========================================

    l10n_do_itbis_facturado = fields.Monetary(
        string='ITBIS Facturado', currency_field='currency_id',
        compute='_compute_606_itbis', store=True
    )
    l10n_do_itbis_retenido = fields.Monetary(
        string='ITBIS Retenido (col 12)', currency_field='currency_id',
        compute='_compute_606_buckets', store=True
    )
    l10n_do_itbis_proporcionalidad = fields.Monetary(
        string='ITBIS Proporcionalidad', currency_field='currency_id', default=0.0
    )
    l10n_do_itbis_costo = fields.Monetary(
        string='ITBIS al Costo', currency_field='currency_id',
        compute='_compute_606_itbis_costo', store=True, readonly=False
    )
    l10n_do_itbis_adelantar = fields.Monetary(
        string='ITBIS a Adelantar', currency_field='currency_id',
        compute='_compute_606_itbis', store=True
    )
    l10n_do_itbis_percibido = fields.Monetary(
        string='ITBIS Percibido (col 16)', currency_field='currency_id',
        compute='_compute_606_buckets', store=True
    )

    l10n_do_tipo_retencion_isr = fields.Selection([
        ('01', '01 - Alquileres'),
        ('02', '02 - Honorarios'),
        ('03', '03 - Otras rentas'),
        ('04', '04 - Presunción renta'),
        ('05', '05 - Intereses PJ'),
        ('06', '06 - Intereses PF'),
        ('07', '07 - Proveedores Estado'),
        ('08', '08 - Juegos telefónicos'),
    ], string='Tipo Retención ISR')

    l10n_do_isr_retenido = fields.Monetary(
        string='ISR Retenido (col 18)', currency_field='currency_id',
        compute='_compute_606_buckets', store=True
    )
    l10n_do_isr_percibido = fields.Monetary(
        string='ISR Percibido (col 19)', currency_field='currency_id',
        compute='_compute_606_buckets', store=True
    )

    l10n_do_impuesto_selectivo = fields.Monetary(currency_field='currency_id', default=0.0)
    l10n_do_otros_impuestos = fields.Monetary(currency_field='currency_id', default=0.0)
    l10n_do_propina_legal = fields.Monetary(currency_field='currency_id', default=0.0)

    # =========================================
    # RETENCIONES
    # =========================================

    l10n_do_retention_ids = fields.One2many('l10n_do_ncf.move.retention', 'move_id', string='Retenciones')
    l10n_do_total_isr_retention = fields.Monetary(
        compute='_compute_retention_totals', store=True, currency_field='currency_id'
    )
    l10n_do_total_itbis_retention = fields.Monetary(
        compute='_compute_retention_totals', store=True, currency_field='currency_id'
    )
    l10n_do_amount_to_pay = fields.Monetary(
        compute='_compute_retention_totals', store=True, currency_field='currency_id'
    )

    # =========================================
    # ✅ MÉTODOS AUXILIARES CONFIGURABLES
    # =========================================

    def _get_b11_monthly_limit(self):
        """✅ FIX: Límite configurable B11"""
        param = self.env['ir.config_parameter'].sudo()
        return int(param.get_param('l10n_do_ncf.b11_monthly_limit', default=50))
    
    def _get_b13_transaction_limit(self):
        """✅ FIX: Límite configurable B13"""
        param = self.env['ir.config_parameter'].sudo()
        return float(param.get_param('l10n_do_ncf.b13_transaction_limit', default=10000))

    # =========================================
    # CÓMPUTOS MULTIMONEDA
    # =========================================

    @api.depends('company_id')
    def _compute_dop_currency(self):
        dop = self.env.ref('base.DOP', raise_if_not_found=False)
        for move in self:
            move.l10n_do_dop_currency_id = dop.id if dop else move.currency_id.id

    @api.depends('amount_total', 'l10n_do_exchange_rate', 'currency_id')
    def _compute_amount_dop(self):
        dop = self.env.ref('base.DOP', raise_if_not_found=False)
        for move in self:
            if move.currency_id and dop and move.currency_id.id != dop.id:
                move.l10n_do_amount_dop = move.amount_total * (move.l10n_do_exchange_rate or 1.0)
            else:
                move.l10n_do_amount_dop = move.amount_total

    # =========================================
    # ✅ FIX 6: CÓMPUTO MONTO ACREDITADO
    # =========================================

    @api.depends('state', 'l10n_do_origin_move_id', 'amount_total', 'move_type')
    def _compute_credited_amount(self):
        """✅ CORREGIDO: Depends completos"""
        for move in self:
            if move.move_type == 'out_invoice':
                credit_notes = self.search([
                    ('l10n_do_origin_move_id', '=', move.id),
                    ('state', '=', 'posted'),
                    ('move_type', '=', 'out_refund'),
                ])
                move.l10n_do_credited_amount = sum(credit_notes.mapped('amount_total'))
            else:
                move.l10n_do_credited_amount = 0

    # =========================================
    # CÓMPUTO SPLIT BIENES/SERVICIOS AUTOMÁTICO
    # =========================================

    @api.depends('invoice_line_ids', 'invoice_line_ids.product_id', 'invoice_line_ids.price_subtotal')
    def _compute_606_split_bienes_servicios(self):
        """
        Split automático basado en tipo de producto.
        product.detailed_type:
        - 'consu' / 'product' = Bien
        - 'service' = Servicio
        """
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund'):
                move.l10n_do_606_monto_bienes = 0
                move.l10n_do_606_monto_servicios = 0
                continue

            bienes = 0.0
            servicios = 0.0

            for line in move.invoice_line_ids.filtered(lambda l: not l.display_type):
                subtotal = line.price_subtotal or 0
                if line.product_id:
                    if line.product_id.detailed_type in ('consu', 'product'):
                        bienes += subtotal
                    else:
                        servicios += subtotal
                else:
                    servicios += subtotal

            move.l10n_do_606_monto_bienes = bienes
            move.l10n_do_606_monto_servicios = servicios

    # =========================================
    # ✅ FIX 2: CÓMPUTOS 606
    # =========================================

    @api.depends('l10n_do_fiscal_type', 'amount_tax')
    def _compute_606_itbis_costo(self):
        """✅ CORREGIDO: Siempre asigna valor explícito"""
        for move in self:
            if move.l10n_do_fiscal_type == 'minor_expense':
                move.l10n_do_itbis_costo = abs(move.amount_tax or 0)
            else:
                # ✅ FIX: Valor explícito cuando NO es minor_expense
                move.l10n_do_itbis_costo = 0

    @api.depends('amount_tax', 'l10n_do_itbis_costo', 'l10n_do_itbis_proporcionalidad', 'l10n_do_fiscal_type')
    def _compute_606_itbis(self):
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund'):
                move.l10n_do_itbis_facturado = 0
                move.l10n_do_itbis_adelantar = 0
                continue
            move.l10n_do_itbis_facturado = abs(move.amount_tax or 0)
            if move.l10n_do_fiscal_type in ('informal', 'minor_expense'):
                move.l10n_do_itbis_adelantar = 0
            else:
                move.l10n_do_itbis_adelantar = max(
                    move.l10n_do_itbis_facturado - (move.l10n_do_itbis_costo or 0) - (move.l10n_do_itbis_proporcionalidad or 0), 0
                )

    @api.depends('l10n_do_retention_ids', 'l10n_do_retention_ids.retention_amount', 'l10n_do_retention_ids.dgii_606_bucket')
    def _compute_606_buckets(self):
        for move in self:
            buckets = {'itbis_retenido': 0, 'itbis_percibido': 0, 'isr_retenido': 0, 'isr_percibido': 0}
            for ret in move.l10n_do_retention_ids:
                if ret.dgii_606_bucket in buckets:
                    buckets[ret.dgii_606_bucket] += ret.retention_amount or 0
            move.l10n_do_itbis_retenido = buckets['itbis_retenido']
            move.l10n_do_itbis_percibido = buckets['itbis_percibido']
            move.l10n_do_isr_retenido = buckets['isr_retenido']
            move.l10n_do_isr_percibido = buckets['isr_percibido']

    @api.depends('l10n_do_retention_ids', 'l10n_do_retention_ids.retention_amount', 'amount_total')
    def _compute_retention_totals(self):
        for move in self:
            isr = itbis = 0
            for ret in move.l10n_do_retention_ids:
                if ret.retention_type_id:
                    if ret.retention_type_id.retention_type == 'isr':
                        isr += ret.retention_amount or 0
                    elif ret.retention_type_id.retention_type == 'itbis':
                        itbis += ret.retention_amount or 0
            move.l10n_do_total_isr_retention = isr
            move.l10n_do_total_itbis_retention = itbis
            move.l10n_do_amount_to_pay = (move.amount_total or 0) - isr - itbis

    # =========================================
    # FORMA DE PAGO MIXTA
    # =========================================

    @api.depends('l10n_do_payment_cash', 'l10n_do_payment_bank', 'l10n_do_payment_card',
                 'l10n_do_payment_credit', 'l10n_do_payment_bond', 'l10n_do_payment_swap',
                 'l10n_do_payment_other', 'payment_state')
    def _compute_forma_pago(self):
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund', 'out_invoice', 'out_refund'):
                move.l10n_do_forma_pago = False
                continue

            payments = {
                '01': move.l10n_do_payment_cash or 0,
                '02': move.l10n_do_payment_bank or 0,
                '03': move.l10n_do_payment_card or 0,
                '04': move.l10n_do_payment_credit or 0,
                '05': move.l10n_do_payment_swap or 0,
                '07': move.l10n_do_payment_other or 0,
            }

            active_payments = [k for k, v in payments.items() if v > 0]

            if len(active_payments) > 1:
                move.l10n_do_forma_pago = '07'
            elif len(active_payments) == 1:
                move.l10n_do_forma_pago = active_payments[0]
            elif move.payment_state == 'not_paid':
                move.l10n_do_forma_pago = '04'
            elif move.payment_state == 'paid':
                move.l10n_do_forma_pago = '02'
            else:
                move.l10n_do_forma_pago = '04'

    @api.depends('l10n_do_is_credit_sale', 'l10n_do_retention_date', 'l10n_do_retention_reported',
                 'l10n_do_third_party_retention_itbis', 'l10n_do_third_party_retention_isr')
    def _compute_needs_607_retention(self):
        for move in self:
            move.l10n_do_needs_607_retention_line = (
                move.l10n_do_is_credit_sale and
                move.l10n_do_retention_date and
                not move.l10n_do_retention_reported and
                (move.l10n_do_third_party_retention_itbis > 0 or move.l10n_do_third_party_retention_isr > 0)
            )

    # =========================================
    # ✅ FIX 3: CÓMPUTO TIPO NCF OPTIMIZADO
    # =========================================

    @api.depends('move_type', 'partner_id', 'partner_id.vat', 'l10n_do_fiscal_type', 'l10n_do_is_debit_note')
    def _compute_l10n_do_ncf_type_id(self):
        """✅ OPTIMIZADO: Cache de tipos NCF"""
        NcfType = self.env['l10n_do_ncf.type']
        
        # ✅ FIX: Pre-cargar todos los tipos en un solo search
        all_types = NcfType.search([])
        type_cache = {t.code: t.id for t in all_types}
        
        for move in self:
            ncf_type_id = False
            
            if move.move_type == 'out_invoice':
                if move.l10n_do_is_debit_note:
                    ncf_type_id = type_cache.get('03')
                elif move.partner_id and move.partner_id.vat:
                    ncf_type_id = type_cache.get('01')
                else:
                    ncf_type_id = type_cache.get('02')
                    
            elif move.move_type == 'out_refund':
                ncf_type_id = type_cache.get('04')
                
            elif move.move_type in ('in_invoice', 'in_refund'):
                type_map = {
                    'informal': '11',
                    'minor_expense': '13',
                    'exterior': '17',
                    'special': '14',
                    'governmental': '15'
                }
                code = type_map.get(move.l10n_do_fiscal_type)
                if code:
                    ncf_type_id = type_cache.get(code)
            
            move.l10n_do_ncf_type_id = ncf_type_id

    # =========================================
    # VALIDACIONES CÉDULA RD
    # =========================================

    def _validate_cedula_rd(self, cedula):
        """Validar cédula dominicana con algoritmo Luhn modificado."""
        if not cedula:
            return False

        cedula = re.sub(r'[^0-9]', '', str(cedula))

        if len(cedula) != 11:
            return False

        try:
            weights = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
            total = 0
            for i in range(10):
                product = int(cedula[i]) * weights[i]
                total += product if product < 10 else product - 9

            check_digit = (10 - (total % 10)) % 10
            return int(cedula[10]) == check_digit
        except:
            return False

    def _validate_rnc_rd(self, rnc):
        """Validar RNC dominicano con Módulo 11."""
        if not rnc:
            return False

        rnc = re.sub(r'[^0-9]', '', str(rnc))

        if len(rnc) != 9:
            return False

        try:
            weights = [7, 9, 8, 6, 5, 4, 3, 2]
            total = sum(int(rnc[i]) * weights[i] for i in range(8))
            remainder = total % 11
            check_digit = 0 if remainder == 0 else (11 - remainder) if remainder != 1 else 0
            return int(rnc[8]) == check_digit
        except:
            return False

    # =========================================
    # VALIDACIONES
    # =========================================

    @api.constrains('l10n_do_informal_provider_cedula')
    def _check_cedula_format(self):
        """Validar formato de cédula para B11"""
        for move in self:
            if move.l10n_do_fiscal_type == 'informal' and move.l10n_do_informal_provider_cedula:
                cedula = move.l10n_do_informal_provider_cedula
                if not self._validate_cedula_rd(cedula):
                    raise ValidationError(_(
                        'Cédula inválida: %s\n\n'
                        'Verifique que:\n'
                        '- Tenga 11 dígitos\n'
                        '- El dígito verificador sea correcto'
                    ) % cedula)

    @api.constrains('l10n_do_vendor_ncf', 'company_id', 'partner_id')
    def _check_vendor_ncf_duplicate(self):
        """Validar que no exista duplicado de NCF proveedor"""
        for move in self:
            if not move.l10n_do_vendor_ncf or move.move_type not in ('in_invoice', 'in_refund'):
                continue

            ncf = move.l10n_do_vendor_ncf.strip().upper()
            duplicates = self.search([
                ('id', '!=', move.id),
                ('company_id', '=', move.company_id.id),
                ('l10n_do_vendor_ncf', '=ilike', ncf),
                ('move_type', 'in', ('in_invoice', 'in_refund')),
                ('state', '!=', 'cancel'),
            ])

            if duplicates:
                raise ValidationError(_(
                    '⚠️ NCF DUPLICADO\n\n'
                    'El NCF %s ya existe en:\n'
                    '- Documento: %s\n'
                    '- Proveedor: %s\n'
                    '- Fecha: %s'
                ) % (ncf, duplicates[0].name, duplicates[0].partner_id.name, duplicates[0].invoice_date))

    @api.constrains('l10n_do_vendor_ncf')
    def _check_vendor_ncf_format(self):
        for move in self:
            if move.l10n_do_vendor_ncf and move.move_type in ('in_invoice', 'in_refund'):
                ncf = move.l10n_do_vendor_ncf.strip().upper()
                if not re.match(NCF_FULL_PATTERN, ncf):
                    raise ValidationError(_('NCF proveedor inválido: %s') % ncf)

    @api.constrains('l10n_do_ncf_origin', 'move_type')
    def _check_ncf_origin(self):
        for move in self:
            if not move.company_id or not move.company_id.country_id or move.company_id.country_id.code != 'DO':
                continue
            if move.move_type == 'out_refund' and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_origin and not move.l10n_do_origin_move_id:
                    raise ValidationError(_('NC requiere NCF afectado.'))

    @api.constrains('l10n_do_is_debit_note', 'l10n_do_debit_ncf_origin')
    def _check_debit_note_origin(self):
        for move in self:
            if not move.company_id or not move.company_id.country_id or move.company_id.country_id.code != 'DO':
                continue
            if move.l10n_do_is_debit_note and move.state == 'posted':
                if not move.l10n_do_debit_ncf_origin and not move.l10n_do_debit_origin_move_id:
                    raise ValidationError(_('ND requiere NCF afectado.'))

    @api.constrains('l10n_do_is_vendor_debit_note', 'l10n_do_vendor_debit_ncf_origin')
    def _check_vendor_debit_note(self):
        for move in self:
            if not move.company_id or not move.company_id.country_id or move.company_id.country_id.code != 'DO':
                continue
            if move.l10n_do_is_vendor_debit_note and move.state == 'posted':
                if not move.l10n_do_vendor_debit_ncf_origin:
                    raise ValidationError(_('ND proveedor requiere NCF afectado.'))

    # =========================================
    # BLOQUEO POST-REPORTE DGII
    # =========================================

    def _check_dgii_reported_block(self):
        """Bloquear modificaciones si ya fue reportado a DGII."""
        self.ensure_one()
        if self.l10n_do_reported_606 or self.l10n_do_reported_607:
            raise UserError(_(
                '🔒 DOCUMENTO BLOQUEADO\n\n'
                'Este documento ya fue reportado a DGII en el período %s.\n\n'
                'No puede ser modificado ni cancelado.\n\n'
                'Para corregir errores debe:\n'
                '- Emitir Nota de Crédito (NC)\n'
                '- O realizar ajuste en período siguiente'
            ) % (self.l10n_do_report_period or 'anterior'))

    def button_cancel(self):
        """Override para bloquear cancelación post-reporte"""
        for move in self:
            if move.l10n_do_reported_606 or move.l10n_do_reported_607:
                move._check_dgii_reported_block()
        return super().button_cancel()

    def button_draft(self):
        """Override para bloquear volver a borrador en NC con NCF y post-reporte"""
        for move in self:
            # Bloquear NC con NCF generado
            if move.move_type == 'out_refund' and move.l10n_do_ncf_number:
                raise UserError(_(
                    '🔒 DOCUMENTO BLOQUEADO\n\n'
                    'Esta Nota de Crédito ya tiene NCF generado: %s\n\n'
                    'No puede volver a borrador.\n'
                    'Para corregir errores, anule este documento y cree uno nuevo.'
                ) % move.l10n_do_ncf_number)
            # Bloquear documentos reportados DGII
            if move.l10n_do_reported_606 or move.l10n_do_reported_607:
                move._check_dgii_reported_block()
        return super().button_draft()

    def unlink(self):
        """Override para bloquear eliminación post-reporte"""
        for move in self:
            if move.l10n_do_reported_606 or move.l10n_do_reported_607:
                raise UserError(_(
                    '🔒 No puede eliminar documentos reportados a DGII.\n'
                    'Documento: %s | Período: %s'
                ) % (move.name, move.l10n_do_report_period or 'N/A'))
        return super().unlink()

    # =========================================
    # VALIDACIONES B11/B13/B17
    # =========================================

    def _check_informal_provider_rnc(self):
        """Verificar que proveedor NO tenga RNC"""
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'informal':
            return True

        if self.partner_id and self.partner_id.vat:
            vat = self.partner_id.vat.replace('-', '').strip()
            if vat and len(vat) >= 9:
                raise UserError(_(
                    '⚠️ NO puede usar B11 para proveedor con RNC.\n\n'
                    'Proveedor: %s\nRNC: %s\n\n'
                    'Use "Compra Fiscal" y solicite NCF.'
                ) % (self.partner_id.name, self.partner_id.vat))

        if not self.l10n_do_informal_provider_name:
            raise UserError(_('B11 requiere nombre del proveedor informal.'))

        self.l10n_do_informal_rnc_verified = True
        return True

    # =========================================
    # ✅ FIX 4: B11 MONTHLY LIMIT CON BLOQUEO
    # =========================================

    def _check_b11_monthly_limit(self):
        """✅ CORREGIDO: Ahora bloquea si excede límite"""
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'informal':
            return
        
        limit = self._get_b11_monthly_limit()
        first_day = self.invoice_date.replace(day=1) if self.invoice_date else date.today().replace(day=1)
        
        count = self.search_count([
            ('company_id', '=', self.company_id.id),
            ('l10n_do_fiscal_type', '=', 'informal'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', first_day),
            ('id', '!=', self.id),
        ])
        
        if count >= limit:
            # ✅ FIX: Ahora BLOQUEA en lugar de solo avisar
            company_config = self.env['ir.config_parameter'].sudo()
            block_b11 = company_config.get_param('l10n_do_ncf.b11_block_on_limit', default='True') == 'True'
            
            if block_b11:
                raise UserError(_(
                    '🚫 LÍMITE B11 ALCANZADO\n\n'
                    'Ya tiene %s comprobantes B11 este mes.\n'
                    'Límite mensual: %s\n\n'
                    'No puede emitir más B11 hasta el próximo mes.\n\n'
                    'Opciones:\n'
                    '- Use "Compra Fiscal" y solicite NCF\n'
                    '- Configure límite en Ajustes > Contabilidad > NCF'
                ) % (count, limit))
            else:
                _logger.warning('B11 Alerta: %s - %s/%s B11 este mes', 
                              self.company_id.name, count, limit)

    # =========================================
    # ✅ FIX 8: VALIDACIÓN B13 CON LÍMITE CONFIGURABLE
    # =========================================

    def _check_b13_no_itbis(self):
        """✅ MEJORADO: Límite configurable"""
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'minor_expense':
            return True

        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                if tax.amount > 0 and 'itbis' in (tax.name or '').lower():
                    raise UserError(_(
                        '⚠️ B13 (Gasto Menor) no permite ITBIS acreditable.\n\n'
                        'Línea: %s\nImpuesto: %s\n\n'
                        'Use impuesto 0%% o quite el impuesto ITBIS.'
                    ) % (line.name, tax.name))

        # ✅ FIX: Límite configurable
        limit = self._get_b13_transaction_limit()
        if self.amount_total > limit:
            raise UserError(_(
                '⚠️ B13 excede límite de RD$ %s por transacción.\n\n'
                'Monto: RD$ %s\n\n'
                'Use "Compra Fiscal" para montos mayores.'
            ) % (limit, self.amount_total))

        return True

    def _check_b17_no_itbis(self):
        """Validar que B17 no tenga ITBIS (solo ISR 27%)"""
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'exterior':
            return True

        if self.amount_tax > 0:
            raise UserError(_(
                '⚠️ B17 (Pago Exterior) no debe tener ITBIS.\n\n'
                'Los pagos al exterior están exentos de ITBIS.\n'
                'Use impuesto 0%% y aplique retención ISR 27%%.'
            ))

        has_isr_27 = any(ret.retention_type_id.code == 'ISR_EXT' for ret in self.l10n_do_retention_ids)
        if not has_isr_27:
            raise UserError(_('B17 requiere retención ISR 27%.'))

        return True

    # =========================================
    # ✅ FIX 7: GENERADOR NCF CORREGIDO
    # =========================================

    def _generate_ncf(self):
        """✅ CORREGIDO: Comparación campo vs campo"""
        self.ensure_one()
        if self.l10n_do_ncf_number:
            return

        if not self.l10n_do_ncf_type_id:
            raise UserError(_('Seleccione tipo de comprobante.'))

        ncf_type = self.l10n_do_ncf_type_id
        
        # ✅ FIX: Filtrar correctamente secuencias disponibles
        sequences = self.env['l10n_do_ncf.sequence'].search([
            ('ncf_type_id', '=', ncf_type.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'active'),
        ], order='id desc')
        
        sequence = False
        for seq in sequences:
            if seq.current_number <= seq.range_to:
                sequence = seq
                break
        
        if not sequence:
            raise UserError(_(
                '⚠️ SECUENCIA AGOTADA\n\n'
                'No hay secuencias activas disponibles para %s.\n\n'
                'Solicite nuevos rangos NCF a DGII.'
            ) % ncf_type.name)

        if sequence.expiration_date:
            if self.invoice_date and self.invoice_date > sequence.expiration_date:
                raise UserError(_(
                    'La fecha de factura (%s) es posterior al vencimiento de la secuencia (%s).'
                ) % (self.invoice_date, sequence.expiration_date))
            if sequence.expiration_date < fields.Date.today():
                raise UserError(_('Secuencia %s vencida.') % sequence.name)

        prefix = ncf_type.prefix
        if sequence.current_number == 0:
            next_num = sequence.range_from if sequence.range_from >= 1 else 1
        else:
            next_num = sequence.current_number + 1
        
        if ncf_type.is_electronic:
            ncf = '%s%010d' % (prefix, next_num)
        else:
            ncf = '%s%08d' % (prefix, next_num)

        self.write({
            'l10n_do_ncf_number': ncf,
            'l10n_do_ncf_seq_id': sequence.id,
            'l10n_do_fiscal_status': 'valid',
        })
        sequence.sudo().write({'current_number': next_num})
        self.env['l10n_do_ncf.fiscal.audit'].log_event(
            'ncf_generated', move=self, description='NCF generado automáticamente'
        )

        _logger.info('NCF generado: %s | Doc: %s', ncf, self.name)
    # =========================================
    # ONCHANGE
    # =========================================
    @api.onchange('l10n_do_ncf_type_id')
    def _onchange_check_sequence_exists(self):
        """Validar que exista secuencia activa para el tipo seleccionado"""
        if not self.l10n_do_ncf_type_id:
            return
        
        if not self.company_id or not self.company_id.country_id or self.company_id.country_id.code != 'DO':
            return
        
        # Si ya tiene NCF, bloquear cambio
        if self.l10n_do_ncf_number:
            return {'warning': {
                'title': _('⚠️ Cambio no permitido'),
                'message': _('Este documento ya tiene NCF generado (%s). No puede cambiar el tipo de comprobante.') % self.l10n_do_ncf_number
            }}
    
        # Verificar existencia de secuencia activa
        if self.move_type in ('out_invoice', 'out_refund') and self.l10n_do_ncf_required:
            seq = self.env['l10n_do_ncf.sequence'].search([
                ('company_id', '=', self.company_id.id),
                ('ncf_type_id', '=', self.l10n_do_ncf_type_id.id),
                ('state', '=', 'active'),
            ], limit=1)
            
            if not seq:
                return {'warning': {
                    'title': _('⚠️ Sin secuencia activa'),
                    'message': _('No existe secuencia NCF activa para %s.\nDebe configurar una secuencia antes de usar este tipo.') % self.l10n_do_ncf_type_id.name
                }}


    @api.constrains('l10n_do_ncf_type_id')
    def _lock_ncf_type_after_generation(self):
        """Bloquear cambio de tipo NCF si ya tiene NCF generado"""
        for move in self:
            if not move.company_id or not move.company_id.country_id or move.company_id.country_id.code != 'DO':
                continue
            
            # Si ya tiene NCF, verificar que el tipo coincida con el prefijo
            if move.l10n_do_ncf_number and move.l10n_do_ncf_type_id:
                ncf_prefix = move.l10n_do_ncf_number[:3] if move.l10n_do_ncf_number else ''
                type_prefix = move.l10n_do_ncf_type_id.prefix if move.l10n_do_ncf_type_id else ''
                
                if ncf_prefix and type_prefix and ncf_prefix != type_prefix:
                    raise ValidationError(_(
                        '🔒 CAMBIO BLOQUEADO\n\n'
                        'Este documento ya tiene NCF emitido: %s\n'
                        'No puede cambiar el tipo de comprobante.\n\n'
                        'Si necesita corregir:\n'
                        '- Anule este documento\n'
                        '- Emita una Nota de Crédito (B04)\n'
                        '- Cree un nuevo documento con el tipo correcto'
                    ) % move.l10n_do_ncf_number)            
    @api.onchange('l10n_do_fiscal_type')
    def _onchange_fiscal_type(self):
        if self.move_type not in ('in_invoice', 'in_refund'):
            return

        if self.l10n_do_fiscal_type in ('informal', 'minor_expense'):
            self.l10n_do_retention_ids = [(5, 0, 0)]
            self.l10n_do_vendor_ncf = False

        if self.l10n_do_fiscal_type == 'informal':
            self._apply_b11_retentions()
        elif self.l10n_do_fiscal_type == 'exterior':
            self._apply_b17_retentions()

    def _apply_b11_retentions(self):
        """Retenciones B11: 100% ITBIS + ISR según tipo servicio"""
        retentions = []
        base = self.amount_untaxed or 0
        itbis = self.amount_tax or 0
        RetType = self.env['l10n_do_ncf.retention.type']

        if itbis > 0:
            itbis_type = RetType.search([('code', '=', 'ITBIS_100')], limit=1)
            if itbis_type:
                retentions.append((0, 0, {'retention_type_id': itbis_type.id, 'base_amount': itbis}))

        if base > 0:
            if self.l10n_do_informal_service_type == 'professional':
                isr_type = RetType.search([('code', '=', 'ISR_PROF')], limit=1)
                self.l10n_do_tipo_retencion_isr = '02'
            else:
                isr_type = RetType.search([('code', '=', 'ISR_TEC')], limit=1)
                self.l10n_do_tipo_retencion_isr = '03'

            if isr_type:
                retentions.append((0, 0, {'retention_type_id': isr_type.id, 'base_amount': base}))

        if retentions:
            self.l10n_do_retention_ids = retentions

    @api.onchange('l10n_do_informal_service_type')
    def _onchange_informal_service_type(self):
        if self.l10n_do_fiscal_type == 'informal':
            self._apply_b11_retentions()

    def _apply_b17_retentions(self):
        """Retenciones B17: 27% ISR"""
        retentions = []
        base = self.amount_untaxed or 0
        RetType = self.env['l10n_do_ncf.retention.type']
        if base > 0:
            isr_type = RetType.search([('code', '=', 'ISR_EXT')], limit=1)
            if isr_type:
                retentions.append((0, 0, {'retention_type_id': isr_type.id, 'base_amount': base}))
        if retentions:
            self.l10n_do_retention_ids = retentions
            self.l10n_do_tipo_retencion_isr = '03'

    @api.onchange('l10n_do_origin_move_id')
    def _onchange_origin_move(self):
        if self.l10n_do_origin_move_id:
            self.l10n_do_ncf_origin = self.l10n_do_origin_move_id.l10n_do_ncf_number

    @api.onchange('l10n_do_debit_origin_move_id')
    def _onchange_debit_origin_move(self):
        if self.l10n_do_debit_origin_move_id:
            self.l10n_do_debit_ncf_origin = self.l10n_do_debit_origin_move_id.l10n_do_ncf_number

    @api.onchange('l10n_do_vendor_ncf')
    def _onchange_vendor_ncf(self):
        if self.l10n_do_vendor_ncf:
            self.l10n_do_vendor_ncf = self.l10n_do_vendor_ncf.strip().upper()
            self.l10n_do_vendor_ncf_validated = False

    @api.onchange('partner_id')
    def _onchange_partner_check_rnc_change(self):
        """Detectar cambio de RNC en cliente con facturas previas."""
        if self.move_type != 'out_invoice' or not self.partner_id:
            return

        if self.partner_id.vat:
            b02_invoices = self.search([
                ('partner_id', '=', self.partner_id.id),
                ('l10n_do_ncf_number', '=like', 'B02%'),
                ('state', '=', 'posted'),
            ], limit=1)

            if b02_invoices:
                return {
                    'warning': {
                        'title': _('⚠️ Cliente con RNC nuevo'),
                        'message': _(
                            'Este cliente tiene facturas B02 anteriores.\n\n'
                            'Ahora tiene RNC: %s\n\n'
                            'Si necesita corregir facturas anteriores:\n'
                            '1. Emita NC (B04) a la factura B02\n'
                            '2. Emita nueva factura B01 con RNC'
                        ) % self.partner_id.vat
                    }
                }

    # =========================================
    # ✅ FIX 5: SYNC_TAX_RETENTIONS ACTIVADO
    # =========================================

    def _sync_tax_retentions(self):
        """✅ ACTIVADO: Sincronizar impuestos negativos con retenciones"""
        self.ensure_one()
        if self.move_type not in ('in_invoice', 'in_refund'):
            return
        
        # Solo ejecutar si NO tiene retenciones manuales
        if self.l10n_do_retention_ids:
            return
        
        RetType = self.env['l10n_do_ncf.retention.type']
        retentions = []
        base_amount = abs(self.amount_untaxed or 0)
        
        for line in self.line_ids:
            if line.tax_line_id and line.balance > 0:
                tax = line.tax_line_id
                tax_amount = abs(line.balance)
                tax_name = (tax.name or '').lower()
                tax_rate = abs(tax.amount)
                
                retention_type = False
                apply_base = base_amount
                
                if 'isr' in tax_name or 'renta' in tax_name:
                    if tax_rate >= 25:
                        retention_type = RetType.search([('code', '=', 'ISR_EXT')], limit=1)
                    elif tax_rate >= 8 and tax_rate <= 12:
                        retention_type = RetType.search([('code', '=', 'ISR_PROF')], limit=1)
                    elif tax_rate >= 1 and tax_rate <= 5:
                        retention_type = RetType.search([('code', '=', 'ISR_TEC')], limit=1)
                    else:
                        retention_type = RetType.search([('code', '=', 'ISR_PROF')], limit=1)
                
                elif 'itbis' in tax_name:
                    itbis_amount = abs(self.amount_tax or 0)
                    apply_base = itbis_amount
                    
                    if tax_rate >= 90:
                        retention_type = RetType.search([('code', '=', 'ITBIS_100')], limit=1)
                    elif tax_rate >= 70:
                        retention_type = RetType.search([('code', '=', 'ITBIS_75')], limit=1)
                    elif tax_rate >= 25:
                        retention_type = RetType.search([('code', '=', 'ITBIS_PROF')], limit=1)
                
                if retention_type:
                    if retention_type.rate > 0:
                        calculated_base = (tax_amount / retention_type.rate) * 100
                    else:
                        calculated_base = apply_base
                    
                    retentions.append((0, 0, {
                        'retention_type_id': retention_type.id,
                        'base_amount': calculated_base,
                    }))
        
        if retentions:
            self.l10n_do_retention_ids = retentions

    # =========================================
    # ✅ FIX 9: ACTION_POST CON SYNC ACTIVADO
    # =========================================

    def action_post(self):
        """✅ MEJORADO: Llama _sync_tax_retentions"""
        for move in self:
            is_do_company = move.company_id.country_id and move.company_id.country_id.code == 'DO'

            # VENTAS - Solo para compañías RD
            if is_do_company and move.move_type in ('out_invoice', 'out_refund') and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_type_id:
                    raise UserError(_('Seleccione tipo de comprobante.'))
                if move.move_type == 'out_refund':
                    if not move.l10n_do_ncf_origin and not move.l10n_do_origin_move_id:
                        raise UserError(_('NC requiere factura origen.'))
                    if not move.l10n_do_credit_note_reason:
                        raise UserError(_('NC requiere motivo.'))
                if move.l10n_do_is_debit_note:
                    if not move.l10n_do_debit_ncf_origin and not move.l10n_do_debit_origin_move_id:
                        raise UserError(_('ND requiere factura origen.'))
                    if not move.l10n_do_debit_note_reason:
                        raise UserError(_('ND requiere motivo.'))

            # COMPRAS - Solo para compañías RD
            if is_do_company and move.move_type in ('in_invoice', 'in_refund'):
                if move.l10n_do_fiscal_type == 'informal':
                    move._check_informal_provider_rnc()
                    move._check_b11_monthly_limit()
                elif move.l10n_do_fiscal_type == 'minor_expense':
                    move._check_b13_no_itbis()
                elif move.l10n_do_fiscal_type == 'exterior':
                    move._check_b17_no_itbis()
                elif move.l10n_do_fiscal_type == 'fiscal':
                    # Skip validation for demo data or vendors without VAT
                    if not self.env.context.get('install_mode') and move.partner_id and move.partner_id.vat and not move.l10n_do_vendor_ncf:
                        raise UserError(_('Ingrese NCF del proveedor o cambie Tipo Fiscal.'))

        result = super().action_post()

        for move in self:
            is_do_company = move.company_id.country_id and move.company_id.country_id.code == 'DO'

            # Generar NCF ventas - Solo para compañías RD
            if is_do_company and move.move_type in ('out_invoice', 'out_refund') and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_number:
                    move._generate_ncf()

                # Estado origen para NC
                if move.move_type == 'out_refund' and move.l10n_do_origin_move_id:
                    origin = move.l10n_do_origin_move_id
                    total_nc = sum(self.search([
                        ('l10n_do_origin_move_id', '=', origin.id),
                        ('state', '=', 'posted'),
                        ('move_type', '=', 'out_refund'),
                    ]).mapped('amount_total'))

                    if abs(total_nc - origin.amount_total) < 0.01:
                        origin.l10n_do_fiscal_status = 'annulled'
                    else:
                        origin.l10n_do_fiscal_status = 'partial_credit'

                    self.env['l10n_do_ncf.fiscal.audit'].log_credit_note(move, origin)

                if move.l10n_do_is_debit_note and move.l10n_do_debit_origin_move_id:
                    move.l10n_do_debit_origin_move_id.l10n_do_fiscal_status = 'debited'

            # Generar NCF compras B11/B13 - Solo para compañías RD
            if is_do_company and move.move_type in ('in_invoice', 'in_refund'):
                if move.l10n_do_fiscal_type in ('informal', 'minor_expense'):
                    if not move.l10n_do_ncf_number:
                        move._generate_ncf()
                
                # ✅ FIX: ACTIVAR sincronización de retenciones
                move._sync_tax_retentions()

        return result

    # =========================================
    # MÉTODOS AUXILIARES
    # =========================================

    def action_validate_vendor_ncf(self):
        self.ensure_one()
        if not self.l10n_do_vendor_ncf:
            raise UserError(_('Ingrese NCF.'))
        ncf = self.l10n_do_vendor_ncf.strip().upper()
        if not re.match(NCF_FULL_PATTERN, ncf):
            raise UserError(_('Formato inválido.'))
        self.write({'l10n_do_vendor_ncf': ncf, 'l10n_do_vendor_ncf_validated': True, 'l10n_do_vendor_ncf_validation_source': 'local'})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('✓ Validado'), 'message': ncf, 'type': 'success'}}

    def action_verify_informal_rnc(self):
        self.ensure_one()
        if self.partner_id and self.partner_id.vat:
            raise UserError(_('Proveedor tiene RNC: %s') % self.partner_id.vat)
        self.l10n_do_informal_rnc_verified = True
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('✓ Verificado'), 'message': _('Sin RNC'), 'type': 'success'}}

    def action_add_retention(self):
        return {
            'type': 'ir.actions.act_window', 'name': _('Agregar Retención'),
            'res_model': 'l10n_do_ncf.retention.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_move_id': self.id, 'default_base_amount': self.amount_untaxed, 'default_itbis_amount': self.amount_tax}
        }

    def action_clear_retentions(self):
        self.l10n_do_retention_ids.unlink()

    def action_mark_reported_606(self):
        """Marcar como reportado en 606"""
        self.ensure_one()
        period = self.invoice_date.strftime('%Y%m') if self.invoice_date else fields.Date.today().strftime('%Y%m')
        self.write({
            'l10n_do_reported_606': True,
            'l10n_do_report_period': period,
        })
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('✓ Marcado'), 'message': _('Reportado 606 período %s') % period, 'type': 'success'}}

    def action_mark_reported_607(self):
        """Marcar como reportado en 607"""
        self.ensure_one()
        period = self.invoice_date.strftime('%Y%m') if self.invoice_date else fields.Date.today().strftime('%Y%m')
        self.write({
            'l10n_do_reported_607': True,
            'l10n_do_report_period': period,
        })
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('✓ Marcado'), 'message': _('Reportado 607 período %s') % period, 'type': 'success'}}

    def action_mark_retention_reported(self):
        self.ensure_one()
        self.l10n_do_retention_reported = True
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('✓ Marcada'), 'message': _('Retención reportada en 607.'), 'type': 'success'}}

    # =========================================
    # HELPERS REPORTES 606/607
    # =========================================

    def _get_ncf_for_report(self):
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund'):
            return self.l10n_do_ncf_number or ''
        elif self.move_type in ('in_invoice', 'in_refund'):
            if self.l10n_do_fiscal_type in ('informal', 'minor_expense'):
                return self.l10n_do_ncf_number or ''
            return self.l10n_do_vendor_ncf or ''
        return ''

    def _get_rnc_for_606(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type == 'minor_expense':
            return self.company_id.vat or ''
        elif self.l10n_do_fiscal_type == 'informal':
            return self.l10n_do_informal_provider_cedula or ''
        return self.partner_id.vat or '' if self.partner_id else ''

    def _get_606_line_data(self):
        """Datos completos para línea 606"""
        self.ensure_one()

        ncf_modificado = ''
        if self.move_type == 'in_refund':
            ncf_modificado = self.l10n_do_ncf_origin or ''
        elif self.l10n_do_is_vendor_debit_note:
            ncf_modificado = self.l10n_do_vendor_debit_ncf_origin or ''

        return {
            'rnc': self._get_rnc_for_606(),
            'tipo_id': '2' if self.l10n_do_informal_provider_cedula else '1',
            'tipo_bienes_servicios': self.l10n_do_purchase_type or '02',
            'ncf': self._get_ncf_for_report(),
            'ncf_modificado': ncf_modificado,
            'fecha': self.invoice_date,
            'monto_bienes': self.l10n_do_606_monto_bienes or 0,
            'monto_servicios': self.l10n_do_606_monto_servicios or 0,
            'itbis_facturado': self.l10n_do_itbis_facturado or 0,
            'itbis_retenido': self.l10n_do_itbis_retenido or 0,
            'itbis_proporcionalidad': self.l10n_do_itbis_proporcionalidad or 0,
            'itbis_costo': self.l10n_do_itbis_costo or 0,
            'itbis_adelantar': self.l10n_do_itbis_adelantar or 0,
            'itbis_percibido': self.l10n_do_itbis_percibido or 0,
            'tipo_retencion_isr': self.l10n_do_tipo_retencion_isr or '',
            'isr_retenido': self.l10n_do_isr_retenido or 0,
            'isr_percibido': self.l10n_do_isr_percibido or 0,
            'impuesto_selectivo': self.l10n_do_impuesto_selectivo or 0,
            'otros_impuestos': self.l10n_do_otros_impuestos or 0,
            'propina_legal': self.l10n_do_propina_legal or 0,
            'forma_pago': self.l10n_do_forma_pago or '04',
            'monto_dop': self.l10n_do_amount_dop or self.amount_total,
            'tasa_cambio': self.l10n_do_exchange_rate or 1.0,
            'es_nota_debito': self.l10n_do_is_vendor_debit_note,
        }

    def _get_607_lines_data(self):
        """Datos para 607 incluyendo segunda línea de retención posterior."""
        self.ensure_one()
        lines = []

        main_line = {
            'rnc_cedula': self.partner_id.vat or '',
            'tipo_id': '1' if len(self.partner_id.vat or '') == 9 else '2',
            'ncf': self.l10n_do_ncf_number or '',
            'ncf_modificado': self.l10n_do_ncf_origin or '',
            'fecha_comprobante': self.invoice_date,
            'fecha_retencion': None,
            'itbis_facturado': abs(self.amount_tax) if self.move_type == 'out_invoice' else 0,
            'itbis_retenido_terceros': 0,
            'monto_facturado': self.amount_total,
            'isr_retenido_terceros': 0,
            'efectivo': self.l10n_do_payment_cash or 0,
            'cheque_transfer': self.l10n_do_payment_bank or 0,
            'tarjeta': self.l10n_do_payment_card or 0,
            'credito': self.l10n_do_payment_credit or 0,
            'bonos': self.l10n_do_payment_bond or 0,
            'permuta': self.l10n_do_payment_swap or 0,
            'otras_formas': self.l10n_do_payment_other or 0,
        }
        lines.append(main_line)

        if self.l10n_do_needs_607_retention_line:
            retention_line = {
                'rnc_cedula': self.partner_id.vat or '',
                'tipo_id': '1' if len(self.partner_id.vat or '') == 9 else '2',
                'ncf': self.l10n_do_ncf_number or '',
                'ncf_modificado': '',
                'fecha_comprobante': self.invoice_date,
                'fecha_retencion': self.l10n_do_retention_date,
                'itbis_facturado': 0,
                'itbis_retenido_terceros': self.l10n_do_third_party_retention_itbis or 0,
                'monto_facturado': 0,
                'isr_retenido_terceros': self.l10n_do_third_party_retention_isr or 0,
                'efectivo': 0,
                'cheque_transfer': self.l10n_do_payment_bank or 0,
                'tarjeta': 0,
                'credito': 0,
                'bonos': 0,
                'permuta': 0,
                'otras_formas': 0,
            }
            lines.append(retention_line)

        return lines





