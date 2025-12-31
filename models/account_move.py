# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/account_move.py
# Descripción: Extensión de facturas con NCF - Enterprise DGII-Grade
# Compatibilidad: Odoo 19
# Versión: 19.0.1.7.0

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import re
import logging

_logger = logging.getLogger(__name__)

# =========================================
# PATRONES DE VALIDACIÓN NCF (DGII OFICIAL)
# =========================================
# NCF tradicional: B + 2 dígitos tipo + 8 dígitos secuencia = 11 caracteres
NCF_PATTERN = r'^B(01|02|03|04|11|12|13|14|15|16|17)\d{8}$'

# e-CF: E + 2 dígitos tipo + 10 dígitos secuencia = 13 caracteres (DGII 2025+)
ECF_PATTERN = r'^E(31|32|33|34|41|43|44|45|46|47)\d{10}$'

# Patrón combinado NCF + e-CF
NCF_FULL_PATTERN = r'^(B(01|02|03|04|11|12|13|14|15|16|17)\d{8}|E(31|32|33|34|41|43|44|45|46|47)\d{10})$'


class AccountMove(models.Model):
    _inherit = 'account.move'

    # =========================================
    # CAMPOS NCF PRINCIPALES
    # =========================================

    l10n_do_ncf_number = fields.Char(
        string='NCF',
        copy=False,
        readonly=True,
        tracking=True,
        index=True,
        help='Numero de Comprobante Fiscal'
    )

    l10n_do_ncf_type_id = fields.Many2one(
        'l10n_do_ncf.type',
        string='Tipo de NCF',
        tracking=True,
        compute='_compute_l10n_do_ncf_type_id',
        store=True,
        readonly=False,
        help='Tipo de comprobante fiscal a generar'
    )

    l10n_do_ncf_seq_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia NCF',
        readonly=True,
        copy=False,
        help='Secuencia utilizada para generar el NCF'
    )

    l10n_do_ncf_expiration = fields.Date(
        string='Vencimiento NCF',
        related='l10n_do_ncf_seq_id.expiration_date',
        store=True
    )

    # =========================================
    # ESTADO FISCAL (para auditoría)
    # =========================================

    l10n_do_fiscal_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('valid', 'Válido'),
        ('annulled', 'Anulado'),
        ('credited', 'Con NC Aplicada'),
    ], string='Estado Fiscal',
       default='pending',
       tracking=True,
       help='Estado fiscal del documento según DGII')

    # =========================================
    # CAMPOS PARA NOTAS DE CRÉDITO/DÉBITO
    # =========================================

    l10n_do_ncf_origin = fields.Char(
        string='NCF Afectado',
        copy=False,
        help='NCF de la factura original que se esta modificando (para NC/ND)'
    )

    l10n_do_origin_move_id = fields.Many2one(
        'account.move',
        string='Factura Origen',
        copy=False,
        domain="[('partner_id', '=', partner_id), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('l10n_do_ncf_number', '!=', False)]",
        help='Factura original que se esta modificando'
    )

    l10n_do_credit_note_reason = fields.Selection([
        ('01', '01 - Anulación total'),
        ('02', '02 - Corrección de errores'),
        ('03', '03 - Devolución de bienes'),
        ('04', '04 - Descuento posterior'),
        ('05', '05 - Ajuste de precio'),
        ('06', '06 - Otros'),
    ], string='Motivo NC/ND',
       help='Motivo de la Nota de Crédito o Débito (requerido por DGII)')

    # =========================================
    # OPCIÓN SIN NCF
    # =========================================

    l10n_do_ncf_required = fields.Boolean(
        string='Requiere NCF',
        default=True,
        help='Desmarcar para documentos que no requieren NCF (ej: exportaciones especiales)'
    )

    # =========================================
    # CAMPOS PARA COMPRAS (PROVEEDOR)
    # =========================================

    l10n_do_vendor_ncf = fields.Char(
        string='NCF Proveedor',
        copy=False,
        tracking=True,
        help='NCF del comprobante recibido del proveedor'
    )

    l10n_do_vendor_ncf_validated = fields.Boolean(
        string='NCF Validado',
        default=False,
        copy=False,
        help='Indica si el NCF del proveedor fue validado contra DGII'
    )

    l10n_do_vendor_ncf_validation_source = fields.Selection([
        ('local', 'Validación Local'),
        ('dgii', 'Validación DGII'),
        ('manual', 'Verificación Manual'),
    ], string='Fuente de Validación',
       default='local',
       help='Indica cómo fue validado el NCF del proveedor')

    l10n_do_fiscal_type = fields.Selection([
        ('fiscal', 'Fiscal (con NCF)'),
        ('informal', 'Compra Informal'),
        ('minor_expense', 'Gasto Menor'),
        ('exterior', 'Pago al Exterior'),
        ('special', 'Regimen Especial'),
        ('governmental', 'Gubernamental'),
        ('export', 'Exportacion'),
    ], string='Tipo Fiscal', default='fiscal')

    l10n_do_expense_type = fields.Selection([
        ('01', '01 - Gastos de Personal'),
        ('02', '02 - Gastos por Trabajos, Suministros y Servicios'),
        ('03', '03 - Arrendamientos'),
        ('04', '04 - Gastos de Activos Fijos'),
        ('05', '05 - Gastos de Representacion'),
        ('06', '06 - Otras Deducciones Admitidas'),
        ('07', '07 - Gastos Financieros'),
        ('08', '08 - Gastos Extraordinarios'),
        ('09', '09 - Compras y Gastos que forman parte del Costo de Venta'),
        ('10', '10 - Adquisiciones de Activos'),
        ('11', '11 - Gastos de Seguros'),
    ], string='Tipo de Gasto', default='02', help='Clasificacion de gasto para reporte 606')

    # =========================================
    # ASIGNACIÓN AUTOMÁTICA DE TIPO NCF
    # =========================================

    @api.depends('move_type', 'partner_id', 'reversed_entry_id')
    def _compute_l10n_do_ncf_type_id(self):
        """Asignar tipo NCF automáticamente según el tipo de documento y cliente"""
        for move in self:
            # Solo para documentos de venta
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue

            # No cambiar si ya tiene NCF generado
            if move.l10n_do_ncf_number:
                continue

            if move.move_type == 'out_refund':
                # NOTA DE CRÉDITO: SIEMPRE B04
                ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
                if ncf_type:
                    move.l10n_do_ncf_type_id = ncf_type.id

                # Copiar NCF origen si viene de reversión
                if move.reversed_entry_id and move.reversed_entry_id.l10n_do_ncf_number:
                    move.l10n_do_ncf_origin = move.reversed_entry_id.l10n_do_ncf_number
                    move.l10n_do_origin_move_id = move.reversed_entry_id.id

            elif move.move_type == 'out_invoice' and move.partner_id:
                # FACTURA DE VENTA: según tipo de cliente
                ncf_type = move._get_ncf_type_for_partner(move.partner_id)
                if ncf_type:
                    move.l10n_do_ncf_type_id = ncf_type.id

    def _get_ncf_type_for_partner(self, partner):
        """Obtener el tipo de NCF correcto según el tipo de cliente"""
        if not partner:
            return self.env['l10n_do_ncf.type'].search([('code', '=', '02')], limit=1)

        taxpayer_type = partner.l10n_do_dgii_tax_payer_type
        partner_vat = partner.vat
        partner_country = partner.country_id

        # Exportaciones: cliente extranjero
        if partner_country and partner_country.code != 'DO':
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '16')], limit=1)
            if ncf_type:
                return ncf_type

        # Gubernamental
        if taxpayer_type == 'governmental':
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '15')], limit=1)
            if ncf_type:
                return ncf_type

        # Régimen Especial
        if taxpayer_type == 'special_regime':
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '14')], limit=1)
            if ncf_type:
                return ncf_type

        # Contribuyente con RNC válido = Crédito Fiscal (B01)
        if taxpayer_type == 'taxpayer' and partner_vat:
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '01')], limit=1)
            if ncf_type:
                return ncf_type

        # Por defecto: Consumidor Final (B02)
        return self.env['l10n_do_ncf.type'].search([('code', '=', '02')], limit=1)

    def _get_ncf_type_for_move(self):
        """Obtener el tipo de NCF correcto según el tipo de documento"""
        self.ensure_one()

        if self.move_type == 'out_refund':
            return self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
        elif self.move_type == 'out_invoice' and self.partner_id:
            return self._get_ncf_type_for_partner(self.partner_id)

        return False

    # =========================================
    # ONCHANGE HANDLERS
    # =========================================

    @api.onchange('partner_id')
    def _onchange_partner_ncf_type(self):
        """Asignar tipo NCF automáticamente según el tipo de cliente"""
        if self.move_type == 'out_invoice' and self.partner_id:
            if not self.l10n_do_ncf_number:
                ncf_type = self._get_ncf_type_for_partner(self.partner_id)
                if ncf_type:
                    self.l10n_do_ncf_type_id = ncf_type.id

                # Advertencia si es exportación con ITBIS
                if self.partner_id.country_id and self.partner_id.country_id.code != 'DO':
                    has_itbis = any(
                        tax.amount > 0
                        for line in self.invoice_line_ids
                        for tax in line.tax_ids
                        if 'ITBIS' in tax.name.upper() or tax.amount == 18
                    )
                    if has_itbis:
                        return {
                            'warning': {
                                'title': _('Advertencia: Exportación con ITBIS'),
                                'message': _(
                                    'Este cliente es extranjero (Exportación B16).\n'
                                    'Las exportaciones NO pueden llevar ITBIS.\n'
                                    'Debe eliminar los impuestos antes de confirmar.'
                                )
                            }
                        }

    @api.onchange('l10n_do_origin_move_id')
    def _onchange_origin_move(self):
        """Copiar NCF de la factura origen al campo NCF Afectado"""
        if self.l10n_do_origin_move_id and self.l10n_do_origin_move_id.l10n_do_ncf_number:
            self.l10n_do_ncf_origin = self.l10n_do_origin_move_id.l10n_do_ncf_number

    @api.onchange('l10n_do_ncf_required')
    def _onchange_ncf_required(self):
        """Limpiar tipo NCF si no requiere NCF"""
        if not self.l10n_do_ncf_required:
            self.l10n_do_ncf_type_id = False

    @api.onchange('l10n_do_credit_note_reason', 'l10n_do_origin_move_id')
    def _onchange_credit_note_reason(self):
        """Validar monto cuando el motivo es Anulación Total"""
        if self.move_type == 'out_refund' and self.l10n_do_credit_note_reason == '01':
            if self.l10n_do_origin_move_id:
                origin = self.l10n_do_origin_move_id
                if abs(self.amount_total - origin.amount_total) > 0.01:
                    return {
                        'warning': {
                            'title': _('Advertencia: Monto incorrecto para Anulación Total'),
                            'message': _(
                                'Para Anulación Total (Motivo 01), el monto de la Nota de Crédito '
                                'debe ser exactamente igual al monto de la factura original.\n\n'
                                'Monto Factura Original: %s\n'
                                'Monto Nota de Crédito: %s'
                            ) % (origin.amount_total, self.amount_total)
                        }
                    }

    # =========================================
    # VALIDACIONES DGII CRÍTICAS
    # =========================================

    @api.constrains('l10n_do_ncf_type_id', 'move_type')
    def _check_ncf_type_for_document(self):
        """Validar que el tipo de NCF sea correcto para el tipo de documento"""
        for move in self:
            if not move.l10n_do_ncf_type_id:
                continue

            ncf_code = move.l10n_do_ncf_type_id.code

            # Nota de Crédito DEBE ser B04
            if move.move_type == 'out_refund' and ncf_code != '04':
                raise ValidationError(_(
                    'Las Notas de Crédito deben usar el tipo B04 (Nota de Crédito).\n'
                    'No está permitido usar %s para notas de crédito según normativa DGII.'
                ) % move.l10n_do_ncf_type_id.name)

            # Facturas NO pueden ser B04
            if move.move_type == 'out_invoice' and ncf_code == '04':
                raise ValidationError(_(
                    'Las Facturas no pueden usar el tipo B04 (Nota de Crédito).\n'
                    'Use B01, B02, B14, B15 o B16 según corresponda.'
                ))

    @api.constrains('move_type', 'partner_id', 'invoice_line_ids', 'state')
    def _check_export_no_itbis(self):
        """DGII: Las exportaciones (B16) NO pueden llevar ITBIS"""
        for move in self:
            if move.state != 'posted':
                continue

            if move.move_type != 'out_invoice':
                continue

            if not move.partner_id or not move.partner_id.country_id:
                continue

            # Solo aplica a clientes extranjeros (exportación)
            if move.partner_id.country_id.code == 'DO':
                continue

            # Verificar si hay ITBIS en las líneas
            for line in move.invoice_line_ids:
                for tax in line.tax_ids:
                    if tax.amount > 0 and ('ITBIS' in tax.name.upper() or tax.amount == 18):
                        raise ValidationError(_(
                            'Las exportaciones (B16) NO pueden llevar ITBIS según normativa DGII.\n\n'
                            'Cliente: %s (%s)\n'
                            'Impuesto encontrado: %s\n\n'
                            'Elimine los impuestos de las líneas antes de confirmar.'
                        ) % (move.partner_id.name, move.partner_id.country_id.name, tax.name))

    @api.constrains('l10n_do_ncf_origin', 'move_type', 'partner_id', 'l10n_do_origin_move_id',
                    'l10n_do_credit_note_reason', 'amount_total', 'state')
    def _check_ncf_origin_required(self):
        """Validaciones completas para Notas de Crédito según DGII"""
        for move in self:
            if move.move_type != 'out_refund' or move.state != 'posted':
                continue

            if not move.l10n_do_ncf_required:
                continue

            # 1. Validar que tiene NCF afectado
            if not move.l10n_do_ncf_origin:
                if move._is_demo_or_test_mode():
                    continue
                raise ValidationError(_(
                    'Las Notas de Crédito requieren el NCF Afectado.\n'
                    'Debe indicar el NCF de la factura original que está modificando.'
                ))

            # 2. Validar que tiene motivo
            if not move.l10n_do_credit_note_reason:
                raise ValidationError(_(
                    'Las Notas de Crédito requieren un Motivo.\n'
                    'Seleccione el motivo de la nota de crédito (Anulación, Devolución, etc.)'
                ))

            # 3. Validaciones con factura origen
            if move.l10n_do_origin_move_id:
                origin_move = move.l10n_do_origin_move_id

                # 3.1 Validar mismo cliente
                if origin_move.partner_id != move.partner_id:
                    raise ValidationError(_(
                        'El NCF Afectado pertenece a otro cliente.\n'
                        'NCF: %s - Cliente original: %s\n'
                        'Cliente actual: %s\n\n'
                        'La Nota de Crédito debe ser del mismo cliente.'
                    ) % (move.l10n_do_ncf_origin, origin_move.partner_id.name, move.partner_id.name))

                # 3.2 Validar que la factura origen está posted
                if origin_move.state != 'posted':
                    raise ValidationError(_(
                        'La factura origen debe estar confirmada (posted).\n'
                        'Factura: %s - Estado: %s'
                    ) % (origin_move.name, origin_move.state))

                # 3.3 CRÍTICO: Validar monto para Anulación Total (Motivo 01)
                if move.l10n_do_credit_note_reason == '01':
                    if abs(move.amount_total - origin_move.amount_total) > 0.01:
                        raise ValidationError(_(
                            'Para Anulación Total (Motivo 01), el monto de la Nota de Crédito '
                            'debe ser EXACTAMENTE igual al monto de la factura original.\n\n'
                            'Factura Original: %s\n'
                            'Monto Factura: %s\n'
                            'Monto Nota de Crédito: %s\n\n'
                            'Si desea hacer una anulación parcial, use otro motivo.'
                        ) % (origin_move.name, origin_move.amount_total, move.amount_total))

                # 3.4 Calcular total de NC existentes sobre esta factura
                existing_nc = self.search([
                    ('l10n_do_origin_move_id', '=', origin_move.id),
                    ('state', '=', 'posted'),
                    ('id', '!=', move.id),
                    ('move_type', '=', 'out_refund'),
                ])

                total_nc_existentes = sum(existing_nc.mapped('amount_total'))

                # 3.5 CRÍTICO: Validar que la factura no esté ya totalmente anulada
                if abs(total_nc_existentes - origin_move.amount_total) < 0.01:
                    raise ValidationError(_(
                        'La factura %s ya ha sido anulada totalmente.\n'
                        'No se pueden aplicar más Notas de Crédito.\n\n'
                        'NCF Factura: %s\n'
                        'Monto original: %s\n'
                        'Total NC aplicadas: %s'
                    ) % (origin_move.name, origin_move.l10n_do_ncf_number,
                         origin_move.amount_total, total_nc_existentes))

                # 3.6 Validar que no exceda el monto disponible
                if existing_nc:
                    monto_disponible = origin_move.amount_total - total_nc_existentes

                    # Si ya hay NC y el motivo actual es Anulación Total, bloquear
                    if move.l10n_do_credit_note_reason == '01':
                        raise ValidationError(_(
                            'La factura %s ya tiene Notas de Crédito aplicadas.\n'
                            'No se permite Anulación Total cuando ya existe otra NC.\n\n'
                            'NCF Factura: %s\n'
                            'Total NC existentes: %s\n'
                            'Monto disponible: %s\n\n'
                            'Use otro motivo para NC parcial.'
                        ) % (origin_move.name, origin_move.l10n_do_ncf_number,
                             total_nc_existentes, monto_disponible))

                    # Validar que no excede monto disponible
                    if move.amount_total > monto_disponible + 0.01:
                        raise ValidationError(_(
                            'El monto de la Nota de Crédito excede el saldo disponible.\n\n'
                            'Factura: %s\n'
                            'Monto original: %s\n'
                            'NC existentes: %s\n'
                            'Monto disponible: %s\n'
                            'Monto NC actual: %s\n\n'
                            'No puede aplicar más crédito del monto disponible.'
                        ) % (origin_move.name, origin_move.amount_total,
                             total_nc_existentes, monto_disponible, move.amount_total))

    @api.constrains('l10n_do_ncf_number', 'company_id')
    def _check_ncf_unique(self):
        """Validar que el NCF generado no esté duplicado"""
        for move in self:
            if move.l10n_do_ncf_number and move.move_type in ('out_invoice', 'out_refund'):
                existing = self.search([
                    ('l10n_do_ncf_number', '=', move.l10n_do_ncf_number),
                    ('company_id', '=', move.company_id.id),
                    ('id', '!=', move.id),
                    ('state', '!=', 'cancel'),
                ])
                if existing:
                    _logger.critical(
                        'NCF DUPLICADO DETECTADO: %s - Factura actual: %s - Existente: %s',
                        move.l10n_do_ncf_number, move.name, existing[0].name
                    )
                    raise ValidationError(_(
                        'El NCF %s ya existe.\n'
                        'Factura existente: %s\n\n'
                        'Contacte al administrador del sistema.'
                    ) % (move.l10n_do_ncf_number, existing[0].name))

    @api.constrains('l10n_do_vendor_ncf')
    def _check_vendor_ncf_format(self):
        """Validar formato del NCF del proveedor según estándar DGII"""
        for move in self:
            if move.l10n_do_vendor_ncf:
                ncf = move.l10n_do_vendor_ncf.strip().upper()

                # Validar formato completo: NCF tradicional o e-CF
                if not re.match(NCF_FULL_PATTERN, ncf):
                    raise ValidationError(_(
                        'El formato del NCF del proveedor no es válido.\n\n'
                        'Formatos aceptados:\n'
                        '- NCF tradicional: B0100000001 (11 caracteres)\n'
                        '  B + tipo (01-17) + 8 dígitos secuencia\n\n'
                        '- e-CF: E310000000001 (13 caracteres)\n'
                        '  E + tipo (31-47) + 10 dígitos secuencia\n\n'
                        'NCF ingresado: %s\n\n'
                        'Tipos NCF válidos: 01-04, 11-17\n'
                        'Tipos e-CF válidos: 31-34, 41-47'
                    ) % ncf)

    @api.constrains('l10n_do_vendor_ncf', 'partner_id', 'company_id')
    def _check_vendor_ncf_unique(self):
        """Validar que el NCF del proveedor no esté duplicado"""
        for move in self:
            if move.l10n_do_vendor_ncf and move.partner_id:
                existing = self.search([
                    ('l10n_do_vendor_ncf', '=', move.l10n_do_vendor_ncf),
                    ('partner_id', '=', move.partner_id.id),
                    ('company_id', '=', move.company_id.id),
                    ('id', '!=', move.id),
                    ('state', '!=', 'cancel'),
                ])
                if existing:
                    raise ValidationError(_(
                        'El NCF %s ya fue registrado para este proveedor.\n'
                        'Factura existente: %s\n\n'
                        'No puede duplicar el NCF del proveedor.'
                    ) % (move.l10n_do_vendor_ncf, existing[0].name))

    def _is_demo_or_test_mode(self):
        """Verificar si estamos en modo demo o test"""
        return self.env.context.get('install_mode') or \
               self.env.context.get('demo') or \
               self.env.registry.in_test_mode()

    # =========================================
    # GENERACIÓN DE NCF
    # =========================================

    def _get_ncf_sequence(self):
        """Obtener la secuencia NCF activa para el tipo de comprobante"""
        self.ensure_one()

        if not self.l10n_do_ncf_required:
            return False

        if not self.l10n_do_ncf_type_id:
            raise UserError(_(
                'No se ha definido el tipo de comprobante fiscal.\n'
                'Esto puede ocurrir si el cliente no tiene configurado correctamente su tipo de contribuyente.'
            ))

        sequence = self.env['l10n_do_ncf.sequence'].search([
            ('company_id', '=', self.company_id.id),
            ('ncf_type_id', '=', self.l10n_do_ncf_type_id.id),
            ('state', '=', 'active'),
        ], limit=1, order='id desc')

        if not sequence:
            raise UserError(_(
                'No hay secuencia NCF activa para el tipo "%s".\n\n'
                'Por favor, configure una secuencia en:\n'
                'Facturación → Configuración → NCF → Secuencias NCF'
            ) % self.l10n_do_ncf_type_id.name)

        return sequence

    def _generate_ncf(self):
        """Generar NCF para la factura"""
        self.ensure_one()

        if not self.l10n_do_ncf_required:
            _logger.info('Factura %s: No requiere NCF', self.name)
            return False

        if self.l10n_do_ncf_number:
            return self.l10n_do_ncf_number

        if self.move_type not in ('out_invoice', 'out_refund'):
            return False

        sequence = self._get_ncf_sequence()
        if not sequence:
            return False

        try:
            ncf = sequence.get_next_ncf()
            self.write({
                'l10n_do_ncf_number': ncf,
                'l10n_do_ncf_seq_id': sequence.id,
                'l10n_do_fiscal_status': 'valid',
            })
            _logger.info('NCF generado: %s para factura %s', ncf, self.name)
            return ncf
        except Exception as e:
            _logger.error('Error generando NCF para %s: %s', self.name, str(e))
            raise

    # =========================================
    # OVERRIDE: ACTION_POST
    # =========================================

    def action_post(self):
        """Override para generar NCF al confirmar factura"""
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund') and move.l10n_do_ncf_required:
                # Asignar tipo NCF si no tiene
                if not move.l10n_do_ncf_type_id:
                    ncf_type = move._get_ncf_type_for_move()
                    if ncf_type:
                        move.l10n_do_ncf_type_id = ncf_type.id

                # Validar licencia
                if move.l10n_do_ncf_type_id and not move.l10n_do_ncf_number:
                    license_config = self.env['l10n_do_ncf.license.config'].search([
                        ('company_id', '=', move.company_id.id)
                    ], limit=1)

                    if not license_config:
                        raise UserError(_(
                            'No hay licencia NCF configurada para la compañía %s.\n\n'
                            'Configure la licencia en:\n'
                            'Facturación → Configuración → NCF → Licencia'
                        ) % move.company_id.name)

                    # Validación estricta de vencimiento (incluyendo hoy)
                    today = fields.Date.today()
                    if license_config.expiration_date and license_config.expiration_date <= today:
                        _logger.critical(
                            'NCF BLOQUEADO: Licencia vencida para %s - Factura: %s - Vencimiento: %s',
                            move.company_id.name, move.name, license_config.expiration_date
                        )
                        raise UserError(_(
                            'La licencia NCF ha expirado.\n'
                            'Fecha de vencimiento: %s\n'
                            'Fecha actual: %s\n\n'
                            'Renueve su licencia NCF para continuar facturando.'
                        ) % (license_config.expiration_date, today))

                    if not license_config.is_valid:
                        _logger.critical(
                            'NCF BLOQUEADO: Licencia inválida para %s - Factura: %s',
                            move.company_id.name, move.name
                        )
                        raise UserError(_(
                            'La licencia NCF no es válida.\n\n'
                            'Verifique la configuración de su licencia NCF.'
                        ))

        # Llamar al método original
        result = super().action_post()

        # Generar NCF después de confirmar
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund') and move.l10n_do_ncf_required:
                if not move.l10n_do_ncf_number:
                    move._generate_ncf()

                # Actualizar estado fiscal de factura origen si es NC
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
                        origin.l10n_do_fiscal_status = 'credited'

        return result

    # =========================================
    # MÉTODOS DE VALIDACIÓN NCF PROVEEDOR
    # =========================================

    def action_validate_vendor_ncf(self):
        """Validar NCF del proveedor - Validación local"""
        self.ensure_one()

        if not self.l10n_do_vendor_ncf:
            raise UserError(_('Ingrese el NCF del proveedor primero.'))

        if not self.partner_id or not self.partner_id.vat:
            raise UserError(_('El proveedor debe tener un RNC configurado.'))

        ncf = self.l10n_do_vendor_ncf.strip().upper()

        # Validar formato
        if not re.match(NCF_FULL_PATTERN, ncf):
            raise UserError(_(
                'Formato de NCF inválido.\n'
                'Formatos válidos: B0100000001 (11 chars) o E310000000001 (13 chars)'
            ))

        # Marcar como validado localmente
        self.write({
            'l10n_do_vendor_ncf': ncf,
            'l10n_do_vendor_ncf_validated': True,
            'l10n_do_vendor_ncf_validation_source': 'local',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('NCF Validado (Local)'),
                'message': _(
                    'El NCF %s ha sido validado localmente.\n'
                    'Para validación oficial, consulte dgii.gov.do'
                ) % ncf,
                'type': 'success',
                'sticky': False,
            }
        }

    # =========================================
    # RETENCIONES
    # =========================================

    l10n_do_retention_ids = fields.One2many(
        'l10n_do_ncf.retention.line',
        'move_id',
        string='Retenciones'
    )

    l10n_do_total_isr_retention = fields.Monetary(
        string='Retención ISR',
        compute='_compute_retentions',
        store=True
    )

    l10n_do_total_itbis_retention = fields.Monetary(
        string='Retención ITBIS',
        compute='_compute_retentions',
        store=True
    )

    l10n_do_amount_to_pay = fields.Monetary(
        string='Monto a Pagar',
        compute='_compute_retentions',
        store=True
    )

    @api.depends('l10n_do_retention_ids', 'l10n_do_retention_ids.retention_amount', 'amount_total')
    def _compute_retentions(self):
        """Calcular totales de retenciones"""
        for move in self:
            isr_total = 0.0
            itbis_total = 0.0

            for retention in move.l10n_do_retention_ids:
                if retention.retention_type_id.retention_type == 'isr':
                    isr_total += retention.retention_amount
                elif retention.retention_type_id.retention_type == 'itbis':
                    itbis_total += retention.retention_amount

            move.l10n_do_total_isr_retention = isr_total
            move.l10n_do_total_itbis_retention = itbis_total
            move.l10n_do_amount_to_pay = move.amount_total - isr_total - itbis_total

    def action_add_retention(self):
        """Abrir wizard para agregar retención"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agregar Retención'),
            'res_model': 'l10n_do_ncf.retention.line',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_move_id': self.id,
                'default_currency_id': self.currency_id.id,
                'default_base_amount': self.amount_untaxed,
            }
        }

    def action_clear_retentions(self):
        """Eliminar todas las retenciones"""
        self.l10n_do_retention_ids.unlink()

    @api.onchange('l10n_do_vendor_ncf')
    def _onchange_vendor_ncf(self):
        """Limpiar y formatear NCF del proveedor"""
        if self.l10n_do_vendor_ncf:
            self.l10n_do_vendor_ncf = self.l10n_do_vendor_ncf.strip().upper()

    # =========================================
    # NOTA: NO USAMOS _sql_constraints
    # El índice único se crea en hooks.py
    # para manejar correctamente valores NULL
    # =========================================