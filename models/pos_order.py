# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/pos_order.py
# Descripción: Extensión de Punto de Venta con NCF
# Compatibilidad: Odoo 19

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
import re

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    """Configuración NCF para cada Punto de Venta"""
    _inherit = 'pos.config'

    # =========================================
    # CONFIGURACIÓN NCF PARA ESTE POS
    # =========================================
    l10n_do_ncf_enabled = fields.Boolean(
        string='Habilitar NCF',
        default=True,
        help='Habilitar generación de NCF en este punto de venta'
    )

    l10n_do_ncf_sequence_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia NCF (Consumidor Final)',
        domain="[('ncf_type_id.prefix', '=', 'B02'), ('state', '=', 'active')]",
        help='Secuencia NCF para ventas a consumidor final (B02)'
    )

    l10n_do_ncf_fiscal_sequence_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia NCF (Crédito Fiscal)',
        domain="[('ncf_type_id.prefix', '=', 'B01'), ('state', '=', 'active')]",
        help='Secuencia NCF para ventas con crédito fiscal (B01)'
    )

    l10n_do_ncf_special_sequence_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia NCF (Régimen Especial)',
        domain="[('ncf_type_id.prefix', '=', 'B14'), ('state', '=', 'active')]",
        help='Secuencia NCF para régimen especial (B14)'
    )

    l10n_do_ncf_gov_sequence_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia NCF (Gubernamental)',
        domain="[('ncf_type_id.prefix', '=', 'B15'), ('state', '=', 'active')]",
        help='Secuencia NCF para ventas gubernamentales (B15)'
    )

    # =========================================
    # CLIENTE POR DEFECTO (opcional, por POS)
    # =========================================
    l10n_do_pos_default_partner_id = fields.Many2one(
        'res.partner',
        string='Cliente por Defecto',
        help='Cliente que se asigna automaticamente al abrir una nueva orden.\n'
             'Dejar vacio para no asignar ninguno (comportamiento estandar).\n'
             'Si el contacto tiene marcado "Es una empresa", Odoo activara '
             'automaticamente la opcion de Factura al asignarlo.'
    )

    # NOTA (Odoo 19): NO sobreescribir _load_pos_data_fields aqui.
    # pos.config hereda la implementacion de pos.load.mixin, que devuelve
    # una lista vacia; en Odoo, read([]) significa "leer TODOS los campos".
    # Por eso l10n_do_pos_default_partner_id ya viaja al frontend sin hacer
    # nada. Si se sobreescribe devolviendo solo nuestros campos, el POS deja
    # de recibir el resto (use_pricelist, etc.) y falla al abrir la sesion.

    def _get_ncf_sequence_for_partner(self, partner):
        """Obtener la secuencia NCF correcta según el tipo de cliente"""
        self.ensure_one()

        if not partner or not partner.l10n_do_dgii_tax_payer_type:
            # Sin cliente o sin tipo = Consumidor Final (B02)
            return self.l10n_do_ncf_sequence_id

        taxpayer_type = partner.l10n_do_dgii_tax_payer_type

        if taxpayer_type == 'taxpayer':
            return self.l10n_do_ncf_fiscal_sequence_id or self.l10n_do_ncf_sequence_id
        elif taxpayer_type == 'special_regime':
            return self.l10n_do_ncf_special_sequence_id or self.l10n_do_ncf_sequence_id
        elif taxpayer_type == 'governmental':
            return self.l10n_do_ncf_gov_sequence_id or self.l10n_do_ncf_sequence_id
        else:
            # final_consumer, non_taxpayer, etc = B02
            return self.l10n_do_ncf_sequence_id

    def _get_ncf_type_name(self, partner):
        """Obtener nombre del tipo de NCF para mensajes de error"""
        if not partner or not partner.l10n_do_dgii_tax_payer_type:
            return 'Consumidor Final (B02)'

        mapping = {
            'taxpayer': 'Crédito Fiscal (B01)',
            'final_consumer': 'Consumidor Final (B02)',
            'non_taxpayer': 'Consumidor Final (B02)',
            'special_regime': 'Régimen Especial (B14)',
            'governmental': 'Gubernamental (B15)',
        }
        return mapping.get(partner.l10n_do_dgii_tax_payer_type, 'Consumidor Final (B02)')


class ResPartner(models.Model):
    """Exponer campos NCF del contacto al frontend del POS.

    NOTA (Odoo 19): reemplaza al antiguo PosSession._loader_params_res_partner,
    que fue eliminado en Odoo 18+.

    A diferencia de pos.config y pos.order, res.partner SI declara una lista
    explicita de campos en su _load_pos_data_fields, por lo que aqui si es
    necesario (y correcto) extenderla con super() + [...].
    """
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            'l10n_do_dgii_tax_payer_type',
            'l10n_do_rnc_validated',
            'l10n_do_dgii_status',
        ]


class PosOrder(models.Model):
    """Extensión de órdenes POS con NCF"""
    _inherit = 'pos.order'

    # =========================================
    # CAMPOS NCF
    # =========================================
    l10n_do_ncf_number = fields.Char(
        string='NCF',
        readonly=True,
        copy=False,
        help='Número de Comprobante Fiscal'
    )

    l10n_do_ncf_type = fields.Selection([
        ('B01', 'B01 - Crédito Fiscal'),
        ('B02', 'B02 - Consumidor Final'),
        ('B14', 'B14 - Régimen Especial'),
        ('B15', 'B15 - Gubernamental'),
    ], string='Tipo NCF',
        readonly=True,
        copy=False
    )

    l10n_do_ncf_seq_id = fields.Many2one(
        'l10n_do_ncf.sequence',
        string='Secuencia NCF',
        readonly=True,
        copy=False
    )

    l10n_do_partner_vat = fields.Char(
        string='RNC/Cédula',
        compute='_compute_partner_vat',
        store=True
    )

    @api.depends('partner_id', 'partner_id.vat')
    def _compute_partner_vat(self):
        for order in self:
            order.l10n_do_partner_vat = order.partner_id.vat if order.partner_id else ''

    # NOTA (Odoo 19): NO sobreescribir _load_pos_data_fields aqui.
    # Igual que pos.config, pos.order hereda la implementacion vacia de
    # pos.load.mixin, que carga TODOS los campos. Los campos NCF
    # (l10n_do_ncf_number, l10n_do_ncf_type, l10n_do_partner_vat) ya llegan
    # al frontend sin declararlos. Sobreescribir aqui limitaria la orden a
    # esos tres campos y rompe el POS.

    # =========================================
    # MÉTODOS DE GENERACIÓN NCF
    # =========================================
    def _get_ncf_type_from_partner(self):
        """Determinar tipo de NCF según el cliente"""
        self.ensure_one()

        if not self.partner_id or not self.partner_id.l10n_do_dgii_tax_payer_type:
            return 'B02'

        mapping = {
            'taxpayer': 'B01',
            'final_consumer': 'B02',
            'non_taxpayer': 'B02',
            'special_regime': 'B14',
            'governmental': 'B15',
        }

        return mapping.get(self.partner_id.l10n_do_dgii_tax_payer_type, 'B02')

    def _validate_ncf_sequence_available(self):
        """Validar que existe secuencia NCF antes de procesar el pago"""
        self.ensure_one()

        if not self.config_id.l10n_do_ncf_enabled:
            return True

        sequence = self.config_id._get_ncf_sequence_for_partner(self.partner_id)
        ncf_type_name = self.config_id._get_ncf_type_name(self.partner_id)

        if not sequence:
            raise ValidationError(_(
                'No se puede procesar la venta.\n\n'
                'No hay secuencia NCF configurada para: %s\n\n'
                'Configure la secuencia en:\n'
                'Punto de Venta → Configuración → %s → Pestaña NCF'
            ) % (ncf_type_name, self.config_id.name))

        # Verificar que la secuencia tiene NCF disponibles
        if sequence.available_qty <= 0:
            raise ValidationError(_(
                'No se puede procesar la venta.\n\n'
                'La secuencia NCF "%s" no tiene comprobantes disponibles.\n'
                'Disponibles: %s\n\n'
                'Solicite una nueva secuencia a la DGII.'
            ) % (sequence.display_name, sequence.available_qty))

        # Verificar vencimiento
        if sequence.expiration_date and sequence.aplica_vencimiento:
            from datetime import date
            if sequence.expiration_date < date.today():
                raise ValidationError(_(
                    'No se puede procesar la venta.\n\n'
                    'La secuencia NCF "%s" está vencida.\n'
                    'Fecha de vencimiento: %s\n\n'
                    'Solicite una nueva secuencia a la DGII.'
                ) % (sequence.display_name, sequence.expiration_date))

        return True

    def _generate_ncf(self):
        """Generar NCF para la orden POS"""
        self.ensure_one()

        if not self.config_id.l10n_do_ncf_enabled:
            return False

        if self.l10n_do_ncf_number:
            return self.l10n_do_ncf_number

        # Validar secuencia disponible
        self._validate_ncf_sequence_available()

        ncf_type = self._get_ncf_type_from_partner()
        sequence = self.config_id._get_ncf_sequence_for_partner(self.partner_id)

        try:
            ncf = sequence.get_next_ncf()

            self.write({
                'l10n_do_ncf_number': ncf,
                'l10n_do_ncf_type': ncf_type,
                'l10n_do_ncf_seq_id': sequence.id,
            })

            _logger.info('POS NCF: Generado %s para orden %s', ncf, self.name)
            return ncf

        except Exception as e:
            _logger.error('POS NCF: Error generando NCF - %s', str(e))
            raise UserError(_('Error generando NCF: %s') % str(e))

    def action_pos_order_paid(self):
        """Override: Generar NCF al marcar como pagado"""
        # Validar ANTES de procesar el pago
        for order in self:
            if order.config_id.l10n_do_ncf_enabled:
                order._validate_ncf_sequence_available()

        # Procesar pago
        res = super().action_pos_order_paid()

        # Generar NCF después del pago exitoso
        for order in self:
            if order.config_id.l10n_do_ncf_enabled and not order.l10n_do_ncf_number:
                order._generate_ncf()

        return res

    # =========================================
    # MÉTODOS PARA UI DEL POS
    # =========================================
    @api.model
    def search_partner_by_vat(self, vat):
        """Buscar cliente por RNC/Cédula desde el POS"""
        vat_clean = re.sub(r'[^0-9]', '', vat or '')

        if not vat_clean:
            return False

        partner = self.env['res.partner'].search([
            '|',
            ('vat', '=', vat_clean),
            ('vat', '=', vat),
        ], limit=1)

        if partner:
            return {
                'id': partner.id,
                'name': partner.name,
                'vat': partner.vat,
                'l10n_do_dgii_tax_payer_type': partner.l10n_do_dgii_tax_payer_type,
                'l10n_do_rnc_validated': partner.l10n_do_rnc_validated,
            }

        return False

    @api.model
    def create_partner_from_pos(self, vat, name=None):
        """Crear cliente desde el POS con validación DGII"""
        partner = self.env['res.partner'].create_quick_from_rnc(
            vat,
            name=name or None
        )

        return {
            'id': partner.id,
            'name': partner.name,
            'vat': partner.vat,
            'l10n_do_dgii_tax_payer_type': partner.l10n_do_dgii_tax_payer_type,
            'l10n_do_rnc_validated': partner.l10n_do_rnc_validated,
        }