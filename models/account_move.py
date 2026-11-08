# -*- coding: utf-8 -*-
# módulo: l10n_do_ncf
# Archivo: models/account_move.py
# Versión: 19.0 FINAL - PRODUCCIÓN LISTA - ODOO 19
# Compatibilidad: Odoo 19 (100% compatible, upgrade-friendly)

from odoo import Command, models, fields, api, _
from odoo.exceptions import RedirectWarning, ValidationError, UserError
from datetime import date
import re
import logging

from .dgii_609_codes import (
    DETALLE_SERVICIO as DETALLE_SERVICIO_609,
    TIPO_SERVICIO as TIPO_SERVICIO_609,
)

_logger = logging.getLogger(__name__)

# =========================================
# PATRONES Y CONSTANTES
# =========================================
NCF_PATTERN = r'^B(01|02|03|04|11|12|13|14|15|16|17)\d{8}$'
ECF_PATTERN = r'^E(31|32|33|34|41|42|43|44|45|46|47)\d{10}$'

# Prefijos de RNC típicos de entidades del Estado. Solo se usan para
# ADVERTIR (nunca bloquean): 401 ministerios y direcciones, 402 instituciones
# descentralizadas, 430 ayuntamientos y 431 otros organismos. El 430 es
# ambiguo (ver res_partner.py), por eso es solo un aviso.
GOV_RNC_PREFIXES = ('401', '402', '430', '431')
NCF_FULL_PATTERN = r'^(B(01|02|03|04|11|12|13|14|15|16|17)\d{8}|E(31|32|33|34|41|42|43|44|45|46|47)\d{10})$'

# Tipos electrónicos de venta que siguen las mismas reglas de coherencia
# fiscal que su equivalente en papel (cliente extranjero, RNC obligatorio,
# patrón gubernamental). Un conector de e-CF convierte 14/15/16 en 44/45/46.
COHERENCE_PAPER_CODE = {'44': '14', '45': '15', '46': '16'}

# "Tipo de compra" de la factura de proveedor, en el lenguaje del usuario. Los
# tres últimos son tipos fiscales (l10n_do_fiscal_type) cuyo comprobante emite
# la empresa (B11/E41, B13/E43, B17/E47).
PURCHASE_KINDS = [
    ('vendor', 'Con comprobante del proveedor'),
    ('informal', 'Proveedor informal'),
    ('minor_expense', 'Gastos menores'),
    ('exterior', 'Pago al exterior'),
]
PURCHASE_KIND_FISCAL_TYPES = ('informal', 'minor_expense', 'exterior')


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Encontrar la factura escribiendo su NCF o e-NCF (p. ej. al elegir el
    # origen de una nota de débito).
    _rec_names_search = ['name', 'partner_id.name', 'ref', 'l10n_do_ncf_number']

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

    l10n_do_ncf_required = fields.Boolean(
        string='Requiere NCF',
        compute='_compute_l10n_do_ncf_required',
        store=True,
        readonly=False,
        help='Se activa automaticamente en facturas y notas de credito de '
             'venta de companias dominicanas. Puede desmarcarse a mano en '
             'casos excepcionales, antes de postear.',
    )

    @api.depends('move_type', 'company_id')
    def _compute_l10n_do_ncf_required(self):
        """Toda factura / nota de credito de venta de una compania
        dominicana requiere NCF.

        MOTIVO: antes era un Boolean manual con default=False y SOLO el POS
        lo activaba (pos_order.py::_prepare_invoice_vals). Por eso las
        facturas creadas desde e-commerce, Ventas, CRM o Contabilidad
        nacian sin NCF: no entraban en las condiciones de action_post ni de
        _generate_ncf, que dependen de este flag.

        readonly=False mantiene el valor editable: la decision fiscal final
        sigue siendo del usuario.
        """
        for move in self:
            move.l10n_do_ncf_required = (
                move.company_id.country_id.code == 'DO'
                and move.move_type in ('out_invoice', 'out_refund')
            )

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
    ], string='Estado Fiscal', default='draft', tracking=True,
        # Una copia es un documento nuevo: nace en Borrador, no hereda
        # "Válido", "Anulado" ni "Rechazado DGII" del original.
        copy=False)

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

    l10n_do_is_debit_note = fields.Boolean(string='Es Nota de Débito', default=False, copy=False)
    l10n_do_debit_note_reason = fields.Selection([
        ('01', '01 - Intereses por mora'),
        ('02', '02 - Gastos adicionales'),
        ('03', '03 - Ajuste precio al alza'),
        ('04', '04 - Otros cargos'),
    ], string='Motivo ND', copy=False)
    # Solo facturas de cliente confirmadas del mismo cliente y compañía. Sin
    # este filtro se podía elegir un borrador, una compra o la propia nota, y
    # escribir el e-NCF ofrecía "Crear", que fabricaba un asiento vacío.
    l10n_do_debit_origin_move_id = fields.Many2one(
        'account.move', string='Factura Origen ND', copy=False, index='btree_not_null',
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),"
               " ('l10n_do_is_debit_note', '=', False), ('company_id', '=', company_id),"
               " ('commercial_partner_id', '=', commercial_partner_id)]")
    l10n_do_debit_ncf_origin = fields.Char(string='NCF Afectado ND', copy=False)
    l10n_do_debit_note_ids = fields.One2many(
        'account.move', 'l10n_do_debit_origin_move_id', string='Notas de débito')
    l10n_do_debit_note_count = fields.Integer(
        string='Notas de débito', compute='_compute_l10n_do_debit_note_count')
    # account_debit_note trae su propio botón "Nota de débito" y su botón
    # inteligente: si está instalado, se usan esos y se ocultan los del módulo.
    l10n_do_std_debit_note = fields.Boolean(compute='_compute_l10n_do_debit_note_count')
    l10n_do_can_debit_note = fields.Boolean(compute='_compute_l10n_do_debit_note_count')

    @api.depends('l10n_do_debit_note_ids', 'state', 'move_type', 'l10n_do_is_debit_note')
    def _compute_l10n_do_debit_note_count(self):
        std = 'debit_origin_id' in self._fields
        for move in self:
            move.l10n_do_debit_note_count = len(move.l10n_do_debit_note_ids)
            move.l10n_do_std_debit_note = std
            move.l10n_do_can_debit_note = (
                move.move_type == 'out_invoice' and move.state == 'posted'
                and not move.l10n_do_is_debit_note
                and move.company_id.country_id.code == 'DO')

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

    # En compras se calcula a partir del proveedor (informal, del exterior o el
    # contacto "Gastos menores") y se puede cambiar; el usuario lo ve como
    # "Tipo de compra" (l10n_do_purchase_kind). En ventas no se usa.
    l10n_do_fiscal_type = fields.Selection([
        ('fiscal', 'Compra Fiscal'),
        ('informal', 'B11 - Compra Informal'),
        ('minor_expense', 'B13 - Gasto Menor'),
        ('exterior', 'B17 - Pago Exterior'),
        ('special', 'B14 - Régimen Especial'),
        ('governmental', 'B15 - Gubernamental'),
    ], string='Tipo Fiscal', tracking=True,
        compute='_compute_l10n_do_fiscal_type', store=True, readonly=False, precompute=True)

    l10n_do_purchase_kind = fields.Selection(
        PURCHASE_KINDS, string='Tipo de compra',
        compute='_compute_l10n_do_purchase_kind',
        inverse='_inverse_l10n_do_purchase_kind',
        help='Con comprobante del proveedor: compra normal, el NCF o e-NCF lo da el '
             'proveedor.\nProveedor informal: persona física sin comprobante; lo emite '
             'la empresa.\nGastos menores: peajes, parqueos y gastos sin comprobante.\n'
             'Pago al exterior: proveedor fuera del país.\n\n'
             'Se elige solo según el proveedor y se puede cambiar.')

    l10n_do_purchase_kind_manual = fields.Boolean(
        string='Tipo de compra elegido a mano', copy=False,
        help='El usuario eligió el tipo de compra: ya no se recalcula con el proveedor '
             'ni con las líneas.')

    # Las líneas cuentan para el proveedor extranjero: solo los servicios sin
    # ITBIS son un pago al exterior (ver _l10n_do_partner_fiscal_type).
    @api.depends('partner_id', 'move_type', 'invoice_line_ids.product_id',
                 'invoice_line_ids.display_type', 'l10n_do_purchase_kind_manual')
    def _compute_l10n_do_fiscal_type(self):
        for move in self:
            current = move.l10n_do_fiscal_type
            if (move.move_type not in ('in_invoice', 'in_refund')
                    or move.state == 'posted' or move.l10n_do_ncf_number
                    or move.l10n_do_is_vendor_debit_note
                    or (move.l10n_do_purchase_kind_manual and current)):
                # Un comprobante confirmado o emitido no cambia de tipo.
                move.l10n_do_fiscal_type = current or 'fiscal'
                continue
            move.l10n_do_fiscal_type = move._l10n_do_partner_fiscal_type(current)

    def _l10n_do_partner_fiscal_type(self, current=False):
        """Tipo fiscal de compra que corresponde al proveedor de la factura."""
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner:
            return current or 'fiscal'
        if partner == self.company_id.l10n_do_minor_expense_partner_id:
            return 'minor_expense'
        if partner.l10n_do_is_informal_supplier:
            return 'informal'
        if partner.country_id and partner.country_id.code != 'DO' and self._l10n_do_is_foreign_service():
            return 'exterior'
        # Un régimen especial o gubernamental puesto a mano se respeta.
        return current if current in ('special', 'governmental') else 'fiscal'

    def _l10n_do_is_foreign_service(self):
        """True si la compra a un proveedor extranjero es un pago al exterior.

        La E47/B17 es para "pagos de rentas gravadas de fuentes dominicanas a
        Personas Físicas o Jurídicas no residentes en el país" (DGII, Guía del
        Contribuyente No. 5, pág. 5): servicios, no mercancía. Y no lleva ITBIS
        (instructivo del 606: el B17 no llena las casillas de ITBIS). Por eso
        solo cuando TODAS las líneas son productos de tipo Servicio y ninguna
        tiene ITBIS. Un bien, una línea con ITBIS o una línea sin producto (no
        se sabe qué es) dejan la compra "Con comprobante del proveedor": por
        ejemplo una importación de mercancía, cuyo tratamiento en el 606 aún no
        está definido.
        """
        self.ensure_one()
        lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        if not lines:
            return False
        for line in lines:
            if not line.product_id or line.product_id.type != 'service':
                return False
            if any(tax.amount > 0 and (tax.dgii_tax_kind == 'itbis' or (
                    not tax.dgii_tax_kind and tax.amount in (18.0, 16.0)))
                   for tax in line.tax_ids):
                return False
        return True

    @api.depends('l10n_do_fiscal_type')
    def _compute_l10n_do_purchase_kind(self):
        for move in self:
            kind = move.l10n_do_fiscal_type
            move.l10n_do_purchase_kind = kind if kind in PURCHASE_KIND_FISCAL_TYPES else 'vendor'

    def _inverse_l10n_do_purchase_kind(self):
        for move in self:
            fiscal_type = move._l10n_do_fiscal_type_for_kind(move.l10n_do_purchase_kind)
            if fiscal_type != move.l10n_do_fiscal_type:
                move.l10n_do_fiscal_type = fiscal_type
            move._l10n_do_mark_kind_manual()

    def _l10n_do_mark_kind_manual(self):
        """Marca el tipo de compra como elegido a mano si no es el que daría
        la regla automática."""
        for move in self:
            if (move.move_type in ('in_invoice', 'in_refund') and move.state == 'draft'
                    and not move.l10n_do_purchase_kind_manual
                    and move.l10n_do_fiscal_type
                    and move.l10n_do_fiscal_type != move._l10n_do_partner_fiscal_type(
                        move.l10n_do_fiscal_type)):
                move.l10n_do_purchase_kind_manual = True

    def _l10n_do_fiscal_type_for_kind(self, kind):
        self.ensure_one()
        if kind in PURCHASE_KIND_FISCAL_TYPES:
            return kind
        current = self.l10n_do_fiscal_type
        return current if current in ('special', 'governmental') else 'fiscal'

    @api.onchange('l10n_do_purchase_kind')
    def _onchange_l10n_do_purchase_kind(self):
        if self.move_type not in ('in_invoice', 'in_refund') or not self.l10n_do_purchase_kind:
            return
        fiscal_type = self._l10n_do_fiscal_type_for_kind(self.l10n_do_purchase_kind)
        # Solo es "a mano" si el usuario eligió algo distinto de la regla (este
        # onchange también corre cuando el tipo cambia solo con el proveedor).
        if fiscal_type != self._l10n_do_partner_fiscal_type(self.l10n_do_fiscal_type):
            self.l10n_do_purchase_kind_manual = True
        self.l10n_do_fiscal_type = fiscal_type
        if self.l10n_do_purchase_kind == 'minor_expense' and not self.partner_id:
            self.partner_id = self.company_id._l10n_do_minor_expense_partner()
        self._l10n_do_apply_retention_taxes()

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
    # Clasificación anterior, que no era la del Formato 609. Se conserva solo
    # como dato histórico: la migración 19.0.3.3.0 la pasó a los dos campos
    # oficiales donde la equivalencia era clara. No se usa en ningún reporte.
    l10n_do_exterior_service_type = fields.Selection([
        ('01', '01 - Servicios técnicos'),
        ('02', '02 - Servicios profesionales'),
        ('03', '03 - Regalías'),
        ('04', '04 - Intereses'),
        ('05', '05 - Dividendos'),
        ('06', '06 - Otros'),
    ], string='Tipo Servicio Exterior (anterior)', readonly=True)
    # Formato 609, columnas 5 y 6 (Norma General 07-2018, Anexo D).
    l10n_do_609_service_type = fields.Selection(
        TIPO_SERVICIO_609, string='Tipo de Servicio Adquirido (609)',
        help='Tabla de Tipos de Servicios del Formato 609 (Norma General 07-2018, Anexo D).')
    l10n_do_609_service_detail = fields.Selection(
        DETALLE_SERVICIO_609, string='Detalle del Servicio Adquirido (609)',
        help='Tabla de detalles del servicio adquirido del Formato 609. El primer '
             'dígito del detalle es su Tipo de Servicio.')

    @api.constrains('l10n_do_609_service_type', 'l10n_do_609_service_detail')
    def _check_609_service_detail(self):
        for move in self:
            detail = move.l10n_do_609_service_detail
            if detail and detail[0] != move.l10n_do_609_service_type:
                raise ValidationError(_(
                    'El detalle %(detail)s del Formato 609 no pertenece al Tipo de '
                    'Servicio %(type)s: el primer dígito del detalle es su tipo.',
                    detail=detail, type=move.l10n_do_609_service_type or _('(vacío)')))

    @api.onchange('l10n_do_609_service_type')
    def _onchange_609_service_type(self):
        detail = self.l10n_do_609_service_detail
        if detail and detail[0] != self.l10n_do_609_service_type:
            self.l10n_do_609_service_detail = False

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
    # Tipo de ingresos: el mismo dato para el e-CF (TipoIngresos, Formato e-CF
    # v1.0, pág. 7, campo 8) y el 607 (Norma General 07-2018, Anexo B, casilla
    # 5). Sin valor por defecto: si falta, el 607 lo marca como pendiente.
    l10n_do_ncf_is_electronic = fields.Boolean(related='l10n_do_ncf_type_id.is_electronic')

    l10n_do_ecf_income_type = fields.Selection(
        [
            ('1', '01 - Ingresos por operaciones (no financieros)'),
            ('2', '02 - Ingresos financieros'),
            ('3', '03 - Ingresos extraordinarios'),
            ('4', '04 - Ingresos por arrendamientos'),
            ('5', '05 - Ingresos por venta de activo depreciable'),
            ('6', '06 - Otros ingresos'),
        ],
        string='Tipo de ingreso',
    )

    # Anulación de un comprobante en papel (608, Norma General 07-2018, Anexo C).
    l10n_do_annulment_type = fields.Selection(
        [
            ('01', '01 - Deterioro de factura preimpresa'),
            ('02', '02 - Errores de impresión (factura preimpresa)'),
            ('03', '03 - Impresión defectuosa'),
            ('04', '04 - Corrección de la información'),
            ('05', '05 - Cambio de productos'),
            ('06', '06 - Devolución de productos'),
            ('07', '07 - Omisión de productos'),
            ('08', '08 - Errores en secuencias de NCF'),
            ('09', '09 - Por cese de operaciones'),
            ('10', '10 - Pérdida o hurto de talonarios'),
        ],
        string='Tipo de anulación (608)', copy=False, readonly=True,
    )
    l10n_do_annulment_date = fields.Date(string='Fecha de anulación', copy=False, readonly=True)

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
    ], string='Tipo Gasto',
        help='Tipo de bienes y servicios comprados del 606 (Norma General 07-2018, '
             'Anexo A, casilla 3). Si se deja vacío, se toma de la cuenta de gasto de '
             'las líneas (campo "Tipo 606" de la cuenta).')

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
    ], string='Tipo Compra (606)',
        help='Tipo de bienes y servicios comprados del 606 (Norma General 07-2018, '
             'Anexo A, casilla 3). Si se deja vacío, se toma de la cuenta de gasto de '
             'las líneas (campo "Tipo 606" de la cuenta).')

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
    # Una sola fuente de verdad: los impuestos de retención de las líneas
    # (los que generan asiento). Una factura confirmada antes de la versión
    # 19.0.4 conserva lo que se reportó desde la pestaña: "anterior".
    l10n_do_retention_legacy = fields.Boolean(
        string='Retenciones anteriores (pestaña)', copy=False, readonly=True,
        help='Factura confirmada antes de que las retenciones salieran de los impuestos '
             'de las líneas: sus reportes conservan lo que tenía la pestaña Retenciones.')
    l10n_do_retention_line_ids = fields.One2many(
        'account.move.line', compute='_compute_l10n_do_retention_line_ids',
        string='Retenciones del asiento')

    @api.depends('line_ids.tax_line_id', 'line_ids.amount_currency')
    def _compute_l10n_do_retention_line_ids(self):
        for move in self:
            move.l10n_do_retention_line_ids = move._l10n_do_retention_tax_lines()

    def _l10n_do_retention_tax_lines(self):
        """Líneas de impuesto del asiento que son retenciones (o percepciones)."""
        self.ensure_one()
        return self.line_ids.filtered(
            lambda l: l.tax_line_id and (
                l.tax_line_id.amount < 0
                or (l.tax_line_id.dgii_606_bucket or '').endswith('_percibido')))

    def _l10n_do_tax_retention_amounts(self):
        """{columna del 606: monto} de los impuestos de retención, en la moneda
        de la factura (False = impuesto sin tipo DGII)."""
        self.ensure_one()
        result = {}
        for line in self._l10n_do_retention_tax_lines():
            bucket = line.tax_line_id._l10n_do_retention_bucket()
            result[bucket] = result.get(bucket, 0.0) + abs(line.amount_currency)
        return result

    def _l10n_do_amount_before_retentions(self):
        """Total de la factura antes de las retenciones de sus impuestos, en la
        moneda de la factura (amount_total ya viene con ellas restadas)."""
        self.ensure_one()
        retained = sum(abs(line.amount_currency) for line in self.line_ids
                       if line.tax_line_id and line.tax_line_id.amount < 0)
        return abs(self.amount_total) + retained

    def _l10n_do_billed_tax_amount(self):
        """Impuestos facturados (los positivos), sin las retenciones."""
        self.ensure_one()
        return sum(abs(line.amount_currency) for line in self.line_ids
                   if line.tax_line_id and line.tax_line_id.amount > 0)

    def _l10n_do_isr_retention_lines(self):
        self.ensure_one()
        return self._l10n_do_retention_tax_lines().filtered(
            lambda l: l.tax_line_id._l10n_do_retention_bucket() == 'isr_retenido')

    def _l10n_do_isr_retention_type(self):
        """Casilla 17 del 606: la escrita en la factura, o la del impuesto de
        retención de ISR si todas sus líneas dicen la misma."""
        self.ensure_one()
        if self.l10n_do_tipo_retencion_isr:
            return self.l10n_do_tipo_retencion_isr
        if self.l10n_do_retention_legacy:
            return False
        types = set(self._l10n_do_isr_retention_lines().tax_line_id.mapped('dgii_isr_retention_type'))
        if len(types) == 1 and False not in types:
            return types.pop()
        if self.l10n_do_fiscal_type == 'exterior' and self._l10n_do_isr_retention_lines():
            # Lo que el módulo ponía antes en un pago al exterior.
            return '03'
        return False

    def _l10n_do_isr_retention_base(self):
        """Base del ISR retenido (renta presunta del 609), en la moneda de la factura."""
        self.ensure_one()
        if self.l10n_do_retention_legacy:
            lines = self.l10n_do_retention_ids.filtered(
                lambda r: r.retention_type_id.retention_type == 'isr'
                and not r.retention_type_id.is_perceived)
            return sum(lines.mapped('base_amount'))
        return self._l10n_do_tax_base_in_currency(self._l10n_do_isr_retention_lines())

    def _l10n_do_tax_base_in_currency(self, tax_lines):
        """Base de unas líneas de impuesto en la moneda de la factura
        (tax_base_amount viene en la moneda de la compañía)."""
        self.ensure_one()
        base = abs(sum(tax_lines.mapped('tax_base_amount')))
        if self.currency_id and self.currency_id != self.company_id.currency_id:
            base = self.currency_id.round(base * (self.invoice_currency_rate or 1.0))
        return base
    l10n_do_total_isr_retention = fields.Monetary(compute='_compute_retention_totals', store=True, currency_field='currency_id')
    l10n_do_total_itbis_retention = fields.Monetary(compute='_compute_retention_totals', store=True, currency_field='currency_id')
    l10n_do_gross_total = fields.Monetary(
        string='Total Bruto',
        compute='_compute_retention_totals',
        store=True,
        currency_field='currency_id',
        help='Total antes de retenciones (amount_total + retenciones)'
    )
    l10n_do_amount_to_pay = fields.Monetary(compute='_compute_retention_totals', store=True, currency_field='currency_id')

    # Retenciones de la pestaña frente a las del asiento (impuestos negativos
    # de las líneas). Solo las segundas crean el pasivo con la DGII y reducen
    # lo que se le debe al proveedor; los reportes (606, IR-17, e-CF) leen
    # primero la pestaña. Esto marca las facturas donde no cuadran.
    l10n_do_retention_check = fields.Selection([
        ('no_entry', 'Retención sin asiento'),
        ('mismatch', 'No coincide con el asiento'),
        ('untyped', 'Impuesto de retención sin tipo DGII'),
    ], string='Revisión de retenciones', compute='_compute_l10n_do_retention_check',
        store=True, index='btree_not_null')
    l10n_do_retention_gap = fields.Monetary(
        string='Monto por ajustar', compute='_compute_l10n_do_retention_check', store=True,
        currency_field='currency_id',
        help='Retención que está en la pestaña y no en el asiento (o la diferencia entre '
             'ambas), o la de un impuesto sin tipo DGII, que no llega al 606 ni al IR-17.')

    @api.depends('move_type', 'l10n_do_retention_ids.retention_amount',
                 'l10n_do_retention_ids.retention_type_id', 'l10n_do_retention_ids.tax_id',
                 'line_ids.tax_line_id', 'line_ids.amount_currency')
    def _compute_l10n_do_retention_check(self):
        for move in self:
            check, gap = move._l10n_do_retention_diagnosis()
            move.l10n_do_retention_check = check
            move.l10n_do_retention_gap = gap

    def _l10n_do_retention_amounts(self):
        """({'itbis', 'isr'} de la pestaña, {'itbis', 'isr'} del asiento, monto
        de impuestos de retención del asiento sin tipo DGII), en la moneda de
        la factura. Las percepciones no cuentan."""
        self.ensure_one()
        tab = {'itbis': 0.0, 'isr': 0.0}
        # Las filas copiadas de un impuesto (tax_id) son el asiento mismo.
        for retention in self.l10n_do_retention_ids.filtered(lambda r: not r.tax_id):
            kind = retention.retention_type_id
            if kind and not kind.is_perceived and kind.retention_type in tab:
                tab[kind.retention_type] += retention.retention_amount or 0.0
        entry = {'itbis': 0.0, 'isr': 0.0}
        untyped = 0.0
        for line in self.line_ids:
            tax = line.tax_line_id
            if not tax or tax.amount >= 0:
                continue
            amount = abs(line.amount_currency)
            if tax.dgii_retention_type in entry:
                entry[tax.dgii_retention_type] += amount
            else:
                untyped += amount
        return tab, entry, untyped

    def _l10n_do_retention_diagnosis(self):
        """(revisión, monto por ajustar) de las retenciones de la factura."""
        self.ensure_one()
        if self.move_type not in ('in_invoice', 'in_refund'):
            return False, 0.0
        tab, entry, untyped = self._l10n_do_retention_amounts()
        currency = self.currency_id or self.company_id.currency_id
        if not currency.is_zero(untyped):
            return 'untyped', currency.round(untyped)
        tab_total = sum(tab.values())
        if currency.is_zero(tab_total):
            return False, 0.0
        if currency.is_zero(sum(entry.values())):
            return 'no_entry', currency.round(tab_total)
        gap = sum(abs(tab[kind] - entry[kind]) for kind in tab)
        if currency.is_zero(gap):
            return False, 0.0
        return 'mismatch', currency.round(gap)

    def action_l10n_do_open_untyped_retention_taxes(self):
        """Botón del aviso: los impuestos de retención sin tipo DGII."""
        self.ensure_one()
        taxes = self.line_ids.tax_line_id.filtered(
            lambda t: t.amount < 0 and not t.dgii_retention_type)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Impuestos de retención sin tipo DGII'),
            'res_model': 'account.tax',
            'domain': [('id', 'in', taxes.ids)],
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
        }

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

            # El tipo fiscal decide el tipo de comprobante (B11, B13...): con
            # NCF asignado ya no se puede cambiar. Reescribir el mismo valor
            # sí se permite.
            if (
                move.l10n_do_ncf_number
                and 'l10n_do_fiscal_type' in vals
                and vals['l10n_do_fiscal_type'] != move.l10n_do_fiscal_type
            ):
                raise UserError(_(
                    '🔒 CAMBIO FISCAL NO PERMITIDO\n\n'
                    'Documento con NCF %s.\n\n'
                    'No se puede modificar el tipo fiscal de un comprobante ya emitido.'
                ) % move.l10n_do_ncf_number)

            # Marcar como nota de débito una factura ya confirmada la
            # convertía en "ND" sin aviso: la nota es un documento nuevo.
            if (
                'l10n_do_is_debit_note' in vals
                and bool(vals['l10n_do_is_debit_note']) != move.l10n_do_is_debit_note
                and (move.state == 'posted' or move.l10n_do_ncf_number)
            ):
                raise UserError(_(
                    'La factura %s ya está confirmada: no se puede convertir en nota de '
                    'débito.\n\nPara cobrarle un cargo adicional al cliente, use el botón '
                    '"Nota de débito" de la factura: crea una nota nueva enlazada a ella.',
                    move.name))

        res = super().write(vals)
        if 'l10n_do_debit_origin_move_id' in vals or 'l10n_do_is_debit_note' in vals:
            self._l10n_do_fill_debit_ncf_origin()
        if 'l10n_do_fiscal_type' in vals and not self.env.context.get('l10n_do_skip_kind_manual'):
            self._l10n_do_mark_kind_manual()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._l10n_do_debit_vals_from_std(vals)
        moves = super().create(vals_list)
        moves._l10n_do_fill_debit_ncf_origin()
        explicit = self.browse([move.id for move, vals in zip(moves, vals_list)
                                if 'l10n_do_fiscal_type' in vals or 'l10n_do_purchase_kind' in vals])
        explicit._l10n_do_mark_kind_manual()
        return moves

    def _l10n_do_fill_debit_ncf_origin(self):
        """NCF afectado de la nota de débito, tomado de su factura origen.

        En el formulario es de solo lectura, así que lo que pone el onchange
        no siempre llega a guardarse.
        """
        for move in self:
            origin = move.l10n_do_debit_origin_move_id
            if move.l10n_do_is_debit_note and origin and not move.l10n_do_debit_ncf_origin:
                number = origin._l10n_do_note_origin_number()
                if number:
                    move.l10n_do_debit_ncf_origin = number

    @api.model
    def _l10n_do_debit_vals_from_std(self, vals):
        """Nota creada con el botón "Nota de débito" de Odoo (account_debit_note).

        Ese asistente copia la factura y le pone debit_origin_id: sin esto la
        nota salía como una factura más (B01/E31). Aquí se completa como nota
        de débito dominicana (B03/E33) enlazada a su origen.
        """
        origin_id = vals.get('debit_origin_id')
        if not origin_id:
            return
        origin = self.browse(origin_id)
        if origin.company_id.country_id.code != 'DO':
            return
        if origin.move_type == 'out_invoice' and vals.get('move_type', 'out_invoice') == 'out_invoice':
            vals.setdefault('l10n_do_is_debit_note', True)
            vals.setdefault('l10n_do_debit_origin_move_id', origin.id)
            vals.setdefault('l10n_do_debit_ncf_origin', origin._l10n_do_note_origin_number() or False)
        elif origin.move_type == 'in_invoice' and vals.get('move_type', 'in_invoice') == 'in_invoice':
            # La nota de débito de un proveedor trae el comprobante de él.
            vals.setdefault('l10n_do_is_vendor_debit_note', True)
            vals.setdefault('l10n_do_vendor_debit_ncf_origin',
                            origin.l10n_do_vendor_ncf or origin.l10n_do_ncf_number or False)
            vals.setdefault('l10n_do_fiscal_type', 'fiscal')

    def _l10n_do_note_origin_number(self):
        """El comprobante (NCF o e-NCF) que una nota de este documento modifica.

        Punto de extensión: con e-CF el número puede estar asignado antes de
        que la DGII responda (un conector lo sobrescribe).
        """
        self.ensure_one()
        return self.l10n_do_ncf_number

    # =========================================
    # NOTA DE DÉBITO DESDE LA FACTURA
    # =========================================
    def _l10n_do_debit_note_vals(self):
        """Valores de una nota de débito en borrador para esta factura."""
        self.ensure_one()
        vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'journal_id': self.journal_id.id,
            'currency_id': self.currency_id.id,
            'fiscal_position_id': self.fiscal_position_id.id,
            'invoice_payment_term_id': self.invoice_payment_term_id.id,
            'invoice_user_id': self.invoice_user_id.id,
            'ref': self.name,
            'l10n_do_is_debit_note': True,
            'l10n_do_debit_origin_move_id': self.id,
            'l10n_do_debit_ncf_origin': self._l10n_do_note_origin_number(),
        }
        if 'debit_origin_id' in self._fields:
            # Con account_debit_note, su botón inteligente la cuenta también.
            vals['debit_origin_id'] = self.id
        return vals

    def action_l10n_do_debit_note(self):
        """Botón "Nota de débito": abre una nota nueva ya enlazada a la factura.

        Lleva el cliente, la factura origen y su comprobante; el motivo y los
        cargos los completa el usuario.
        """
        self.ensure_one()
        if not self.l10n_do_can_debit_note:
            raise UserError(_('Solo se le hace nota de débito a una factura de cliente confirmada.'))
        if not self._l10n_do_note_origin_number():
            raise UserError(_(
                'La factura %s todavía no tiene comprobante fiscal (NCF o e-NCF). '
                'Espere a que tenga su número para hacerle una nota de débito.', self.name))
        debit_note = self.create(self._l10n_do_debit_note_vals())
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nota de débito'),
            'res_model': 'account.move',
            'res_id': debit_note.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'context': {'default_move_type': 'out_invoice'},
        }

    def action_l10n_do_view_debit_notes(self):
        self.ensure_one()
        notes = self.l10n_do_debit_note_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Notas de débito'),
            'res_model': 'account.move',
            'context': {'default_move_type': 'out_invoice', 'create': False},
        }
        if len(notes) == 1:
            action.update({'view_mode': 'form', 'views': [(False, 'form')], 'res_id': notes.id})
        else:
            action.update({'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')],
                           'domain': [('id', 'in', notes.ids)]})
        return action

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
            # _origin.id es el id real en base de datos (0/False en un registro
            # nuevo todavía sin guardar). Buscar con el move.id "NewId" de un
            # borrador provocaba un warning y nunca encontraba nada.
            origin_id = move._origin.id
            if move.move_type == 'out_invoice' and origin_id:
                credit_notes = self.search([
                    ('l10n_do_origin_move_id', '=', origin_id),
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
            for line in move.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                # Sin producto no se sabe si es bien o servicio: no se cuenta y
                # el 606 lo marca como pendiente (se puede escribir a mano).
                if not line.product_id:
                    continue
                if line.product_id.type == 'service':
                    servicios += line.price_subtotal
                else:
                    bienes += line.price_subtotal
            move.l10n_do_606_monto_bienes = bienes
            move.l10n_do_606_monto_servicios = servicios

    @api.depends('l10n_do_fiscal_type', 'line_ids.tax_line_id', 'line_ids.amount_currency')
    def _compute_606_itbis_costo(self):
        for move in self:
            move.l10n_do_itbis_costo = (
                move._l10n_do_itbis_amount() if move.l10n_do_fiscal_type == 'minor_expense' else 0)

    def _l10n_do_itbis_amount(self):
        """ITBIS del asiento (sin ISC, propina, otros impuestos ni
        retenciones), en la moneda de la factura: las líneas de impuesto de
        clase ITBIS, o sin clase al 18 o 16 %."""
        self.ensure_one()
        total = 0.0
        for line in self.line_ids.filtered(lambda l: l.tax_line_id and l.tax_line_id.amount > 0):
            tax = line.tax_line_id
            if tax.dgii_tax_kind == 'itbis' or (
                    not tax.dgii_tax_kind and tax.amount_type == 'percent'
                    and tax.amount in (18.0, 16.0)):
                total += abs(line.amount_currency)
        return total

    @api.depends('line_ids.tax_line_id', 'line_ids.amount_currency', 'l10n_do_itbis_costo',
                 'l10n_do_fiscal_type')
    def _compute_606_itbis(self):
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund'):
                move.l10n_do_itbis_facturado = move.l10n_do_itbis_adelantar = 0
                continue
            move.l10n_do_itbis_facturado = move._l10n_do_itbis_amount()
            # ITBIS por adelantar = facturado - llevado al costo (Norma General
            # 07-2018, Anexo A, casilla 15; instructivo 606, julio 2025).
            move.l10n_do_itbis_adelantar = max(
                move.l10n_do_itbis_facturado - move.l10n_do_itbis_costo, 0)

    @api.depends('l10n_do_retention_ids.retention_amount', 'l10n_do_retention_ids.dgii_606_bucket',
                 'l10n_do_retention_legacy', 'line_ids.tax_line_id', 'line_ids.amount_currency')
    def _compute_606_buckets(self):
        for move in self:
            buckets = {'itbis_retenido': 0, 'itbis_percibido': 0, 'isr_retenido': 0, 'isr_percibido': 0}
            if move.l10n_do_retention_legacy:
                # Confirmada antes de 19.0.4: lo que se reportó desde la pestaña.
                for ret in move.l10n_do_retention_ids:
                    if ret.dgii_606_bucket in buckets:
                        buckets[ret.dgii_606_bucket] += ret.retention_amount or 0
            else:
                for bucket, amount in move._l10n_do_tax_retention_amounts().items():
                    if bucket in buckets:
                        buckets[bucket] += amount
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

    @api.depends('line_ids.tax_line_id', 'line_ids.balance', 'amount_total', 'l10n_do_retention_ids.retention_amount',
                 'l10n_do_retention_ids.retention_type_id', 'l10n_do_retention_legacy')
    def _compute_retention_totals(self):
        """Calcular totales de retenciones desde l10n_do_retention_ids

        Fuentes de datos (en orden de prioridad):
        1. l10n_do_retention_ids - retenciones manuales/calculadas del módulo NCF
        2. line_ids con dgii_retention_type - impuestos de Odoo marcados como retención

        Nota: En Odoo, amount_total YA incluye las retenciones (impuestos negativos).
        """
        for move in self:
            isr = itbis = 0
            if not move.l10n_do_retention_legacy:
                # Desde 19.0.4: solo los impuestos de retención de las líneas.
                amounts = move._l10n_do_tax_retention_amounts()
                isr = amounts.get('isr_retenido', 0.0)
                itbis = amounts.get('itbis_retenido', 0.0)
                move.l10n_do_total_isr_retention = isr
                move.l10n_do_total_itbis_retention = itbis
                move.l10n_do_amount_to_pay = move.amount_total
                move.l10n_do_gross_total = move.amount_total + isr + itbis
                continue

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
                 'l10n_do_payment_other', 'payment_state', 'amount_residual')
    def _compute_forma_pago(self):
        for move in self:
            move.l10n_do_forma_pago = move._l10n_do_payment_form_code()

    # Formas de pago del 606/607 (instructivo 606, julio 2025, casilla 23):
    # 01 Efectivo, 02 Cheques/Transferencias/Depósito, 03 Tarjeta crédito/débito,
    # 04 Compra a crédito, 05 Permuta, 06 Notas de crédito, 07 Mixto.
    def _l10n_do_payment_amounts(self):
        """(importe por forma de pago, importe sin forma conocida), en DOP.

        Sale de los pagos reales conciliados con la factura: el diario de cada
        pago dice su forma (campo "Forma de pago DGII" del diario; un diario de
        tipo Efectivo es 01). Una nota de crédito aplicada es 06 y lo que queda
        por pagar es 04 (a crédito). Un pago cuyo diario no tiene forma va como
        "sin forma conocida": no se adivina.
        """
        self.ensure_one()
        amounts, unknown = {}, 0.0
        terms = self.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable'))
        for line in terms:
            for partial in line.matched_debit_ids | line.matched_credit_ids:
                counterpart = (partial.debit_move_id if partial.credit_move_id == line
                               else partial.credit_move_id)
                origin = counterpart.move_id
                if origin.move_type in ('out_refund', 'in_refund'):
                    code = '06'
                else:
                    journal = counterpart.journal_id
                    code = journal.l10n_do_payment_form or ('01' if journal.type == 'cash' else False)
                if code:
                    amounts[code] = amounts.get(code, 0.0) + partial.amount
                else:
                    unknown += partial.amount
        residual = abs(self.amount_residual_signed or 0.0)
        if residual:
            amounts['04'] = amounts.get('04', 0.0) + residual
        return amounts, unknown

    def _l10n_do_payment_form_code(self):
        """Forma de pago del 606 (un código), o False si no se puede saber.

        Primero lo que el usuario haya indicado en los importes por forma de
        pago de la factura; si no hay, los pagos reales. Varias formas son 07
        (Mixto). "Otras formas" no tiene código en la tabla: queda sin forma.
        """
        self.ensure_one()
        manual = {
            '01': self.l10n_do_payment_cash, '02': self.l10n_do_payment_bank,
            '03': self.l10n_do_payment_card, '04': self.l10n_do_payment_credit,
            '05': self.l10n_do_payment_swap,
        }
        active = [code for code, amount in manual.items() if amount and amount > 0]
        if self.l10n_do_payment_other and self.l10n_do_payment_other > 0:
            return '07' if active else False
        if active:
            return active[0] if len(active) == 1 else '07'
        if self.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund') \
                or self.state != 'posted':
            return False
        amounts, unknown = self._l10n_do_payment_amounts()
        if unknown or not amounts:
            return False
        return next(iter(amounts)) if len(amounts) == 1 else '07'

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

    @api.depends('move_type', 'partner_id.vat', 'partner_id.country_id', 'partner_id.l10n_do_dgii_tax_payer_type', 'l10n_do_fiscal_type', 'l10n_do_is_debit_note')
    def _compute_l10n_do_ncf_type_id(self):
        """Asignar tipo de NCF segun tipo fiscal del cliente/proveedor

        DOCUMENTOS CON NCF: si el documento ya tiene numero y tipo, el tipo
        se conserva. Editar despues el cliente (tipo de contribuyente, RNC,
        pais) o el tipo fiscal de una compra no puede cambiar el tipo de un
        comprobante ya emitido.

        VENTAS (out_invoice) - Orden de evaluacion:
        1. Nota de Debito -> B03 (sea cual sea el tipo de cliente)
        2. Exportacion (cliente extranjero) -> B16
        3. Gubernamental -> B15
        4. Regimen Especial -> B14
        5. Contribuyente (tipo 'taxpayer') -> B01
        6. Todos los demas (consumidor final) -> B02

        CRITERIO B01 vs B02 (normativa DGII):
        Lo que determina el tipo NO es que el cliente tenga documento, sino
        si SOLICITA credito fiscal. En ventas al detalle se emite B02 por
        defecto; el B01 solo cuando el cliente pide factura con credito
        fiscal y esta registrado como contribuyente.

        Por eso NO se usa la sola presencia de vat: una cedula de 11 digitos
        identifica a una persona, pero no implica que este registrada como
        Persona Fisica con Actividad Empresarial. El campo que manda es
        partner.l10n_do_dgii_tax_payer_type: si es 'taxpayer' -> B01,
        cualquier otro valor -> B02.

        NC VENTAS (out_refund): siempre B04
        COMPRAS (in_invoice): segun l10n_do_fiscal_type del movimiento
        """
        NcfType = self.env['l10n_do_ncf.type']
        all_types = NcfType.search([])
        type_cache = {t.code: t for t in all_types}

        for move in self:
            if move.l10n_do_ncf_number and move.l10n_do_ncf_type_id:
                # Comprobante ya emitido: el tipo no se recalcula
                move.l10n_do_ncf_type_id = move.l10n_do_ncf_type_id
                continue

            code = move._l10n_do_get_ncf_type_code()
            move.l10n_do_ncf_type_id = type_cache.get(code).id if code and code in type_cache else False

    def _l10n_do_get_ncf_type_code(self):
        """Código del tipo de comprobante que corresponde al documento
        ('01', '02', '04'...), o False si no lleva NCF propio.

        Punto de extensión: un conector de e-CF lo sobrescribe para
        convertir el código de papel en su equivalente electrónico
        (01 -> 31, 02 -> 32...). Las reglas están documentadas en
        _compute_l10n_do_ncf_type_id.
        """
        self.ensure_one()

        if self.move_type == 'out_invoice':
            partner = self.partner_id
            partner_country = partner.country_id.code if partner.country_id else 'DO'
            client_type = partner.l10n_do_dgii_tax_payer_type or 'final_consumer'

            # 1. Nota de Debito: siempre B03
            if self.l10n_do_is_debit_note:
                return '03'  # B03 - Nota de Debito
            # 2. Regimen Especial marcado a mano, aunque el cliente sea
            #    extranjero: un diplomatico recibe B14/E44 con su
            #    identificacion extranjera (Formato e-CF v1.0, pag. 12, nota 5).
            if client_type == 'special_regime':
                return '14'  # B14 - Regimen Especial
            # 3. Exportacion: cliente extranjero (pais != DO)
            if partner_country and partner_country != 'DO':
                return '16'  # B16 - Exportacion
            # 4. Gubernamental
            if client_type == 'governmental':
                return '15'  # B15 - Gubernamental
            # 5. Contribuyente registrado que solicita credito fiscal
            if client_type == 'taxpayer':
                return '01'  # B01 - Credito Fiscal
            # 6. Consumidor Final (default)
            return '02'  # B02 - Consumidor Final

        if self.move_type == 'out_refund':
            return '04'  # B04 - Nota de Credito

        if self.move_type in ('in_invoice', 'in_refund'):
            # Mapeo tipo fiscal proveedor -> NCF para compras
            return {
                'informal': '11',
                'minor_expense': '13',
                'exterior': '17',
                'special': '14',
                'governmental': '15',
            }.get(self.l10n_do_fiscal_type, False)

        return False

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
        # Mismo criterio que el índice unique_vendor_ncf_per_company (hooks.py):
        # compañía + proveedor + NCF. Dos proveedores distintos pueden tener
        # el mismo número.
        for move in self:
            if not move.l10n_do_vendor_ncf or move.move_type not in ('in_invoice', 'in_refund'):
                continue
            ncf = move.l10n_do_vendor_ncf.strip().upper()
            duplicates = self.search([
                ('id', '!=', move.id),
                ('company_id', '=', move.company_id.id),
                ('commercial_partner_id', '=', move.commercial_partner_id.id),
                ('l10n_do_vendor_ncf', '=ilike', ncf),
                ('move_type', 'in', ('in_invoice', 'in_refund')),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if duplicates:
                raise ValidationError(_('NCF proveedor duplicado: %s (ya existe en %s para %s)') % (
                    ncf, duplicates.name, move.commercial_partner_id.display_name))

    def _sql_error_to_message(self, exc):
        # Los índices únicos de NCF se crean en hooks.py, así que Odoo no
        # conoce su mensaje: sin esto el usuario vería un error genérico.
        constraint = exc.diag.constraint_name
        if constraint == 'unique_vendor_ncf_per_company':
            return _('Ya existe otra factura de este proveedor con el mismo NCF.')
        if constraint == 'unique_ncf_per_company':
            return _('Ya existe otro documento con el mismo NCF en esta compañía.')
        return super()._sql_error_to_message(exc)

    @api.constrains('l10n_do_vendor_ncf')
    def _check_vendor_ncf_format(self):
        for move in self:
            if move.l10n_do_vendor_ncf and move.move_type in ('in_invoice', 'in_refund'):
                if not re.match(NCF_FULL_PATTERN, move.l10n_do_vendor_ncf.strip().upper()):
                    raise ValidationError(_('NCF proveedor inválido: %s') % move.l10n_do_vendor_ncf)

    @api.constrains('l10n_do_ncf_origin', 'move_type', 'state')
    def _check_ncf_origin(self):
        """La NC debe referenciar el comprobante que corrige.

        Solo se exige cuando ya esta POSTEADA, igual que
        _check_debit_note_origin y _check_vendor_debit_note:

        - En borrador el usuario aun esta completando el documento; el
          constrain saltaba apenas se creaba la NC y no dejaba ni abrirla.
        - Los datos demo de contabilidad de Odoo crean notas de credito sin
          contexto fiscal dominicano, y el constrain hacia fallar la carga
          entera del chart_template (_install_demo).

        El bloqueo real al postear ya lo hace action_post, que ademas exige
        el motivo de la NC.
        """
        for move in self:
            if move.company_id.country_id.code != 'DO':
                continue
            if move.state != 'posted':
                continue
            if move.move_type == 'out_refund' and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_origin and not move.l10n_do_origin_move_id:
                    raise ValidationError(_('NC requiere NCF afectado.'))

    @api.constrains('l10n_do_is_debit_note', 'l10n_do_debit_ncf_origin', 'l10n_do_debit_origin_move_id')
    def _check_debit_note_origin(self):
        for move in self:
            if move.company_id.country_id.code != 'DO':
                continue
            if move.l10n_do_debit_origin_move_id == move:
                raise ValidationError(_(
                    'Una nota de débito no puede modificarse a sí misma: elija como '
                    '"Factura Origen ND" la factura confirmada a la que se le cobra el cargo.'))
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
            # Si tiene NCF, abrir wizard de anulación
            if move.l10n_do_ncf_number:
                return {
                    'name': _('Anular Factura'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'l10n_do_ncf.invoice.annul.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'active_id': move.id,
                        'active_model': 'account.move',
                    }
                }
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
    def _l10n_do_partner_action(self, partner=None):
        """Acción que abre la ficha del proveedor (botón de los errores)."""
        partner = partner or self.partner_id.commercial_partner_id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def _l10n_do_raise_partner_fix(self, message, partner=None):
        partner = partner or self.partner_id.commercial_partner_id
        if not partner:
            raise UserError(message)
        raise RedirectWarning(message, self._l10n_do_partner_action(partner),
                              _('Abrir "%s"', partner.display_name))

    def _l10n_do_fill_informal_provider(self):
        """Nombre y cédula del proveedor informal: los de su contacto si la
        factura no trae otros (reportes 606 y e-CF E41 los leen de aquí)."""
        for move in self.filtered(lambda m: m.l10n_do_fiscal_type == 'informal'):
            partner = move.partner_id.commercial_partner_id
            digits = re.sub(r'[^0-9]', '', partner.vat or '')
            vals = {}
            if not move.l10n_do_informal_provider_name and partner.name:
                vals['l10n_do_informal_provider_name'] = partner.name
            if not move.l10n_do_informal_provider_cedula and len(digits) == 11:
                vals['l10n_do_informal_provider_cedula'] = digits
            if vals:
                move.write(vals)

    def _check_informal_provider_rnc(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'informal':
            return
        partner = self.partner_id.commercial_partner_id
        digits = re.sub(r'[^0-9]', '', partner.vat or '')
        if len(digits) == 9:
            # Un RNC es de un contribuyente: él da su propio comprobante.
            self._l10n_do_raise_partner_fix(_(
                'El proveedor %(name)s tiene RNC (%(vat)s): es un contribuyente y debe darle '
                'su propio comprobante (NCF o e-NCF).\n\nCambie "Tipo de compra" a "Con '
                'comprobante del proveedor" y escriba el NCF que le dio, o, si es una persona '
                'sin comprobante, ponga su cédula en el contacto.',
                name=partner.display_name, vat=partner.vat), partner)
        self._l10n_do_fill_informal_provider()
        if not self.l10n_do_informal_provider_name:
            raise UserError(_(
                'Falta el nombre del proveedor informal: elija el proveedor en la factura.'))
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
                    raise UserError(_(
                        'Gastos menores: la línea "%s" tiene ITBIS.\n\nLos gastos menores van '
                        'exentos: quite el impuesto de la línea o cámbielo por "ITBIS Exento".',
                        line.name))
        if self._l10n_do_retention_tax_lines() or self.l10n_do_retention_ids.filtered('retention_amount'):
            raise UserError(_(
                'Gastos menores: la factura tiene retenciones.\n\nUn gasto menor no lleva '
                'retenciones: quite los impuestos de retención de las líneas.'))
        limit = self._get_b13_transaction_limit()
        if self.amount_total > limit:
            raise UserError(_(
                'Gastos menores: el total (RD$ %(total)s) pasa del límite de RD$ %(limit)s por '
                'gasto.\n\nSi el proveedor le dio comprobante, cambie "Tipo de compra" a "Con '
                'comprobante del proveedor".',
                total='{:,.2f}'.format(self.amount_total), limit='{:,.2f}'.format(limit)))

    def _check_b17_no_itbis(self):
        self.ensure_one()
        if self.l10n_do_fiscal_type != 'exterior':
            return
        if self.amount_tax > 0:
            raise UserError(_(
                'Pago al exterior: la factura tiene ITBIS.\n\nUn pago al exterior no lleva '
                'ITBIS: quite el impuesto de las líneas.'))
        if self.l10n_do_retention_legacy:
            has_isr = any(ret.retention_type_id.code == 'ISR_EXT' for ret in self.l10n_do_retention_ids)
        else:
            has_isr = bool(self._l10n_do_isr_retention_lines())
        if not has_isr:
            raise UserError(_(
                'Pago al exterior: falta la retención de ISR.\n\nAgregue en las líneas el '
                'impuesto de retención del pago al exterior (en el plan l10n_do, "-27% ISR '
                '(L253-12)"). Para que se agregue solo, indíquelo en la compañía, "Retenciones '
                'del pago al exterior".'))

    # =========================================
    # GENERADOR NCF (CON PROTECCIÓN RACE CONDITION)
    # =========================================
    def _l10n_do_uses_external_numbering(self):
        """True si el número de este documento lo asigna un sistema externo.

        Punto de extensión para un conector de e-CF. Aquí siempre es False:
        el NCF sale de las secuencias locales.
        """
        self.ensure_one()
        return False

    # =========================================
    # ESTADO FISCAL DEL ORIGEN SEGÚN SUS NOTAS
    # =========================================
    def _l10n_do_note_is_issued(self):
        """True si esta nota ya modifica fiscalmente su comprobante de origen.

        Con NCF de papel, la nota queda emitida al confirmarse. Con numeración
        externa (e-CF), solo cuando la DGII la acepta, que es cuando recibe su
        número: si se rechaza, no llega a enviarse o no hay secuencia, el
        origen queda como estaba.
        """
        self.ensure_one()
        if self.state != 'posted':
            return False
        if self._l10n_do_uses_external_numbering():
            return bool(self.l10n_do_ncf_number)
        return True

    def _l10n_do_update_origin_fiscal_status(self):
        """Marca el origen de cada nota emitida: Anulado o Parcialmente
        Acreditado (nota de crédito) y Con ND (nota de débito)."""
        for move in self:
            if move.company_id.country_id.code != 'DO' or not move._l10n_do_note_is_issued():
                continue
            if move.move_type == 'out_refund' and move.l10n_do_origin_move_id:
                origin = move.l10n_do_origin_move_id
                notes = self.search([
                    ('l10n_do_origin_move_id', '=', origin.id),
                    ('state', '=', 'posted'),
                    ('move_type', '=', 'out_refund'),
                ]).filtered(lambda note: note._l10n_do_note_is_issued())
                total_nc = sum(notes.mapped('amount_total'))
                if abs(total_nc - origin.amount_total) < 0.01:
                    origin.l10n_do_fiscal_status = 'annulled'
                else:
                    origin.l10n_do_fiscal_status = 'partial_credit'
            if move.l10n_do_is_debit_note and move.l10n_do_debit_origin_move_id:
                move.l10n_do_debit_origin_move_id.l10n_do_fiscal_status = 'debited'

    def _generate_ncf(self):
        """Generar NCF con protección de concurrencia usando FOR UPDATE.

        Evita que dos usuarios obtengan el mismo NCF al confirmar
        facturas simultáneamente.
        """
        self.ensure_one()
        if self.l10n_do_ncf_number:
            return

        if self._l10n_do_uses_external_numbering():
            # El número lo asigna un sistema externo (e-CF): no se consume
            # ninguna secuencia local.
            return

        if not self.l10n_do_ncf_type_id:
            raise UserError(_('Seleccione tipo de comprobante.'))

        ncf_type = self.l10n_do_ncf_type_id

        # Buscar secuencias candidatas
        sequences = self.env['l10n_do_ncf.sequence'].sudo().search([
            ('ncf_type_id', '=', ncf_type.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'active'),
        ], order='id desc')

        if not sequences:
            action = self.env['ir.actions.act_window']._for_xml_id('l10n_do_ncf.action_ncf_sequence')
            action.update({
                'views': [[False, 'form']],
                'view_mode': 'form',
                'target': 'current',
                'context': {'default_ncf_type_id': ncf_type.id,
                            'default_company_id': self.company_id.id},
            })
            raise RedirectWarning(_(
                'No hay una secuencia activa de "%(type)s" (%(prefix)s) en %(company)s.\n\n'
                'Registre el rango que le autorizó la DGII para este tipo de comprobante y '
                'actívelo; luego confirme de nuevo.',
                type=ncf_type.name, prefix=ncf_type.prefix, company=self.company_id.name,
            ), action, _('Registrar secuencia %s', ncf_type.prefix))

        # FOR UPDATE NOWAIT: bloquea la fila para evitar duplicados
        # Si otra transacción tiene el lock, falla inmediatamente
        try:
            self.env.cr.execute("""
                SELECT id, current_number, range_from, range_to, expiration_date
                FROM l10n_do_ncf_sequence
                WHERE id IN %s
                  AND state = 'active'
                  AND current_number < range_to
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE NOWAIT
            """, (tuple(sequences.ids),))

            row = self.env.cr.fetchone()

        except Exception as e:
            if 'could not obtain lock' in str(e) or 'NOWAIT' in str(e):
                raise UserError(_(
                    'Otro usuario está generando un NCF en este momento.\n'
                    'Por favor, intente nuevamente en unos segundos.'
                ))
            raise

        if not row:
            raise UserError(_(
                'No hay secuencias disponibles para %s.\n'
                'Todas las secuencias están agotadas o vencidas.'
            ) % ncf_type.name)

        seq_id, current_number, range_from, range_to, expiration_date = row

        # Validar vencimiento
        if expiration_date:
            if self.invoice_date and self.invoice_date > expiration_date:
                raise UserError(_('La fecha de factura es posterior al vencimiento de la secuencia.'))
            if expiration_date < date.today():
                raise UserError(_('La secuencia está vencida desde %s.') % expiration_date)

        # Calcular siguiente número
        next_num = max(range_from or 1, current_number + 1)

        if next_num > range_to:
            raise UserError(_(
                'Secuencia agotada para %s.\n'
                'Rango: %s - %s\n'
                'Solicite nuevos NCF a DGII.'
            ) % (ncf_type.name, range_from, range_to))

        # Generar NCF
        prefix = ncf_type.prefix
        ncf = f'{prefix}{next_num:0{10 if ncf_type.is_electronic else 8}d}'

        # Actualizar secuencia (atómico dentro del lock)
        self.env.cr.execute("""
            UPDATE l10n_do_ncf_sequence
            SET current_number = %s, write_date = NOW()
            WHERE id = %s
        """, (next_num, seq_id))

        # Asignar NCF a la factura
        self.write({
            'l10n_do_ncf_number': ncf,
            'l10n_do_ncf_seq_id': seq_id,
            'l10n_do_fiscal_status': 'valid',
        })

        _logger.info('NCF generado: %s | Documento: %s | Secuencia: %s', ncf, self.name, seq_id)

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

    @api.onchange('l10n_do_fiscal_type')
    def _onchange_fiscal_type(self):
        if self.move_type not in ('in_invoice', 'in_refund'):
            return
        if self.l10n_do_fiscal_type in ('informal', 'minor_expense'):
            self.l10n_do_vendor_ncf = False
        self._l10n_do_apply_retention_taxes()

    def _l10n_do_suggested_retention_taxes(self, line=None, line_taxes=None):
        """Impuestos de retención que se agregan solos a una línea, según el tipo
        de compra y lo que indicó la compañía. Ninguno en gastos menores ni en
        una compra con comprobante del proveedor."""
        self.ensure_one()
        Tax = self.env['account.tax']
        company = self.company_id
        if self.move_type not in ('in_invoice', 'in_refund') or company.country_id.code != 'DO':
            return Tax
        if self.l10n_do_fiscal_type == 'exterior':
            return company.l10n_do_exterior_retention_tax_ids
        if self.l10n_do_fiscal_type != 'informal':
            return Tax
        taxes = company.l10n_do_informal_retention_tax_ids
        if line is None:
            return taxes
        line_taxes = line.tax_ids if line_taxes is None else line_taxes
        has_itbis = any(t.amount > 0 for t in line_taxes)
        is_service = not line.product_id or line.product_id.type == 'service'
        return taxes.filtered(lambda t: (
            (t._l10n_do_retention_kind() == 'itbis' and has_itbis)
            or (t._l10n_do_retention_kind() == 'isr' and is_service)))

    def _l10n_do_apply_retention_taxes(self):
        """Al cambiar el tipo de compra: quita de las líneas las retenciones
        sugeridas de los otros tipos (y todas en un gasto menor) y agrega las
        del tipo actual. Se escribe con comandos sobre invoice_line_ids para
        que el formulario lo guarde también en una factura ya creada."""
        self.ensure_one()
        company = self.company_id
        known = company.l10n_do_informal_retention_tax_ids | company.l10n_do_exterior_retention_tax_ids
        commands = []
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            taxes = line.tax_ids - known
            if self.l10n_do_fiscal_type == 'minor_expense':
                taxes = taxes.filtered(lambda t: t.amount >= 0)
            new = taxes | self._l10n_do_suggested_retention_taxes(line, taxes)
            if new != line.tax_ids:
                commands.append(Command.update(line.id, {'tax_ids': [Command.set(new.ids)]}))
        if commands:
            self.invoice_line_ids = commands

    # Compatibilidad: los usaban el onchange y los tests anteriores.
    def _apply_b11_retentions(self):
        self._l10n_do_apply_retention_taxes()

    def _apply_b17_retentions(self):
        self._l10n_do_apply_retention_taxes()

    def _l10n_do_suggest_retentions(self):
        self._l10n_do_apply_retention_taxes()

    # =========================================
    # BORRADORES CON RETENCIONES EN LA PESTAÑA
    # =========================================
    @api.model
    def _l10n_do_convert_tab_retentions(self, retention_types=None):
        """Pasa a impuesto de línea las retenciones escritas en la pestaña de
        las facturas de proveedor en borrador.

        Solo cuando el tipo de retención tiene indicado su impuesto equivalente
        en la compañía y el resultado da el mismo monto; si no, la fila se queda
        y la factura sigue avisando (no se confirma hasta que se corrija).
        Devuelve las facturas convertidas.
        """
        domain = [('move_id.state', '=', 'draft'), ('tax_id', '=', False),
                  ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
                  ('move_id.l10n_do_retention_legacy', '=', False)]
        if retention_types is not None:
            domain.append(('retention_type_id', 'in', retention_types.ids))
        rows = self.env['l10n_do_ncf.move.retention'].sudo().search(domain)
        converted = self.browse()
        for move in rows.move_id:
            if move._l10n_do_convert_move_tab_retentions():
                converted |= move
        return converted

    def _l10n_do_convert_move_tab_retentions(self):
        self.ensure_one()
        done = False
        for row in self.l10n_do_retention_ids.filtered(lambda r: not r.tax_id and r.retention_type_id):
            tax = row.retention_type_id.tax_ids.filtered(lambda t: t.company_id == self.company_id)[:1]
            if not tax:
                continue
            kind = row.retention_type_id.retention_type
            lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
            if kind == 'itbis':
                lines = lines.filtered(lambda l: any(t.amount > 0 for t in l.tax_ids))
            elif self.l10n_do_fiscal_type == 'informal':
                lines = lines.filtered(lambda l: not l.product_id or l.product_id.type == 'service')
            before = {line: line.tax_ids for line in lines}
            for line in lines:
                line.tax_ids |= tax
            amount = sum(abs(l.amount_currency) for l in self.line_ids if l.tax_line_id == tax)
            if lines and self.currency_id.compare_amounts(amount, row.retention_amount) == 0:
                row.unlink()
                done = True
            else:
                for line, taxes in before.items():
                    line.tax_ids = taxes
        return done

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
        ncf_code = COHERENCE_PAPER_CODE.get(ncf_code, ncf_code)
        partner_vat = (self.partner_id.vat or '').strip()

        # Validación B15 (Gubernamental) con RNC no gubernamental
        if ncf_code == '15' and partner_vat:
            is_gov_pattern = partner_vat.startswith(GOV_RNC_PREFIXES)
            if not is_gov_pattern:
                return {'warning': {
                    'title': _('⚠️ Inconsistencia Fiscal Detectada'),
                    'message': _(
                        'El cliente "%s" está marcado como Gubernamental (B15), '
                        'pero su RNC %s no corresponde a un patrón típico de entidad estatal.\n\n'
                        'Patrones gubernamentales típicos:\n'
                        '• 401XXXXXX - Ministerios/Direcciones\n'
                        '• 402XXXXXX - Instituciones Descentralizadas\n'
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
            is_gov_pattern = partner_vat.startswith(GOV_RNC_PREFIXES)
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
        """Al confirmar, la pestaña "Retenciones" copia los impuestos de
        retención del asiento: una fila por impuesto, con su base y su monto.
        Es solo una copia (la fuente son los impuestos); la de una factura
        anterior a 19.0.4 no se toca."""
        self.ensure_one()
        if self.move_type not in ('in_invoice', 'in_refund') or self.l10n_do_retention_legacy:
            return
        rows = []
        for tax in self._l10n_do_retention_tax_lines().tax_line_id:
            lines = self.line_ids.filtered(lambda l: l.tax_line_id == tax)
            rows.append(Command.create({
                'tax_id': tax.id,
                'base_amount': self._l10n_do_tax_base_in_currency(lines),
                'tax_amount': abs(sum(lines.mapped('amount_currency'))),
            }))
        self.l10n_do_retention_ids = [Command.clear()] + rows

    # =========================================
    # VALIDACIÓN FISCAL INTELIGENTE
    # =========================================
    def _validate_fiscal_coherence(self):
        """Validación fiscal según algoritmo unificado.

        Reglas:
        - País != RD → la factura debe ser B16 (Exportación), o B14 si el
          cliente está marcado como Régimen Especial (diplomático). No aplica
          a notas de crédito (B04) ni de débito (B03), que llevan su propio tipo
        - B01 (Fiscal) → RNC obligatorio, país RD
        - B02 (Consumidor) → admite cédula; warning si es RNC de empresa
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
        # E44/E45/E46 se validan como B14/B15/B16.
        ncf_code = COHERENCE_PAPER_CODE.get(ncf_code, ncf_code)
        partner_country = partner.country_id.code if partner.country_id else 'DO'
        partner_vat = (partner.vat or '').strip()
        client_type = partner.l10n_do_dgii_tax_payer_type or 'final_consumer'

        # =====================
        # REGLA 1: Exportación (B16)
        # =====================
        if partner_country != 'DO':
            # Cliente extranjero DEBE usar B16 en la factura. Las notas de
            # crédito (B04) y de débito (B03) que la corrigen no son B16.
            is_plain_invoice = self.move_type == 'out_invoice' and not self.l10n_do_is_debit_note
            # Un extranjero marcado como Régimen Especial (diplomático) lleva
            # B14/E44 con su identificación extranjera.
            allowed = ('16', '14') if client_type == 'special_regime' else ('16',)
            if is_plain_invoice and ncf_code not in allowed:
                raise UserError(_(
                    "❌ ERROR FISCAL: Cliente Extranjero\n\n"
                    "El cliente '%s' es de %s (no RD).\n"
                    "Para clientes extranjeros DEBE usar B16 (Exportación), o B14 si el\n"
                    "cliente está marcado como Régimen Especial (diplomático).\n\n"
                    "Tipo actual: %s\n\n"
                    "Corrija el tipo de comprobante o el país del cliente."
                ) % (partner.name, partner_country, ncf_type.name))
            return {}  # B16, o NC/ND, con extranjero = OK

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
        # REGLA 3: B02 (Consumidor Final)
        # =====================
        # NOTA (normativa DGII): el B02 SI admite documento del comprador.
        # De hecho, los B02 que superan RD$250,000 DEBEN incluir nombre y
        # cedula del comprador. Por eso aqui NO se bloquea la presencia de
        # documento: solo se advierte cuando parece un RNC de empresa
        # (9 digitos), porque una empresa que compra para su operacion
        # normalmente necesita B01 para acreditar el ITBIS.
        if ncf_code == '02':
            if partner_vat and len(partner_vat) == 9:
                warnings.append(_(
                    "⚠️ ADVERTENCIA: B02 a cliente con RNC de empresa\n\n"
                    "Cliente: %s\n"
                    "RNC: %s\n"
                    "Tipo: Consumidor Final (B02)\n\n"
                    "El documento parece un RNC de empresa. Un B02 no permite "
                    "al comprador acreditar el ITBIS.\n\n"
                    "Si el cliente necesita credito fiscal, cambie su tipo de "
                    "contribuyente a 'Contribuyente' para que se emita B01."
                ) % (partner.name, partner_vat))
            return {'warnings': warnings}

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
            is_gov_pattern = partner_vat.startswith(GOV_RNC_PREFIXES)

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
            is_gov_pattern = partner_vat.startswith(GOV_RNC_PREFIXES)
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

    # =========================================
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
                    origin = move.l10n_do_debit_origin_move_id
                    if not move.l10n_do_debit_ncf_origin and origin:
                        # El campo es de solo lectura en el formulario: el
                        # número se toma de la factura origen.
                        move.l10n_do_debit_ncf_origin = origin._l10n_do_note_origin_number()
                    if not move.l10n_do_debit_ncf_origin and not origin:
                        raise UserError(_(
                            'Falta la factura que modifica esta nota de débito: elíjala en '
                            '"Factura Origen ND" (pestaña "Datos Fiscales").'))
                    if not move.l10n_do_debit_note_reason:
                        raise UserError(_(
                            'Falta el motivo de la nota de débito: elíjalo en "Motivo ND" '
                            '(pestaña "Datos Fiscales").'))

            if (is_do and move.move_type in ('in_invoice', 'in_refund')
                    and not move.l10n_do_retention_legacy
                    and move.l10n_do_retention_ids.filtered(lambda r: not r.tax_id)):
                raise UserError(_(
                    'La factura tiene retenciones escritas en la pestaña "Retenciones", que no '
                    'generan asiento: no reducen lo que se le debe al proveedor ni crean la deuda '
                    'con la DGII.\n\nPóngalas como impuesto de retención en las líneas (por '
                    'ejemplo "-100%% ITBIS" o la de ISR) y borre las filas de la pestaña.'
                ).replace('%%', '%'))

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

            if is_do:
                move._l10n_do_update_origin_fiscal_status()

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


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _get_computed_taxes(self):
        # Gastos menores: van exentos de ITBIS. Las líneas nuevas toman el
        # "ITBIS Exento" de compras (o ninguno) en vez del ITBIS del producto.
        move = self.move_id
        if (move.move_type in ('in_invoice', 'in_refund')
                and move.l10n_do_fiscal_type == 'minor_expense'
                and move.company_id.country_id.code == 'DO'):
            exempt = move.company_id._l10n_do_purchase_exempt_tax()
            return exempt.with_env(self.env) if exempt else self.env['account.tax']
        taxes = super()._get_computed_taxes()
        if (move.move_type in ('in_invoice', 'in_refund')
                and move.l10n_do_fiscal_type in ('informal', 'exterior')):
            # Las retenciones que indicó la compañía para este tipo de compra.
            suggested = move._l10n_do_suggested_retention_taxes(
                self, taxes or self.env['account.tax'])
            if suggested:
                taxes = (taxes or self.env['account.tax']) | suggested.with_env(self.env)
        return taxes
