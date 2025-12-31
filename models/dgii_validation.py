# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/dgii_validation.py
# Descripción: Validación RNC/NCF contra DGII
# Versión: 19.0.3.0.0 - Corregido para Odoo 19

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
import hashlib
import re
import logging

_logger = logging.getLogger(__name__)


class L10nDoDGIIValidation(models.Model):
    """
    Cache de validaciones DGII
    """
    _name = 'l10n_do_ncf.dgii.validation'
    _description = 'Cache Validación DGII'
    _order = 'validation_date desc'

    validation_type = fields.Selection([
        ('rnc', 'RNC/Cédula'),
        ('ncf', 'NCF'),
    ], string='Tipo Validación', required=True)

    rnc = fields.Char(string='RNC/Cédula', index=True)
    ncf = fields.Char(string='NCF')
    vendor_rnc = fields.Char(string='RNC Emisor')

    is_valid = fields.Boolean(string='Válido', default=False)
    
    business_name = fields.Char(string='Razón Social')
    trade_name = fields.Char(string='Nombre Comercial')
    status = fields.Char(string='Estado')
    activity = fields.Char(string='Actividad Económica')
    
    ncf_type = fields.Char(string='Tipo NCF')
    ncf_status = fields.Char(string='Estado NCF')
    authorization_date = fields.Date(string='Fecha Autorización')
    expiration_date = fields.Date(string='Fecha Vencimiento')
    
    response_raw = fields.Text(string='Respuesta Raw')
    error_message = fields.Char(string='Error')
    validation_date = fields.Datetime(string='Fecha Validación', default=fields.Datetime.now)
    
    move_id = fields.Many2one('account.move', string='Documento')
    registro_unico_id = fields.Many2one('l10n_do_ncf.registro.unico', string='Registro Único')

    request_hash = fields.Char(string='Hash Request', index=True)

    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company
    )

    @api.model
    def _get_request_hash(self, validation_type, rnc=None, ncf=None, vendor_rnc=None):
        """Generar hash único para la request"""
        key = '%s|%s|%s|%s' % (validation_type, rnc or '', ncf or '', vendor_rnc or '')
        return hashlib.md5(key.encode()).hexdigest()

    @api.model
    def validate_rnc(self, rnc, force_refresh=False):
        """Validar RNC/Cédula"""
        if not rnc:
            return {'valid': False, 'error': 'RNC vacío'}

        rnc = re.sub(r'[^0-9]', '', str(rnc))

        if not force_refresh:
            cache = self._get_cached_validation('rnc', rnc=rnc)
            if cache:
                return cache

        local_valid = self._validate_rnc_local(rnc)
        self._save_validation('rnc', rnc=rnc, result=local_valid)
        return local_valid

    def _validate_rnc_local(self, rnc):
        """Validación offline de RNC/Cédula"""
        rnc = re.sub(r'[^0-9]', '', str(rnc))

        if len(rnc) == 9:
            valid = self._validate_rnc_checksum(rnc)
            return {
                'valid': valid,
                'rnc': rnc,
                'type': 'RNC',
                'source': 'local',
                'error': None if valid else 'Dígito verificador inválido'
            }
        elif len(rnc) == 11:
            valid = self._validate_cedula_checksum(rnc)
            return {
                'valid': valid,
                'rnc': rnc,
                'type': 'Cédula',
                'source': 'local',
                'error': None if valid else 'Dígito verificador inválido'
            }
        else:
            return {
                'valid': False,
                'rnc': rnc,
                'error': 'Longitud inválida (debe ser 9 o 11 dígitos)'
            }

    def _validate_rnc_checksum(self, rnc):
        """Validar RNC con Módulo 11"""
        if len(rnc) != 9:
            return False
        try:
            weights = [7, 9, 8, 6, 5, 4, 3, 2]
            total = sum(int(rnc[i]) * weights[i] for i in range(8))
            remainder = total % 11
            if remainder == 0:
                check_digit = 2
            elif remainder == 1:
                check_digit = 1
            else:
                check_digit = 11 - remainder
            return int(rnc[8]) == check_digit
        except:
            return False

    def _validate_cedula_checksum(self, cedula):
        """Validar Cédula con Luhn modificado"""
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

    @api.model
    def validate_ncf(self, ncf, vendor_rnc, force_refresh=False):
        """Validar NCF de proveedor"""
        if not ncf or not vendor_rnc:
            return {'valid': False, 'error': 'NCF o RNC vacío'}

        ncf = ncf.strip().upper()
        vendor_rnc = re.sub(r'[^0-9]', '', str(vendor_rnc))

        if not force_refresh:
            cache = self._get_cached_validation('ncf', ncf=ncf, vendor_rnc=vendor_rnc)
            if cache:
                return cache

        pattern = r'^(B|E)\d{2}\d{8,10}$'
        if not re.match(pattern, ncf):
            result = {'valid': False, 'ncf': ncf, 'error': 'Formato NCF inválido'}
            self._save_validation('ncf', ncf=ncf, vendor_rnc=vendor_rnc, result=result)
            return result

        result = {
            'valid': True,
            'ncf': ncf,
            'vendor_rnc': vendor_rnc,
            'source': 'local',
        }
        self._save_validation('ncf', ncf=ncf, vendor_rnc=vendor_rnc, result=result)
        return result

    def _get_cached_validation(self, validation_type, rnc=None, ncf=None, vendor_rnc=None):
        """Buscar validación en cache (24h)"""
        request_hash = self._get_request_hash(validation_type, rnc, ncf, vendor_rnc)
        cutoff = datetime.now() - timedelta(hours=24)
        
        cached = self.search([
            ('request_hash', '=', request_hash),
            ('validation_date', '>=', cutoff),
        ], limit=1)
        
        if cached:
            return {
                'valid': cached.is_valid,
                'rnc': cached.rnc,
                'ncf': cached.ncf,
                'business_name': cached.business_name,
                'status': cached.status,
                'source': 'cache',
            }
        return None

    def _save_validation(self, validation_type, rnc=None, ncf=None, vendor_rnc=None, result=None):
        """Guardar resultado en cache"""
        request_hash = self._get_request_hash(validation_type, rnc, ncf, vendor_rnc)
        
        existing = self.search([('request_hash', '=', request_hash)], limit=1)
        
        vals = {
            'validation_type': validation_type,
            'rnc': rnc,
            'ncf': ncf,
            'vendor_rnc': vendor_rnc,
            'is_valid': result.get('valid', False),
            'business_name': result.get('business_name', ''),
            'status': result.get('status', ''),
            'error_message': result.get('error', ''),
            'request_hash': request_hash,
            'validation_date': datetime.now(),
        }
        
        if existing:
            existing.write(vals)
        else:
            self.create(vals)


class AccountMoveValidation(models.Model):
    """Extensión para validación DGII en facturas"""
    _inherit = 'account.move'

    def action_validate_vendor_rnc_dgii(self):
        """Validar RNC proveedor contra DGII"""
        self.ensure_one()
        
        if not self.partner_id or not self.partner_id.vat:
            raise UserError(_('El proveedor no tiene RNC/Cédula.'))
        
        Validator = self.env['l10n_do_ncf.dgii.validation']
        result = Validator.validate_rnc(self.partner_id.vat)
        
        if result.get('valid'):
            if result.get('business_name'):
                self.partner_id.write({
                    'l10n_do_dgii_validated': True,
                    'l10n_do_dgii_status': result.get('status', ''),
                })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✓ RNC Válido'),
                    'message': result.get('business_name', self.partner_id.vat),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✗ RNC Inválido'),
                    'message': result.get('error', 'Error de validación'),
                    'type': 'danger',
                }
            }

    def action_validate_ncf_dgii(self):
        """Validar NCF proveedor contra DGII"""
        self.ensure_one()
        
        if not self.l10n_do_vendor_ncf:
            raise UserError(_('Ingrese el NCF del proveedor.'))
        
        if not self.partner_id or not self.partner_id.vat:
            raise UserError(_('El proveedor no tiene RNC.'))
        
        Validator = self.env['l10n_do_ncf.dgii.validation']
        result = Validator.validate_ncf(self.l10n_do_vendor_ncf, self.partner_id.vat)
        
        if result.get('valid'):
            self.l10n_do_vendor_ncf_validated = True
            self.l10n_do_vendor_ncf_validation_source = 'dgii'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✓ NCF Válido'),
                    'message': self.l10n_do_vendor_ncf,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✗ NCF Inválido'),
                    'message': result.get('error', 'Error de validación'),
                    'type': 'danger',
                }
            }


class ResPartnerValidation(models.Model):
    """Extensión para validación DGII en contactos"""
    _inherit = 'res.partner'

    l10n_do_dgii_validated = fields.Boolean(
        string='Validado DGII',
        default=False
    )
    
    l10n_do_dgii_validation_date = fields.Datetime(
        string='Fecha Validación DGII'
    )
    
    l10n_do_dgii_status = fields.Char(
        string='Estado DGII'
    )

    def action_validate_dgii(self):
        """Validar RNC/Cédula contra DGII"""
        self.ensure_one()
        
        if not self.vat:
            raise UserError(_('Ingrese RNC o Cédula.'))
        
        Validator = self.env['l10n_do_ncf.dgii.validation']
        result = Validator.validate_rnc(self.vat)
        
        if result.get('valid'):
            vals = {
                'l10n_do_dgii_validated': True,
                'l10n_do_dgii_validation_date': datetime.now(),
                'l10n_do_dgii_status': result.get('status', 'Activo'),
            }
            
            if result.get('business_name') and not self.name:
                vals['name'] = result['business_name']
            
            self.write(vals)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✓ RNC Válido'),
                    'message': result.get('business_name', self.vat),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✗ RNC Inválido'),
                    'message': result.get('error', 'Error'),
                    'type': 'danger',
                }
            }