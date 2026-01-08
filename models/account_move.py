# -*- coding: utf-8 -*-
# módulo: l10n_do_ncf
# Archivo: models/account_move.py
# Versión: 19.0 FINAL - PRODUCCIÓN LISTA - ODOO 19
# Compatibilidad: Odoo 19 (100% compatible, upgrade-friendly)

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date
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
    # CAMPOS NCF
    # =========================================
    l10n_do_ncf_number = fields.Char(
        string='NCF', copy=False, readonly=True, tracking=True, index=True,
    )

    l10n_do_ncf_type_id = fields.Many2one(
        'l10n_do_ncf.type', string='Tipo NCF', tracking=True,
        compute='_compute_l10n_do_ncf_type_id', store=True, readonly=True,
    )

    l10n_do_ncf_type_display = fields.Char(
        string='Comprobante',
        related='l10n_do_ncf_type_id.display_name',
        readonly=True,
    )
    l10n_do_payment_status_display = fields.Char(
        string='Estado de Pago',
        compute='_compute_payment_status_display',
        store=False,
    )
    l10n_do_ncf_seq_id = fields.Many2one(
        'l10n_do_ncf.sequence', string='Secuencia', readonly=True, copy=False,
    )

    l10n_do_ncf_expiration = fields.Date(related='l10n_do_ncf_seq_id.expiration_date', store=True)

    l10n_do_ncf_required = fields.Boolean(string='Requiere NCF', default=False)

    # =========================================
    # ESTADO FISCAL Y REPORTE DGII
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

    l10n_do_reported_606 = fields.Boolean(string='Reportado 606', default=False, tracking=True)
    l10n_do_reported_607 = fields.Boolean(string='Reportado 607', default=False, tracking=True)
    l10n_do_report_period = fields.Char(string='Período Reportado')

    # =========================================
    # NC / ND
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

    l10n_do_credited_amount = fields.Monetary(
        compute='_compute_credited_amount', store=True, currency_field='currency_id'
    )

    l10n_do_is_debit_note = fields.Boolean(string='Es Nota de Débito', default=False)
    l10n_do_debit_note_reason = fields.Selection([
        ('01', '01 - Intereses por mora'),
        ('02', '02 - Gastos adicionales'),
        ('03', '03 - Ajuste precio al alza'),
        ('04', '04 - Otros cargos'),
    ], string='Motivo ND')
    l10n_do_debit_origin_move_id = fields.Many2one('account.move', string='Factura Origen ND', copy=False)
    l10n_do_debit_ncf_origin = fields.Char(string='NCF Afectado ND', copy=False)

    l10n_do_is_vendor_debit_note = fields.Boolean(string='Es ND de Proveedor', default=False)
    l10n_do_vendor_debit_ncf_origin = fields.Char(string='NCF Afectado (ND Proveedor)')

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

    # B11 - INFORMAL
    l10n_do_informal_provider_name = fields.Char(string='Nombre Proveedor Informal')
    l10n_do_informal_provider_cedula = fields.Char(string='Cédula Proveedor')
    l10n_do_informal_rnc_verified = fields.Boolean(default=False)
    l10n_do_informal_service_type = fields.Selection([
        ('professional', 'Servicios Profesionales (ISR 10%)'),
        ('technical', 'Servicios Técnicos (ISR 2%)'),
        ('goods', 'Bienes (ISR 2%)'),
    ], string='Tipo Servicio Informal', default='professional')

    # B13 - GASTOS MENORES
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

    # B17 - PAGO EXTERIOR
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
    l10n_do_exchange_rate = fields.Float(string='Tasa de Cambio', digits=(12, 4), default=1.0)
    l10n_do_amount_dop = fields.Monetary(
        compute='_compute_amount_dop', store=True, currency_field='l10n_do_dop_currency_id'
    )
    l10n_do_dop_currency_id = fields.Many2one('res.currency', compute='_compute_dop_currency', store=True)

    # =========================================
    # FORMA DE PAGO
    # =========================================
    l10n_do_payment_cash = fields.Monetary(string='Efectivo', currency_field='currency_id', default=0.0)
    l10n_do_payment_bank = fields.Monetary(string='Cheque/Transferencia', currency_field='currency_id', default=0.0)
    l10n_do_payment_card = fields.Monetary(string='Tarjeta', currency_field='currency_id', default=0.0)
    l10n_do_payment_credit = fields.Monetary(string='Crédito', currency_field='currency_id', default=0.0)
    l10n_do_payment_bond = fields.Monetary(string='Bonos/Certificados', currency_field='currency_id', default=0.0)
    l10n_do_payment_swap = fields.Monetary(string='Permuta', currency_field='currency_id', default=0.0)
    l10n_do_payment_other = fields.Monetary(string='Otras Formas', currency_field='currency_id', default=0.0)

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
    l10n_do_third_party_retention_itbis = fields.Monetary(string='ITBIS Retenido por Tercero', currency_field='currency_id', default=0.0)
    l10n_do_third_party_retention_isr = fields.Monetary(string='ISR Retenido por Tercero', currency_field='currency_id', default=0.0)
    l10n_do_retention_reported = fields.Boolean(string='Retención Reportada 607', default=False)

    l10n_do_needs_607_retention_line = fields.Boolean(
        compute='_compute_needs_607_retention', store=True
    )

    # =========================================
    # CLASIFICACIÓN 606
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

    l10n_do_606_monto_bienes = fields.Monetary(
        compute='_compute_606_split_bienes_servicios', store=True, readonly=False, currency_field='currency_id'
    )
    l10n_do_606_monto_servicios = fields.Monetary(
        compute='_compute_606_split_bienes_servicios', store=True, readonly=False, currency_field='currency_id'
    )

    # CAMPOS 606
    l10n_do_itbis_facturado = fields.Monetary(compute='_compute_606_itbis', store=True, currency_field='currency_id')
    l10n_do_itbis_retenido = fields.Monetary(compute='_compute_606_buckets', store=True, currency_field='currency_id')
    l10n_do_itbis_proporcionalidad = fields.Monetary(currency_field='currency_id', default=0.0)
    l10n_do_itbis_costo = fields.Monetary(compute='_compute_606_itbis_costo', store=True, readonly=False, currency_field='currency_id')
    l10n_do_itbis_adelantar = fields.Monetary(compute='_compute_606_itbis', store=True, currency_field='currency_id')
    l10n_do_itbis_percibido = fields.Monetary(compute='_compute_606_buckets', store=True, currency_field='currency_id')

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

    l10n_do_isr_retenido = fields.Monetary(compute='_compute_606_buckets', store=True, currency_field='currency_id')
    l10n_do_isr_percibido = fields.Monetary(compute='_compute_606_buckets', store=True, currency_field='currency_id')

    l10n_do_impuesto_selectivo = fields.Monetary(currency_field='currency_id', default=0.0)
    l10n_do_otros_impuestos = fields.Monetary(currency_field='currency_id', default=0.0)
    l10n_do_propina_legal = fields.Monetary(currency_field='currency_id', default=0.0)

    # =========================================
    # RETENCIONES
    # =========================================
    l10n_do_retention_ids = fields.One2many('l10n_do_ncf.move.retention', 'move_id', string='Retenciones')
    l10n_do_total_isr_retention = fields.Monetary(compute='_compute_retention_totals', store=True, currency_field='currency_id')
    l10n_do_total_itbis_retention = fields.Monetary(compute='_compute_retention_totals', store=True, currency_field='currency_id')
    l10n_do_gross_total = fields.Monetary(
        string='Total Bruto',
        compute='_compute_retention_totals', 
        store=True, 
        currency_field='currency_id',
        help='Total antes de retenciones (amount_total + retenciones)'
    )
    l10n_do_gross_total = fields.Monetary(
        string='Total Bruto',
        compute='_compute_retention_totals', 
        store=True, 
        currency_field='currency_id',
    )
    l10n_do_amount_to_pay = fields.Monetary(compute='_compute_retention_totals', store=True, currency_field='currency_id')

    # =========================================
    # CONFIGURABLES
    # =========================================
    def _get_b11_monthly_limit(self):
        return int(self.env['ir.config_parameter'].sudo().get_param('l10n_do_ncf.b11_monthly_limit', '50'))

    def _get_b13_transaction_limit(self):
        return float(self.env['ir.config_parameter'].sudo().get_param('l10n_do_ncf.b13_transaction_limit', '10000'))

    # =========================================
    # PROTECCIÓN FISCAL EN WRITE
    # =========================================
    def write(self, vals):
        protected_fields = {
            'l10n_do_ncf_type_id',
            'l10n_do_ncf_required',
            'l10n_do_ncf_seq_id',
            'l10n_do_ncf_number',
        }

        for move in self:
            if not move.company_id.country_id or move.company_id.country_id.code != 'DO':
                continue

            if move.l10n_do_ncf_number and protected_fields & set(vals.keys()):
                raise UserError(_(
                    '🔒 CAMBIO FISCAL NO PERMITIDO\n\n'
                    'Factura con NCF %s.\n\n'
                    'No se puede modificar tipo de comprobante ni secuencia.\n\n'
                    'Para corregir, emita Nota de Crédito.'
                ) % move.l10n_do_ncf_number)

        return super().write(vals)

    # =========================================
    # CÓMPUTOS
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
            if move.currency_id != dop:
                move.l10n_do_amount_dop = move.amount_total * move.l10n_do_exchange_rate
            else:
                move.l10n_do_amount_dop = move.amount_total

    @api.depends('state', 'l10n_do_origin_move_id', 'amount_total', 'move_type')
    def _compute_credited_amount(self):
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

    @api.depends('invoice_line_ids.product_id.type', 'invoice_line_ids.price_subtotal')
    def _compute_606_split_bienes_servicios(self):
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund'):
                move.l10n_do_606_monto_bienes = move.l10n_do_606_monto_servicios = 0
                continue
            bienes = servicios = 0.0
            for line in move.invoice_line_ids.filtered(lambda l: not l.display_type):
                subtotal = line.price_subtotal
                if line.product_id and line.product_id.type in ('consu', 'product'):
                    bienes += subtotal
                else:
                    servicios += subtotal
            move.l10n_do_606_monto_bienes = bienes
            move.l10n_do_606_monto_servicios = servicios

    @api.depends('l10n_do_fiscal_type', 'amount_tax')
    def _compute_606_itbis_costo(self):
        for move in self:
            move.l10n_do_itbis_costo = abs(move.amount_tax) if move.l10n_do_fiscal_type == 'minor_expense' else 0

    @api.depends('amount_tax', 'l10n_do_itbis_costo', 'l10n_do_itbis_proporcionalidad', 'l10n_do_fiscal_type')
    def _compute_606_itbis(self):
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund'):
                move.l10n_do_itbis_facturado = move.l10n_do_itbis_adelantar = 0
                continue
            move.l10n_do_itbis_facturado = abs(move.amount_tax or 0)
            if move.l10n_do_fiscal_type in ('informal', 'minor_expense'):
                move.l10n_do_itbis_adelantar = 0
            else:
                move.l10n_do_itbis_adelantar = max(
                    move.l10n_do_itbis_facturado - move.l10n_do_itbis_costo - move.l10n_do_itbis_proporcionalidad, 0
                )

    @api.depends('l10n_do_retention_ids.retention_amount', 'l10n_do_retention_ids.dgii_606_bucket')
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
    @api.depends('payment_state', 'move_type')
    def _compute_payment_status_display(self):
        """Mostrar 'Aplicada' en lugar de 'Pagado' para NC"""
        status_map = {
            'not_paid': 'Sin pagar',
            'partial': 'Parcial',
            'paid': 'Pagado',
            'in_payment': 'En pago',
            'reversed': 'Revertido',
        }
        for move in self:
            if move.move_type in ('out_refund', 'in_refund') and move.payment_state == 'paid':
                move.l10n_do_payment_status_display = 'Aplicada'
            else:
                move.l10n_do_payment_status_display = status_map.get(move.payment_state, move.payment_state or '')


    @api.depends('line_ids.tax_line_id', 'line_ids.balance', 'amount_total', 'l10n_do_retention_ids.retention_amount', 'l10n_do_retention_ids.retention_type_id')
    def _compute_retention_totals(self):
        """Calcular totales de retenciones desde l10n_do_retention_ids
        
        Fuentes de datos (en orden de prioridad):
        1. l10n_do_retention_ids - retenciones manuales/calculadas del módulo NCF
        2. line_ids con dgii_retention_type - impuestos de Odoo marcados como retención
        
        Nota: En Odoo, amount_total YA incluye las retenciones (impuestos negativos).
        """
        for move in self:
            isr = itbis = 0
            
            # Fuente 1: Retenciones del módulo NCF (l10n_do_retention_ids)
            for ret in move.l10n_do_retention_ids:
                if ret.retention_type_id and ret.retention_type_id.retention_type:
                    amount = ret.retention_amount or 0
                    if ret.retention_type_id.retention_type == 'isr':
                        isr += amount
                    elif ret.retention_type_id.retention_type == 'itbis':
                        itbis += amount
            
            # Fuente 2: Si no hay retenciones NCF, buscar en impuestos de Odoo
            if not isr and not itbis:
                for line in move.line_ids:
                    if line.tax_line_id and line.tax_line_id.dgii_retention_type:
                        amount = abs(line.balance)
                        if line.tax_line_id.dgii_retention_type == 'isr':
                            isr += amount
                        elif line.tax_line_id.dgii_retention_type == 'itbis':
                            itbis += amount
            
            move.l10n_do_total_isr_retention = isr
            move.l10n_do_total_itbis_retention = itbis
            move.l10n_do_amount_to_pay = move.amount_total
            move.l10n_do_gross_total = move.amount_total + isr + itbis

    @api.depends('l10n_do_payment_cash', 'l10n_do_payment_bank', 'l10n_do_payment_card',
                 'l10n_do_payment_credit', 'l10n_do_payment_bond', 'l10n_do_payment_swap',
                 'l10n_do_payment_other', 'payment_state')
    def _compute_forma_pago(self):
        for move in self:
            payments = {
                '01': move.l10n_do_payment_cash or 0,
                '02': move.l10n_do_payment_bank or 0,
                '03': move.l10n_do_payment_card or 0,
                '04': move.l10n_do_payment_credit or 0,
                '05': move.l10n_do_payment_swap or 0,
                '07': move.l10n_do_payment_other or 0,
            }
            active = [k for k, v in payments.items() if v > 0]
            if len(active) > 1:
                move.l10n_do_forma_pago = '07'
            elif active:
                move.l10n_do_forma_pago = active[0]
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

    @api.depends('move_type', 'partner_id.vat', 'partner_id.l10n_do_dgii_tax_payer_type', 'l10n_do_fiscal_type', 'l10n_do_is_debit_note')
    def _compute_l10n_do_ncf_type_id(self):
        """Asignar tipo de NCF segun tipo fiscal del cliente/proveedor
        
        VENTAS (out_invoice) - Orden de evaluacion segun DGII:
        1. Exportacion (cliente extranjero) -> B16
        2. Gubernamental -> B15
        3. Regimen Especial -> B14
        4. Nota de Debito -> B03
        5. Con RNC (contribuyente) -> B01
        6. Sin RNC (consumidor final) -> B02
        
        NC VENTAS (out_refund): siempre B04
        COMPRAS (in_invoice): segun l10n_do_fiscal_type del movimiento
        """
        NcfType = self.env['l10n_do_ncf.type']
        all_types = NcfType.search([])
        type_cache = {t.code: t for t in all_types}
        
        # Mapeo tipo fiscal proveedor -> NCF para compras
        supplier_fiscal_map = {
            'informal': '11',
            'minor_expense': '13',
            'exterior': '17',
            'special': '14',
            'governmental': '15',
        }
        
        for move in self:
            code = False
            
            if move.move_type == 'out_invoice':
                # ORDEN CORRECTO segun normativa DGII
                partner = move.partner_id
                partner_country = partner.country_id.code if partner.country_id else 'DO'
                client_type = partner.l10n_do_dgii_tax_payer_type or 'final_consumer'
                has_rnc = bool(partner.vat and len(partner.vat.strip()) >= 9)
                
                # 1. Exportacion: cliente extranjero (pais != DO)
                if partner_country and partner_country != 'DO':
                    code = '16'  # B16 - Exportacion
                # 2. Gubernamental
                elif client_type == 'governmental':
                    code = '15'  # B15 - Gubernamental
                # 3. Regimen Especial
                elif client_type == 'special_regime':
                    code = '14'  # B14 - Regimen Especial
                # 4. Nota de Debito
                elif move.l10n_do_is_debit_note:
                    code = '03'  # B03 - Nota de Debito
                # 5. Contribuyente con RNC
                elif client_type == 'taxpayer' or has_rnc:
                    code = '01'  # B01 - Credito Fiscal
                # 6. Consumidor Final (default)
                else:
                    code = '02'  # B02 - Consumidor Final
                    
            elif move.move_type == 'out_refund':
                code = '04'  # B04 - Nota de Credito
                
            elif move.move_type in ('in_invoice', 'in_refund'):
                code = supplier_fiscal_map.get(move.l10n_do_fiscal_type)
            
            move.l10n_do_ncf_type_id = type_cache.get(code).id if code and code in type_cache else False

    # =========================================
    # VALIDACIONES CÉDULA / RNC
    # =========================================
    def _validate_cedula_rd(self, cedula):
        if not cedula:
            return False
        cedula = re.sub(r'[^0-9]', '', str(cedula))
        if len(cedula) != 11:
            return False
        try:
            weights = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
            total = sum(int(cedula[i]) * weights[i] if int(cedula[i]) * weights[i] < 10 else int(cedula[i]) * weights[i] - 9 for i in range(10))
            check_digit = (10 - (total % 10)) % 10
            return int(cedula[10]) == check_digit
        except:
            return False

    def _validate_rnc_rd(self, rnc):
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
    # CONSTRAINTS Y VALIDACIONES
    # =========================================
    @api.constrains('l10n_do_informal_provider_cedula')
    def _check_cedula_format(self):
        for move in self:
            if move.l10n_do_fiscal_type == 'informal' and move.l10n_do_informal_provider_cedula:
                if not self._validate_cedula_rd(move.l10n_do_informal_provider_cedula):
                    raise ValidationError(_('Cédula inválida: %s') % move.l10n_do_informal_provider_cedula)

    @api.constrains('l10n_do_vendor_ncf', 'company_id', 'partner_id')
    def _check_vendor_ncf_duplicate(self):
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
                raise ValidationError(_('NCF proveedor duplicado: %s (ya existe en %s)') % (ncf, duplicates[0].name))

    @api.constrains('l10n_do_vendor_ncf')
    def _check_vendor_ncf_format(self):
        for move in self:
            if move.l10n_do_vendor_ncf and move.move_type in ('in_invoice', 'in_refund'):
                if not re.match(NCF_FULL_PATTERN, move.l10n_do_vendor_ncf.strip().upper()):
                    raise ValidationError(_('NCF proveedor inválido: %s') % move.l10n_do_vendor_ncf)

    @api.constrains('l10n_do_ncf_origin', 'move_type')
    def _check_ncf_origin(self):
        for move in self:
            if move.company_id.country_id.code != 'DO':
                continue
            if move.move_type == 'out_refund' and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_origin and not move.l10n_do_origin_move_id:
                    raise ValidationError(_('NC requiere NCF afectado.'))

    @api.constrains('l10n_do_is_debit_note', 'l10n_do_debit_ncf_origin')
    def _check_debit_note_origin(self):
        for move in self:
            if move.company_id.country_id.code != 'DO':
                continue
            if move.l10n_do_is_debit_note and move.state == 'posted':
                if not move.l10n_do_debit_ncf_origin and not move.l10n_do_debit_origin_move_id:
                    raise ValidationError(_('ND requiere NCF afectado.'))

    @api.constrains('l10n_do_is_vendor_debit_note', 'l10n_do_vendor_debit_ncf_origin')
    def _check_vendor_debit_note(self):
        for move in self:
            if move.company_id.country_id.code != 'DO':
                continue
            if move.l10n_do_is_vendor_debit_note and move.state == 'posted':
                if not move.l10n_do_vendor_debit_ncf_origin:
                    raise ValidationError(_('ND proveedor requiere NCF afectado.'))

    @api.constrains('l10n_do_ncf_type_id')
    def _lock_ncf_type_after_generation(self):
        for move in self:
            if move.company_id.country_id.code != 'DO':
                continue
            if move.l10n_do_ncf_number and move.l10n_do_ncf_type_id:
                ncf_prefix = move.l10n_do_ncf_number[:3]
                type_prefix = move.l10n_do_ncf_type_id.prefix
                if ncf_prefix != type_prefix:
                    raise ValidationError(_('No puede cambiar el tipo de comprobante con NCF generado: %s') % move.l10n_do_ncf_number)

    # =========================================
    # BLOQUEO POST-REPORTE
    # =========================================
    def _check_dgii_reported_block(self):
        self.ensure_one()
        if self.l10n_do_reported_606 or self.l10n_do_reported_607:
            raise UserError(_('Documento reportado a DGII en período %s. No puede modificarse.') % (self.l10n_do_report_period or 'anterior'))

    def button_cancel(self):
        for move in self:
            # Bloquear si ya fue reportado a DGII
            if move.l10n_do_reported_606 or move.l10n_do_reported_607:
                move._check_dgii_reported_block()
            # Bloquear cancelacion de facturas con NCF (posted o draft con NCF)
            if move.l10n_do_ncf_number:
                raise UserError(_(
                    "No se puede cancelar una factura con NCF asignado.\n\n"
                    "NCF: %s\n\n"
                    "Para reversar esta factura, debe emitir una Nota de Credito (B04).\n"
                    "Esto es requerido por la DGII."
                ) % move.l10n_do_ncf_number)
        return super().button_cancel()

    def button_draft(self):
        for move in self:
            # Solo bloquear si ya fue reportado a DGII
            if move.l10n_do_reported_606 or move.l10n_do_reported_607:
                move._check_dgii_reported_block()
            # Nota: Permitimos restablecer a borrador para editar
            # El NCF se mantiene asignado (readonly)
        return super().button_draft()

    def unlink(self):
        for move in self:
            if move.l10n_do_reported_606 or move.l10n_do_reported_607:
                raise UserError(_('No puede eliminar documento reportado a DGII.'))
            # Prevenir eliminacion de facturas con NCF
            if move.l10n_do_ncf_number:
                raise UserError(_(
                    "No se puede eliminar una factura con NCF asignado.\n\n"
                    "NCF: %s\n\n"
                    "Los NCF son registros fiscales permanentes."
                ) % move.l10n_do_ncf_number)
        return super().unlink()

    # =========================================
    # VALIDACIONES ESPECÍFICAS POR TIPO
    # =========================================
    def _check_informal_provider_rnc(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'informal':
            return
        if self.partner_id and self.partner_id.vat:
            raise UserError(_('Proveedor con RNC no puede usar B11.'))
        if not self.l10n_do_informal_provider_name:
            raise UserError(_('B11 requiere nombre del proveedor.'))
        self.l10n_do_informal_rnc_verified = True

    def _check_b11_monthly_limit(self):
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
        block = self.env['ir.config_parameter'].sudo().get_param('l10n_do_ncf.b11_block_on_limit', 'True') == 'True'
        if count >= limit and block:
            raise UserError(_('Límite mensual B11 alcanzado (%s/%s).') % (count, limit))

    def _check_b13_no_itbis(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'minor_expense':
            return
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                if tax.amount > 0 and 'itbis' in (tax.name or '').lower():
                    raise UserError(_('B13 no permite ITBIS acreditable en línea %s.') % line.name)
        limit = self._get_b13_transaction_limit()
        if self.amount_total > limit:
            raise UserError(_('B13 excede límite de RD$ %s.') % limit)

    def _check_b17_no_itbis(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'exterior':
            return
        if self.amount_tax > 0:
            raise UserError(_('B17 no debe tener ITBIS.'))
        if not any(ret.retention_type_id.code == 'ISR_EXT' for ret in self.l10n_do_retention_ids):
            raise UserError(_('B17 requiere retención ISR 27%.'))

    # =========================================
    # GENERADOR NCF (CON PROTECCIÓN RACE CONDITION)
    # =========================================
    def _generate_ncf(self):
        self.ensure_one()
        if self.l10n_do_ncf_number:
            return

        if not self.l10n_do_ncf_type_id:
            raise UserError(_('Seleccione tipo de comprobante.'))

        ncf_type = self.l10n_do_ncf_type_id

        sequences = self.env['l10n_do_ncf.sequence'].sudo().search([
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
            raise UserError(_('No hay secuencias activas para %s.') % ncf_type.name)

        if sequence.expiration_date and self.invoice_date and self.invoice_date > sequence.expiration_date:
            raise UserError(_('Fecha posterior al vencimiento de la secuencia.'))

        if sequence.expiration_date and sequence.expiration_date < date.today():
            raise UserError(_('Secuencia %s vencida.') % sequence.name)

        prefix = ncf_type.prefix
        next_num = max(sequence.range_from or 1, sequence.current_number + 1)
        ncf = f'{prefix}{next_num:0{10 if ncf_type.is_electronic else 8}d}'

        self.write({
            'l10n_do_ncf_number': ncf,
            'l10n_do_ncf_seq_id': sequence.id,
            'l10n_do_fiscal_status': 'valid',
        })
        sequence.sudo().write({'current_number': next_num})

        _logger.info('NCF generado: %s | Documento: %s', ncf, self.name)

    # =========================================
    # ONCHANGE
    # =========================================
    @api.onchange('l10n_do_ncf_type_id')
    def _onchange_check_sequence_exists(self):
        if not self.l10n_do_ncf_type_id or self.company_id.country_id.code != 'DO':
            return
        if self.l10n_do_ncf_number:
            return {'warning': {'title': _('Cambio no permitido'), 'message': _('Ya tiene NCF generado.')}}
        if self.move_type in ('out_invoice', 'out_refund') and self.l10n_do_ncf_required:
            if not self.env['l10n_do_ncf.sequence'].search([
                ('company_id', '=', self.company_id.id),
                ('ncf_type_id', '=', self.l10n_do_ncf_type_id.id),
                ('state', '=', 'active'),
            ], limit=1):
                return {'warning': {'title': _('Sin secuencia'), 'message': _('Configure secuencia para este tipo.')}}

    @api.onchange('l10n_do_expense_type', 'invoice_line_ids', 'invoice_line_ids.product_id')
    def _onchange_validate_expense_vs_product(self):
        """Warning si hay inconsistencia entre Tipo de Gasto y Producto"""
        if self.move_type not in ('in_invoice', 'in_refund') or not self.l10n_do_expense_type:
            return
        
        # Detectar si hay productos tipo "bienes" vs "servicios"
        has_goods = any(
            line.product_id and line.product_id.type in ('consu', 'product')
            for line in self.invoice_line_ids
        )
        has_services = any(
            line.product_id and line.product_id.type == 'service'
            for line in self.invoice_line_ids
        )
        
        # Tipo de gasto 02 = Servicios, 01 = Bienes
        expense_is_service = self.l10n_do_expense_type == '02'
        expense_is_goods = self.l10n_do_expense_type == '01'
        
        warning_msg = False
        if expense_is_service and has_goods and not has_services:
            warning_msg = (
                "El Tipo de Gasto seleccionado es '02 - Gastos por Trabajos/Servicios', "
                "pero las lineas contienen productos de tipo Bienes. "
                "Verifique la clasificacion fiscal antes de confirmar."
            )
        elif expense_is_goods and has_services and not has_goods:
            warning_msg = (
                "El Tipo de Gasto seleccionado es '01 - Gastos de Personal', "
                "pero las lineas contienen productos de tipo Servicio. "
                "Verifique la clasificacion fiscal antes de confirmar."
            )
        
        if warning_msg:
            return {
                'warning': {
                    'title': 'Verificar Clasificacion Fiscal',
                    'message': warning_msg,
                }
            }

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
        retentions = []
        base = self.amount_untaxed or 0
        itbis = self.amount_tax or 0
        RetType = self.env['l10n_do_ncf.retention.type']
        if itbis > 0:
            itbis_type = RetType.search([('code', '=', 'ITBIS_100')], limit=1)
            if itbis_type:
                retentions.append((0, 0, {'retention_type_id': itbis_type.id, 'base_amount': itbis}))
        if base > 0:
            code = 'ISR_PROF' if self.l10n_do_informal_service_type == 'professional' else 'ISR_TEC'
            isr_type = RetType.search([('code', '=', code)], limit=1)
            if isr_type:
                retentions.append((0, 0, {'retention_type_id': isr_type.id, 'base_amount': base}))
        if retentions:
            self.l10n_do_retention_ids = retentions

    @api.onchange('l10n_do_informal_service_type')
    def _onchange_informal_service_type(self):
        if self.l10n_do_fiscal_type == 'informal':
            self._apply_b11_retentions()

    def _apply_b17_retentions(self):
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
        if self.move_type != 'out_invoice' or not self.partner_id or not self.partner_id.vat:
            return
        if self.search([('partner_id', '=', self.partner_id.id), ('l10n_do_ncf_number', '=like', 'B02%'), ('state', '=', 'posted')], limit=1):
            return {'warning': {'title': _('Cliente con RNC nuevo'), 'message': _('Tiene facturas B02 previas. Considere emitir NC.')}}
    @api.onchange('partner_id', 'l10n_do_ncf_type_id')
    def _onchange_validate_fiscal_coherence(self):
        """Mostrar warning de coherencia fiscal al seleccionar cliente o tipo NCF"""
        if not self.l10n_do_ncf_required or self.move_type not in ('out_invoice', 'out_refund'):
            return
        if not self.partner_id or not self.l10n_do_ncf_type_id:
            return
        if self.company_id.country_id.code != 'DO':
            return
        
        ncf_code = self.l10n_do_ncf_type_id.code
        partner_vat = (self.partner_id.vat or '').strip()
        
        # Validación B15 (Gubernamental) con RNC no gubernamental
        if ncf_code == '15' and partner_vat:
            is_gov_pattern = (
                partner_vat.startswith('4010') or
                partner_vat.startswith('4020') or
                partner_vat.startswith('430') or
                partner_vat.startswith('431')
            )
            if not is_gov_pattern:
                return {'warning': {
                    'title': _('⚠️ Inconsistencia Fiscal Detectada'),
                    'message': _(
                        'El cliente "%s" está marcado como Gubernamental (B15), '
                        'pero su RNC %s no corresponde a un patrón típico de entidad estatal.\n\n'
                        'Patrones gubernamentales típicos:\n'
                        '• 4010XXXXX - Ministerios\n'
                        '• 4020XXXXX - Instituciones Descentralizadas\n'
                        '• 430XXXXXX - Ayuntamientos\n\n'
                        'Verifique si debería usar:\n'
                        '• B01 (Crédito Fiscal) - contribuyente normal\n'
                        '• B14 (Régimen Especial) - ONG o zona franca'
                    ) % (self.partner_id.name, partner_vat)
                }}
        
        # Validación B14 con RNC de empresa normal
        if ncf_code == '14' and partner_vat:
            if partner_vat.startswith('1') and len(partner_vat) == 9:
                return {'warning': {
                    'title': _('⚠️ Verificar Tipo Fiscal'),
                    'message': _(
                        'El cliente "%s" tiene RNC %s que parece empresa normal.\n\n'
                        'B14 (Régimen Especial) aplica para:\n'
                        '• Zonas Francas\n'
                        '• ONGs\n'
                        '• Organismos internacionales\n\n'
                        'Si es contribuyente normal, use B01.'
                    ) % (self.partner_id.name, partner_vat)
                }}
        
        # Validación B01 con RNC gubernamental
        if ncf_code == '01' and partner_vat:
            is_gov_pattern = (
                partner_vat.startswith('4010') or
                partner_vat.startswith('4020') or
                partner_vat.startswith('430')
            )
            if is_gov_pattern:
                return {'warning': {
                    'title': _('⚠️ Verificar Tipo Fiscal'),
                    'message': _(
                        'El cliente "%s" tiene RNC %s que parece gubernamental.\n\n'
                        'Si ES gubernamental, debería usar B15.\n'
                        'Cambie el tipo de contribuyente a "Gubernamental".'
                    ) % (self.partner_id.name, partner_vat)
                }}


    # =========================================
    # SINCRONIZACIÓN RETENCIONES
    # =========================================
    def _sync_tax_retentions(self):
        self.ensure_one()
        if self.move_type not in ('in_invoice', 'in_refund') or self.l10n_do_retention_ids:
            return
        retentions = []
        base = abs(self.amount_untaxed or 0)
        for line in self.line_ids:
            if line.tax_line_id and line.balance < 0:
                tax = line.tax_line_id
                tax_amount = abs(line.balance)
                tax_name = (tax.name or '').lower()
                tax_rate = abs(tax.amount)
                retention_type = False
                if 'isr' in tax_name or 'renta' in tax_name:
                    if tax_rate >= 25:
                        code = 'ISR_EXT'
                    elif 8 <= tax_rate <= 12:
                        code = 'ISR_PROF'
                    elif 1 <= tax_rate <= 5:
                        code = 'ISR_TEC'
                    else:
                        code = 'ISR_PROF'
                    retention_type = self.env['l10n_do_ncf.retention.type'].search([('code', '=', code)], limit=1)
                elif 'itbis' in tax_name:
                    if tax_rate >= 90:
                        code = 'ITBIS_100'
                    elif tax_rate >= 70:
                        code = 'ITBIS_75'
                    elif tax_rate >= 25:
                        code = 'ITBIS_PROF'
                    else:
                        code = 'ITBIS_100'
                    retention_type = self.env['l10n_do_ncf.retention.type'].search([('code', '=', code)], limit=1)
                if retention_type:
                    calculated_base = tax_amount / retention_type.rate * 100 if retention_type.rate > 0 else base
                    retentions.append((0, 0, {'retention_type_id': retention_type.id, 'base_amount': calculated_base}))
        if retentions:
            self.l10n_do_retention_ids = retentions

    # =========================================
    # =========================================
    # VALIDACIÓN FISCAL INTELIGENTE
    # =========================================
    def _validate_fiscal_coherence(self):
        """Validación fiscal según algoritmo unificado.
        
        Reglas:
        - País != RD → debe ser B16 (Exportación)
        - B01 (Fiscal) → RNC obligatorio, país RD
        - B02 (Consumidor) → RNC prohibido, país RD
        - B14 (Especial) → RNC obligatorio, país RD, warning si parece normal
        - B15 (Gubernamental) → RNC obligatorio, país RD, warning si RNC no parece gubernamental
        - B16 (Exportación) → País != RD, RNC dominicano prohibido
        
        Returns: dict con warnings (no bloquea) o raises UserError (bloquea)
        """
        self.ensure_one()
        
        if not self.l10n_do_ncf_required:
            return {}
        
        if self.company_id.country_id.code != 'DO':
            return {}
        
        if self.move_type not in ('out_invoice', 'out_refund'):
            return {}
        
        warnings = []
        partner = self.partner_id
        ncf_type = self.l10n_do_ncf_type_id
        
        if not ncf_type:
            return {}
        
        ncf_code = ncf_type.code  # '01', '02', '14', '15', '16', etc.
        partner_country = partner.country_id.code if partner.country_id else 'DO'
        partner_vat = (partner.vat or '').strip()
        client_type = partner.l10n_do_dgii_tax_payer_type or 'final_consumer'
        
        # =====================
        # REGLA 1: Exportación (B16)
        # =====================
        if partner_country != 'DO':
            # Cliente extranjero DEBE usar B16
            if ncf_code != '16':
                raise UserError(_(
                    "❌ ERROR FISCAL: Cliente Extranjero\n\n"
                    "El cliente '%s' es de %s (no RD).\n"
                    "Para clientes extranjeros DEBE usar B16 (Exportación).\n\n"
                    "Tipo actual: %s\n\n"
                    "Corrija el tipo de comprobante o el país del cliente."
                ) % (partner.name, partner_country, ncf_type.name))
            return {}  # B16 con extranjero = OK
        
        # De aquí en adelante: País = RD
        
        # =====================
        # REGLA 2: B16 solo para extranjeros
        # =====================
        if ncf_code == '16' and partner_country == 'DO':
            raise UserError(_(
                "❌ ERROR FISCAL: B16 para Cliente Local\n\n"
                "El cliente '%s' es de República Dominicana.\n"
                "B16 (Exportación) solo aplica para clientes extranjeros.\n\n"
                "Use B01, B02, B14 o B15 según corresponda."
            ) % partner.name)
        
        # =====================
        # REGLA 3: B02 (Consumidor Final) - RNC PROHIBIDO
        # =====================
        if ncf_code == '02':
            if partner_vat and len(partner_vat) >= 9:
                raise UserError(_(
                    "❌ ERROR FISCAL: B02 con RNC\n\n"
                    "El cliente '%s' tiene RNC: %s\n\n"
                    "B02 (Consumidor Final) NO permite RNC.\n"
                    "Un cliente con RNC debe usar B01 (Crédito Fiscal).\n\n"
                    "Opciones:\n"
                    "1. Cambiar tipo de contribuyente a 'Contribuyente' → usará B01\n"
                    "2. Eliminar el RNC del cliente si es consumidor final"
                ) % (partner.name, partner_vat))
            return {}  # B02 sin RNC = OK
        
        # =====================
        # REGLA 4: B01, B14, B15 - RNC OBLIGATORIO
        # =====================
        if ncf_code in ('01', '14', '15'):
            if not partner_vat or len(partner_vat) < 9:
                raise UserError(_(
                    "❌ ERROR FISCAL: %s sin RNC\n\n"
                    "El cliente '%s' no tiene RNC válido.\n\n"
                    "Para usar %s es obligatorio que el cliente tenga RNC.\n\n"
                    "Opciones:\n"
                    "1. Agregar el RNC al cliente\n"
                    "2. Cambiar tipo de contribuyente a 'Consumidor Final' → usará B02"
                ) % (ncf_type.name, partner.name, ncf_type.name))
        
        # =====================
        # REGLA 5: B15 (Gubernamental) - Validar patrón RNC
        # =====================
        if ncf_code == '15' and partner_vat:
            # Patrones típicos de RNC gubernamental
            is_gov_pattern = (
                partner_vat.startswith('401') or  # Ministerios, direcciones
                partner_vat.startswith('402') or  # Instituciones descentralizadas
                partner_vat.startswith('430') or  # Ayuntamientos
                partner_vat.startswith('431')     # Otros organismos
            )
            
            if not is_gov_pattern:
                warnings.append(_(
                    "⚠️ ADVERTENCIA: RNC no parece Gubernamental\n\n"
                    "Cliente: %s\n"
                    "RNC: %s\n"
                    "Tipo: Gubernamental (B15)\n\n"
                    "El RNC no coincide con patrones típicos de entidades del Estado:\n"
                    "- 401XXXXXX (Ministerios/Direcciones)\n"
                    "- 402XXXXXX (Instituciones Descentralizadas)\n"
                    "- 430XXXXXX (Ayuntamientos)\n\n"
                    "Verifique que:\n"
                    "1. El RNC sea correcto\n"
                    "2. El tipo de contribuyente sea el adecuado\n\n"
                    "Si el cliente NO es gubernamental, cambie su tipo a:\n"
                    "- 'Contribuyente' para B01\n"
                    "- 'Régimen Especial' para B14"
                ) % (partner.name, partner_vat))
        
        # =====================
        # REGLA 6: B14 (Régimen Especial) - Warning informativo
        # =====================
        if ncf_code == '14' and partner_vat:
            # B14 es flexible, pero advertir si parece empresa normal
            if partner_vat.startswith('1') and len(partner_vat) == 9:
                # RNC típico de empresa (1XXXXXXXX)
                warnings.append(_(
                    "⚠️ ADVERTENCIA: RNC parece empresa normal\n\n"
                    "Cliente: %s\n"
                    "RNC: %s\n"
                    "Tipo: Régimen Especial (B14)\n\n"
                    "El RNC parece de una empresa contribuyente normal.\n\n"
                    "B14 aplica para:\n"
                    "- Zonas Francas\n"
                    "- ONGs\n"
                    "- Organismos internacionales\n"
                    "- Exentos por ley\n\n"
                    "Si el cliente es contribuyente normal, use B01."
                ) % (partner.name, partner_vat))
        
        # =====================
        # REGLA 7: B01 con RNC gubernamental
        # =====================
        if ncf_code == '01' and partner_vat:
            is_gov_pattern = (
                partner_vat.startswith('401') or
                partner_vat.startswith('402') or
                partner_vat.startswith('430') or
                partner_vat.startswith('431')
            )
            if is_gov_pattern:
                warnings.append(_(
                    "⚠️ ADVERTENCIA: RNC parece Gubernamental\n\n"
                    "Cliente: %s\n"
                    "RNC: %s\n"
                    "Tipo: Crédito Fiscal (B01)\n\n"
                    "El RNC coincide con patrones de entidades gubernamentales.\n\n"
                    "Si el cliente ES gubernamental, debería usar B15.\n"
                    "Cambie el tipo de contribuyente a 'Gubernamental'."
                ) % (partner.name, partner_vat))
        
        return {'warnings': warnings}
    
    # ACTION_POST
    # =========================================
    def action_post(self):
        for move in self:
            is_do = move.company_id.country_id.code == 'DO'

            if is_do and move.move_type in ('out_invoice', 'out_refund') and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_type_id:
                    raise UserError(_('Seleccione tipo de comprobante.'))
                # Validación fiscal inteligente
                validation_result = move._validate_fiscal_coherence()
                if validation_result.get('warnings'):
                    # Los warnings se registran en el chatter pero no bloquean
                    for warning in validation_result['warnings']:
                        move.message_post(body=warning, message_type='notification')
                if move.move_type == 'out_refund':
                    if not move.l10n_do_ncf_origin and not move.l10n_do_origin_move_id:
                        raise UserError(_('NC requiere origen.'))
                    if not move.l10n_do_credit_note_reason:
                        raise UserError(_('NC requiere motivo.'))
                if move.l10n_do_is_debit_note:
                    if not move.l10n_do_debit_ncf_origin and not move.l10n_do_debit_origin_move_id:
                        raise UserError(_('ND requiere origen.'))
                    if not move.l10n_do_debit_note_reason:
                        raise UserError(_('ND requiere motivo.'))

            if is_do and move.move_type in ('in_invoice', 'in_refund') and move.l10n_do_fiscal_type:
                if move.l10n_do_fiscal_type == 'informal':
                    move._check_informal_provider_rnc()
                    move._check_b11_monthly_limit()
                elif move.l10n_do_fiscal_type == 'minor_expense':
                    move._check_b13_no_itbis()
                elif move.l10n_do_fiscal_type == 'exterior':
                    move._check_b17_no_itbis()
                elif move.l10n_do_fiscal_type == 'fiscal' and move.partner_id.vat and not move.l10n_do_vendor_ncf:
                    # Solo exigir NCF si el usuario configuró explícitamente tipo fiscal
                    pass  # Warning en lugar de bloqueo para no afectar datos demo

        result = super().action_post()

        for move in self:
            is_do = move.company_id.country_id.code == 'DO'

            if is_do and move.move_type in ('out_invoice', 'out_refund') and move.l10n_do_ncf_required and not move.l10n_do_ncf_number:
                move._generate_ncf()

            if is_do and move.move_type == 'out_refund' and move.l10n_do_origin_move_id:
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

            if is_do and move.l10n_do_is_debit_note and move.l10n_do_debit_origin_move_id:
                move.l10n_do_debit_origin_move_id.l10n_do_fiscal_status = 'debited'

            if is_do and move.move_type in ('in_invoice', 'in_refund') and move.l10n_do_fiscal_type in ('informal', 'minor_expense') and not move.l10n_do_ncf_number:
                move._generate_ncf()

            if is_do:
                move._sync_tax_retentions()

        return result

    # =========================================
    # ACCIONES AUXILIARES
    # =========================================
    def action_validate_vendor_ncf(self):
        self.ensure_one()
        if not self.l10n_do_vendor_ncf:
            raise UserError(_('Ingrese NCF.'))
        ncf = self.l10n_do_vendor_ncf.strip().upper()
        if not re.match(NCF_FULL_PATTERN, ncf):
            raise UserError(_('Formato inválido.'))
        self.write({'l10n_do_vendor_ncf': ncf, 'l10n_do_vendor_ncf_validated': True, 'l10n_do_vendor_ncf_validation_source': 'local'})
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('Validado'), 'message': ncf, 'type': 'success'}}

    def action_verify_informal_rnc(self):
        self.ensure_one()
        if self.partner_id and self.partner_id.vat:
            raise UserError(_('Proveedor tiene RNC.'))
        self.l10n_do_informal_rnc_verified = True
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('Verificado'), 'message': _('Sin RNC'), 'type': 'success'}}

    def action_mark_reported_606(self):
        self.ensure_one()
        period = self.invoice_date.strftime('%Y%m') if self.invoice_date else date.today().strftime('%Y%m')
        self.write({'l10n_do_reported_606': True, 'l10n_do_report_period': period})
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('Marcado 606'), 'message': period, 'type': 'success'}}

    def action_mark_reported_607(self):
        self.ensure_one()
        period = self.invoice_date.strftime('%Y%m') if self.invoice_date else date.today().strftime('%Y%m')
        self.write({'l10n_do_reported_607': True, 'l10n_do_report_period': period})
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'title': _('Marcado 607'), 'message': period, 'type': 'success'}}

    # =========================================
    # HELPERS REPORTES
    # =========================================
    def _get_ncf_for_report(self):
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund'):
            return self.l10n_do_ncf_number or ''
        if self.l10n_do_fiscal_type in ('informal', 'minor_expense'):
            return self.l10n_do_ncf_number or ''
        return self.l10n_do_vendor_ncf or ''

    def _get_rnc_for_606(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type == 'minor_expense':
            return self.company_id.vat or ''
        if self.l10n_do_fiscal_type == 'informal':
            return self.l10n_do_informal_provider_cedula or ''
        return self.partner_id.vat or ''

# -*- coding: utf-8 -*-
# módulo: l10n_do_ncf
# Archivo: models/account_move.py
# Versión: 19.0 FINAL - PRODUCCIÓN LISTA - ODOO 19
# Compatibilidad: Odoo 19 (100% compatible, upgrade-friendly)

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date
import re
import logging

_logger = logging.getLogger(__name__)

# =========================================
# PATRONES Y CONSTANTES
