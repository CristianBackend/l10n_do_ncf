# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/pos_order.py
# Descripción: Extensión de Punto de Venta con NCF
# Compatibilidad: Odoo 19
# NOTA: Este archivo solo se carga si point_of_sale está instalado

from odoo import models, fields, api, _
from odoo.exceptions import UserError
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

    def _get_ncf_sequence_for_partner(self, partner):
        """Obtener la secuencia NCF correcta según el tipo de cliente"""
        self.ensure_one()
        
        if not partner or not partner.l10n_do_dgii_tax_payer_type:
            return self.l10n_do_ncf_sequence_id
        
        taxpayer_type = partner.l10n_do_dgii_tax_payer_type
        
        if taxpayer_type == 'taxpayer':
            return self.l10n_do_ncf_fiscal_sequence_id or self.l10n_do_ncf_sequence_id
        elif taxpayer_type == 'special_regime':
            return self.l10n_do_ncf_special_sequence_id or self.l10n_do_ncf_sequence_id
        elif taxpayer_type == 'governmental':
            return self.l10n_do_ncf_gov_sequence_id or self.l10n_do_ncf_sequence_id
        else:
            return self.l10n_do_ncf_sequence_id


class PosSession(models.Model):
    """Extensión de sesión POS para cargar datos NCF"""
    _inherit = 'pos.session'

    def _loader_params_res_partner(self):
        """Agregar campos NCF a los parámetros de carga de partners"""
        result = super()._loader_params_res_partner()
        result['search_params']['fields'].extend([
            'l10n_do_dgii_tax_payer_type',
            'l10n_do_rnc_validated',
            'l10n_do_dgii_status',
        ])
        return result


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

    def _generate_ncf(self):
        """Generar NCF para la orden POS"""
        self.ensure_one()
        
        if not self.config_id.l10n_do_ncf_enabled:
            return False
        
        if self.l10n_do_ncf_number:
            return self.l10n_do_ncf_number
        
        ncf_type = self._get_ncf_type_from_partner()
        sequence = self.config_id._get_ncf_sequence_for_partner(self.partner_id)
        
        if not sequence:
            _logger.warning('POS NCF: No hay secuencia NCF configurada para %s', self.config_id.name)
            return False
        
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
        res = super().action_pos_order_paid()
        
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

    def _export_for_ui(self, order):
        """Agregar campos NCF al exportar orden para la UI del POS"""
        result = super()._export_for_ui(order)
        result.update({
            'l10n_do_ncf_number': order.l10n_do_ncf_number,
            'l10n_do_ncf_type': order.l10n_do_ncf_type,
            'l10n_do_partner_vat': order.l10n_do_partner_vat,
        })
        return result