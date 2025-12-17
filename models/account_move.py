# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import re
import requests
import logging
import traceback

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_do_ncf_number = fields.Char(
        string='NCF',
        copy=False,
        readonly=True,
        tracking=True,
        help='Numero de Comprobante Fiscal'
    )
    l10n_do_ncf_type_id = fields.Many2one(
        'l10n_do_ncf.type',
        string='Tipo de NCF',
        tracking=True,
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

    def _get_ncf_type_for_partner(self, partner):
        """Obtener el tipo de NCF correcto segun el tipo de cliente"""
        if not partner:
            return self.env['l10n_do_ncf.type'].search([('code', '=', '02')], limit=1)

        taxpayer_type = partner.l10n_do_dgii_tax_payer_type
        partner_vat = partner.vat

        if taxpayer_type == 'governmental':
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '15')], limit=1)
            if ncf_type:
                return ncf_type

        if taxpayer_type == 'special_regime':
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '14')], limit=1)
            if ncf_type:
                return ncf_type

        if taxpayer_type == 'taxpayer' and partner_vat:
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '01')], limit=1)
            if ncf_type:
                return ncf_type

        return self.env['l10n_do_ncf.type'].search([('code', '=', '02')], limit=1)

    def _get_ncf_type_for_move(self):
        """Obtener el tipo de NCF correcto segun el tipo de documento"""
        self.ensure_one()

        if self.move_type == 'out_invoice' and self.partner_id:
            return self._get_ncf_type_for_partner(self.partner_id)
        elif self.move_type == 'out_refund':
            return self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)

        return False

    @api.model_create_multi
    def create(self, vals_list):
        """Asignar tipo NCF y datos automaticamente al crear el documento"""
        moves = super().create(vals_list)

        for move in moves:
            vals_to_update = {}

            if move.move_type == 'out_refund':
                if not move.l10n_do_ncf_type_id:
                    ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
                    if ncf_type:
                        vals_to_update['l10n_do_ncf_type_id'] = ncf_type.id

                if move.reversed_entry_id:
                    if move.reversed_entry_id.l10n_do_ncf_number and not move.l10n_do_ncf_origin:
                        vals_to_update['l10n_do_ncf_origin'] = move.reversed_entry_id.l10n_do_ncf_number
                    if not move.l10n_do_origin_move_id:
                        vals_to_update['l10n_do_origin_move_id'] = move.reversed_entry_id.id

            elif move.move_type == 'out_invoice' and move.partner_id:
                if not move.l10n_do_ncf_type_id:
                    ncf_type = move._get_ncf_type_for_partner(move.partner_id)
                    if ncf_type:
                        vals_to_update['l10n_do_ncf_type_id'] = ncf_type.id

            if vals_to_update:
                move.write(vals_to_update)

        return moves

    def write(self, vals):
        """Interceptar escritura para asignar tipo NCF en reversiones"""
        result = super().write(vals)

        if 'reversed_entry_id' in vals:
            for move in self:
                if move.move_type == 'out_refund' and move.reversed_entry_id:
                    vals_to_update = {}

                    if not move.l10n_do_ncf_type_id:
                        ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
                        if ncf_type:
                            vals_to_update['l10n_do_ncf_type_id'] = ncf_type.id

                    if move.reversed_entry_id.l10n_do_ncf_number and not move.l10n_do_ncf_origin:
                        vals_to_update['l10n_do_ncf_origin'] = move.reversed_entry_id.l10n_do_ncf_number

                    if not move.l10n_do_origin_move_id:
                        vals_to_update['l10n_do_origin_move_id'] = move.reversed_entry_id.id

                    if vals_to_update:
                        super(AccountMove, move).write(vals_to_update)

        return result

    @api.onchange('partner_id', 'move_type')
    def _onchange_partner_ncf_type(self):
        """Asignar tipo NCF automaticamente segun el tipo de cliente"""
        if self.move_type == 'out_invoice' and self.partner_id:
            ncf_type = self._get_ncf_type_for_partner(self.partner_id)
            if ncf_type:
                self.l10n_do_ncf_type_id = ncf_type.id

        elif self.move_type == 'out_refund':
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
            if ncf_type:
                self.l10n_do_ncf_type_id = ncf_type.id

    @api.onchange('l10n_do_origin_move_id')
    def _onchange_origin_move(self):
        """Copiar NCF de la factura origen al campo NCF Afectado"""
        if self.l10n_do_origin_move_id and self.l10n_do_origin_move_id.l10n_do_ncf_number:
            self.l10n_do_ncf_origin = self.l10n_do_origin_move_id.l10n_do_ncf_number

    @api.constrains('l10n_do_ncf_origin', 'move_type')
    def _check_ncf_origin_required(self):
        """Validar que las Notas de Credito tengan NCF afectado"""
        for move in self:
            if move.move_type == 'out_refund' and move.state == 'posted':
                if not move.l10n_do_ncf_origin:
                    # Saltar en modo demo
                    if move._is_demo_or_test_mode():
                        continue
                    raise ValidationError(_(
                        'Las Notas de Credito requieren el NCF Afectado.\n'
                        'Debe indicar el NCF de la factura original que esta modificando.'
                    ))

    @api.constrains('l10n_do_ncf_number', 'company_id')
    def _check_ncf_unique(self):
        """Validar que el NCF generado no este duplicado (para ventas)"""
        for move in self:
            if move.l10n_do_ncf_number and move.move_type in ('out_invoice', 'out_refund'):
                existing = self.search([
                    ('l10n_do_ncf_number', '=', move.l10n_do_ncf_number),
                    ('company_id', '=', move.company_id.id),
                    ('id', '!=', move.id),
                    ('state', '!=', 'cancel'),
                ])
                if existing:
                    raise ValidationError(_(
                        'El NCF %s ya existe.\n'
                        'Factura existente: %s\n\n'
                        'Contacte al administrador del sistema.'
                    ) % (move.l10n_do_ncf_number, existing[0].name))

    @api.constrains('l10n_do_vendor_ncf')
    def _check_vendor_ncf_format(self):
        """Validar formato del NCF del proveedor"""
        ncf_pattern = r'^[BE]\d{10}$'
        for move in self:
            if move.l10n_do_vendor_ncf:
                ncf = move.l10n_do_vendor_ncf.strip().upper()
                if not re.match(ncf_pattern, ncf):
                    raise ValidationError(_(
                        'El formato del NCF del proveedor no es valido.\n'
                        'Formato correcto: B0100000001 (11 caracteres)\n'
                        'B = Serie, 01 = Tipo, 00000001 = Secuencia'
                    ))

    @api.constrains('l10n_do_vendor_ncf', 'partner_id', 'company_id')
    def _check_vendor_ncf_unique(self):
        """Validar que el NCF del proveedor no este duplicado"""
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
                        'Ya existe una factura con el NCF %s para este proveedor.\n'
                        'Factura existente: %s'
                    ) % (move.l10n_do_vendor_ncf, existing[0].name))

    def _get_ncf_sequence(self):
        """Obtener la secuencia NCF activa para el tipo de comprobante"""
        self.ensure_one()
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
                'No hay una secuencia NCF activa para "%s".\n\n'
                'Para configurar una secuencia:\n'
                '1. Vaya a Facturacion > Configuracion > NCF > Secuencias\n'
                '2. Cree una nueva secuencia para este tipo\n'
                '3. Ingrese el rango autorizado por DGII\n'
                '4. Active la secuencia'
            ) % self.l10n_do_ncf_type_id.name)

        return sequence

    def _generate_ncf(self):
        """Generar el NCF para la factura"""
        self.ensure_one()
        if self.l10n_do_ncf_number:
            return self.l10n_do_ncf_number

        sequence = self._get_ncf_sequence()
        ncf = sequence.get_next_ncf()

        self.write({
            'l10n_do_ncf_number': ncf,
            'l10n_do_ncf_seq_id': sequence.id,
        })
        return ncf

    def _is_demo_or_test_mode(self):
        """Detectar si estamos en modo demo o test"""
        # Verificar contexto
        if self.env.context.get('install_mode'):
            _logger.info("NCF: Modo demo detectado por install_mode")
            return True
        if self.env.context.get('module'):
            _logger.info("NCF: Modo demo detectado por module context")
            return True
        if self.env.context.get('demo'):
            _logger.info("NCF: Modo demo detectado por demo context")
            return True
        if self.env.context.get('test_mode'):
            _logger.info("NCF: Modo demo detectado por test_mode")
            return True
        if self.env.context.get('load_demo_data'):
            _logger.info("NCF: Modo demo detectado por load_demo_data")
            return True
        # Verificar registry en modo test
        if hasattr(self.env.registry, 'in_test_mode') and self.env.registry.in_test_mode():
            _logger.info("NCF: Modo demo detectado por registry.in_test_mode")
            return True
        # Verificar stack trace para account_demo
        stack = traceback.format_stack()
        stack_str = ''.join(stack)
        if 'account_demo' in stack_str or '_post_load_demo_data' in stack_str or 'force-demo' in stack_str:
            _logger.info("NCF: Modo demo detectado por stack trace (account_demo)")
            return True
        return False

    def action_post(self):
        """Validar licencia y generar NCF al confirmar factura"""
        for move in self:
            # Saltar validaciones NCF en modo demo
            if move._is_demo_or_test_mode():
                continue

            if move.move_type in ('out_invoice', 'out_refund'): 

                if move.move_type == 'out_refund' and not move.l10n_do_ncf_origin:
                    raise UserError(_(
                        'Debe indicar el NCF Afectado.\n\n'
                        'Las Notas de Credito deben referenciar el NCF de la factura original.'
                    ))

                if not move.l10n_do_ncf_type_id:
                    ncf_type = move._get_ncf_type_for_move()
                    if ncf_type:
                        move.l10n_do_ncf_type_id = ncf_type.id

                if move.l10n_do_ncf_type_id and not move.l10n_do_ncf_number:
                    license_config = self.env['l10n_do_ncf.license.config'].search([
                        ('company_id', '=', move.company_id.id)
                    ], limit=1)

                    if not license_config:
                        raise UserError(_(
                            'Licencia NCF no configurada.\n\n'
                            'Para configurar su licencia:\n'
                            '1. Vaya a Facturacion > Configuracion > NCF > Licencia NCF\n'
                            '2. Ingrese su clave de licencia\n'
                            '3. Ingrese el RNC de su empresa\n'
                            '4. Haga clic en Validar Licencia'
                        ))

                    if not license_config.is_valid:
                        raise UserError(_(
                            'Licencia NCF no valida o expirada.\n\n'
                            'Estado: %s\n'
                            'Mensaje: %s\n\n'
                            'Contacte a soporte para renovar su licencia.'
                        ) % (license_config.status, license_config.validation_message or ''))

                    move._generate_ncf()

        return super().action_post()

    def _get_ncf_type_from_number(self, ncf):
        """Extraer el tipo de NCF del numero"""
        if ncf and len(ncf) >= 3:
            return ncf[1:3]
        return None

    def _validate_ncf_type_logic(self, ncf, partner):
        """Validacion inteligente del tipo de NCF"""
        warnings = []
        errors = []

        ncf_type_code = self._get_ncf_type_from_number(ncf)
        if not ncf_type_code:
            return warnings, errors

        rnc = partner.vat or ''
        rnc_clean = re.sub(r'[^0-9]', '', rnc)
        is_cedula = len(rnc_clean) == 11

        if ncf_type_code == '01':
            if is_cedula:
                errors.append(_('NCF tipo B01 no puede ser emitido por personas fisicas.'))

        elif ncf_type_code == '02':
            errors.append(_('NCF tipo B02 no es valido para facturas de compra.'))

        elif ncf_type_code == '03':
            warnings.append(_('NCF tipo B03 es una Nota de Debito.'))

        elif ncf_type_code == '04':
            warnings.append(_('NCF tipo B04 es una Nota de Credito.'))

        elif ncf_type_code == '14':
            warnings.append(_('NCF tipo B14 es para Regimenes Especiales.'))

        elif ncf_type_code == '15':
            warnings.append(_('NCF tipo B15 solo puede ser emitido por entidades del Estado.'))

        return warnings, errors

    def _check_ncf_sequence_logic(self, ncf, partner):
        """Detectar secuencias sospechosas"""
        warnings = []

        last_invoice = self.search([
            ('partner_id', '=', partner.id),
            ('l10n_do_vendor_ncf', '!=', False),
            ('l10n_do_vendor_ncf', '!=', ncf),
            ('state', '!=', 'cancel'),
        ], order='invoice_date desc, id desc', limit=1)

        if last_invoice and last_invoice.l10n_do_vendor_ncf:
            last_ncf = last_invoice.l10n_do_vendor_ncf

            if ncf[:3] == last_ncf[:3]:
                try:
                    current_seq = int(ncf[3:])
                    last_seq = int(last_ncf[3:])

                    if current_seq < last_seq:
                        warnings.append(_('Alerta: NCF menor que el ultimo recibido.'))

                    elif current_seq - last_seq > 1000:
                        warnings.append(_('Alerta: Salto grande en secuencia NCF.'))

                except ValueError:
                    pass

        return warnings

    def action_validate_vendor_ncf(self):
        """Validar NCF del proveedor"""
        self.ensure_one()

        if not self.l10n_do_vendor_ncf:
            raise UserError(_('Ingrese el NCF del proveedor para validar.'))

        if not self.partner_id:
            raise UserError(_('Debe seleccionar un proveedor.'))

        if not self.partner_id.vat:
            raise UserError(_('El proveedor debe tener un RNC/Cedula configurado.'))

        ncf = self.l10n_do_vendor_ncf.strip().upper()
        self.l10n_do_vendor_ncf = ncf

        ncf_pattern = r'^[BE]\d{10}$'
        if not re.match(ncf_pattern, ncf):
            raise UserError(_('El formato del NCF no es valido. Formato: B0100000001'))

        rnc = re.sub(r'[^0-9]', '', self.partner_id.vat)

        # Validar RNC del proveedor contra DGII
        try:
            # Intentar API local primero
            try:
                url = f"http://localhost:5000/api/v1/rnc/{rnc}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('found'):
                        rnc_status = data.get('status', 'ACTIVO')
                        if rnc_status != 'ACTIVO':
                            raise UserError(_('El RNC del proveedor no esta ACTIVO en DGII.'))
            except requests.exceptions.RequestException:
                # Intentar API pública
                url = "https://rnc.megaplus.com.do/api/consulta"
                response = requests.post(
                    url,
                    json={'rnc': rnc},
                    timeout=10,
                    headers={'Content-Type': 'application/json'}
                )
                if response.status_code == 200:
                    data = response.json()
                    if not data.get('error') and data.get('estado'):
                        if data.get('estado') != 'ACTIVO':
                            raise UserError(_('El RNC del proveedor no esta ACTIVO en DGII.'))
                    elif data.get('error'):
                        _logger.warning(f"NCF: RNC {rnc} no encontrado en DGII")
        except requests.exceptions.RequestException:
            # Si falla la conexión, continuar sin validar
            _logger.warning(f"NCF: No se pudo validar RNC {rnc} - API no disponible")
            pass

        existing = self.search([
            ('l10n_do_vendor_ncf', '=', ncf),
            ('partner_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
            ('id', '!=', self.id),
            ('state', '!=', 'cancel'),
        ])

        if existing:
            raise UserError(_('Este NCF ya fue registrado. Factura: %s') % existing[0].name)

        warnings, errors = self._validate_ncf_type_logic(ncf, self.partner_id)
        if errors:
            raise UserError('\n\n'.join(errors))

        seq_warnings = self._check_ncf_sequence_logic(ncf, self.partner_id)
        warnings.extend(seq_warnings)

        self.l10n_do_vendor_ncf_validated = True

        ncf_type_code = self._get_ncf_type_from_number(ncf)
        ncf_type_names = {
            '01': 'Credito Fiscal', '02': 'Consumidor Final',
            '03': 'Nota de Debito', '04': 'Nota de Credito',
            '11': 'Compras', '13': 'Gastos Menores',
            '14': 'Regimen Especial', '15': 'Gubernamental',
        }
        ncf_type_name = ncf_type_names.get(ncf_type_code, 'Otro')

        message = _('NCF: %s (%s)\nProveedor: %s') % (ncf, ncf_type_name, self.partner_id.name)

        if warnings:
            message += '\n\n' + '\n'.join(warnings)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('NCF Validado'),
                'message': message,
                'type': 'warning' if warnings else 'success',
                'sticky': bool(warnings),
            }
        }

    def _get_l10n_do_amounts(self):
        """Calcular montos para reportes DGII"""
        self.ensure_one()
        itbis_amount = 0.0
        exempt_amount = 0.0
        taxed_amount = 0.0

        for line in self.invoice_line_ids:
            line_taxes = line.tax_ids.filtered(lambda t: 'ITBIS' in t.name.upper())
            if line_taxes:
                taxed_amount += line.price_subtotal
                for tax in line_taxes:
                    itbis_amount += line.price_subtotal * (tax.amount / 100)
            else:
                exempt_amount += line.price_subtotal

        return {
            'itbis_amount': itbis_amount,
            'exempt_amount': exempt_amount,
            'taxed_amount': taxed_amount,
            'total_amount': self.amount_total,
        }

    @api.onchange('l10n_do_vendor_ncf')
    def _onchange_vendor_ncf(self):
        """Limpiar y formatear NCF del proveedor"""
        if self.l10n_do_vendor_ncf:
            self.l10n_do_vendor_ncf = self.l10n_do_vendor_ncf.strip().upper()
            self.l10n_do_vendor_ncf_validated = False
