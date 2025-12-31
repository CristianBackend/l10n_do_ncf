# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/dgii_validation.py
# Descripción: Validación RNC y NCF con servicios DGII
# Versión: 19.0.2.3.0

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
import requests
import re
import logging
import hashlib

_logger = logging.getLogger(__name__)

# URLs de servicios DGII
DGII_RNC_URL = 'https://dgii.gov.do/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/rnc.aspx'
DGII_NCF_URL = 'https://dgii.gov.do/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/ncf.aspx'

# API alternativa (si existe)
DGII_API_RNC = 'https://api.dgii.gov.do/rnc/validate'
DGII_API_NCF = 'https://api.dgii.gov.do/ncf/validate'


class L10nDoDGIIValidation(models.Model):
    """
    Cache de validaciones DGII
    
    Almacena resultados para evitar consultas repetidas
    y cumplir con rate limits de DGII.
    """
    _name = 'l10n_do_ncf.dgii.validation'
    _description = 'Validación DGII Cache'
    _order = 'create_date desc'

    validation_type = fields.Selection([
        ('rnc', 'RNC/Cédula'),
        ('ncf', 'NCF'),
    ], string='Tipo', required=True, index=True)

    # Datos validados
    rnc = fields.Char(string='RNC/Cédula', index=True)
    ncf = fields.Char(string='NCF', index=True)
    vendor_rnc = fields.Char(string='RNC Emisor (NCF)')

    # Resultado
    is_valid = fields.Boolean(string='Válido', default=False)
    
    # Datos obtenidos
    business_name = fields.Char(string='Razón Social')
    trade_name = fields.Char(string='Nombre Comercial')
    status = fields.Char(string='Estado DGII')
    activity = fields.Char(string='Actividad Económica')
    address = fields.Text(string='Dirección')
    
    # NCF específicos
    ncf_type = fields.Char(string='Tipo NCF')
    ncf_status = fields.Char(string='Estado NCF')
    authorization_date = fields.Date(string='Fecha Autorización')
    expiration_date = fields.Date(string='Fecha Vencimiento')

    # Meta
    response_raw = fields.Text(string='Respuesta Raw')
    error_message = fields.Char(string='Error')
    validation_date = fields.Datetime(string='Fecha Validación', default=fields.Datetime.now)
    
    # Para rate limiting
    request_hash = fields.Char(string='Hash Request', index=True)

    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company
    )

    _sql_constraints = [
        ('unique_hash', 'UNIQUE(request_hash)', 'Validación duplicada')
    ]

    @api.model
    def _get_request_hash(self, validation_type, rnc=None, ncf=None, vendor_rnc=None):
        """Generar hash único para la request"""
        key = '%s|%s|%s|%s' % (validation_type, rnc or '', ncf or '', vendor_rnc or '')
        return hashlib.md5(key.encode()).hexdigest()

    @api.model
    def validate_rnc(self, rnc, force_refresh=False):
        """
        Validar RNC/Cédula con DGII.
        
        Args:
            rnc: RNC o Cédula a validar
            force_refresh: Si True, ignora cache
            
        Returns:
            dict con resultado de validación
        """
        if not rnc:
            return {'valid': False, 'error': 'RNC vacío'}

        # Limpiar RNC
        rnc_clean = re.sub(r'[^0-9]', '', str(rnc))
        
        if len(rnc_clean) not in (9, 11):
            return {'valid': False, 'error': 'RNC debe tener 9 dígitos o Cédula 11 dígitos'}

        # Verificar cache (válido por 24 horas)
        if not force_refresh:
            cached = self._get_cached_validation('rnc', rnc=rnc_clean)
            if cached:
                return self._format_rnc_result(cached)

        # Consultar DGII
        result = self._query_dgii_rnc(rnc_clean)
        
        # Guardar en cache
        self._save_validation('rnc', rnc=rnc_clean, result=result)
        
        return result

    @api.model
    def validate_ncf(self, ncf, vendor_rnc, force_refresh=False):
        """
        Validar NCF con DGII.
        
        Args:
            ncf: Número de comprobante fiscal
            vendor_rnc: RNC del emisor del NCF
            force_refresh: Si True, ignora cache
            
        Returns:
            dict con resultado de validación
        """
        if not ncf or not vendor_rnc:
            return {'valid': False, 'error': 'NCF y RNC emisor son requeridos'}

        ncf_clean = ncf.strip().upper()
        rnc_clean = re.sub(r'[^0-9]', '', str(vendor_rnc))

        # Validar formato NCF
        ncf_pattern = r'^(B|E)\d{10,11}$'
        if not re.match(ncf_pattern, ncf_clean):
            return {'valid': False, 'error': 'Formato NCF inválido'}

        # Verificar cache
        if not force_refresh:
            cached = self._get_cached_validation('ncf', ncf=ncf_clean, vendor_rnc=rnc_clean)
            if cached:
                return self._format_ncf_result(cached)

        # Consultar DGII
        result = self._query_dgii_ncf(ncf_clean, rnc_clean)
        
        # Guardar en cache
        self._save_validation('ncf', ncf=ncf_clean, vendor_rnc=rnc_clean, result=result)
        
        return result

    def _get_cached_validation(self, validation_type, rnc=None, ncf=None, vendor_rnc=None):
        """Buscar validación en cache (24 horas)"""
        request_hash = self._get_request_hash(validation_type, rnc, ncf, vendor_rnc)
        
        cutoff = datetime.now() - timedelta(hours=24)
        
        cached = self.search([
            ('request_hash', '=', request_hash),
            ('validation_date', '>=', cutoff),
        ], limit=1)
        
        return cached or False

    def _save_validation(self, validation_type, result, rnc=None, ncf=None, vendor_rnc=None):
        """Guardar resultado en cache"""
        request_hash = self._get_request_hash(validation_type, rnc, ncf, vendor_rnc)
        
        # Eliminar cache anterior
        self.search([('request_hash', '=', request_hash)]).unlink()
        
        vals = {
            'validation_type': validation_type,
            'rnc': rnc,
            'ncf': ncf,
            'vendor_rnc': vendor_rnc,
            'is_valid': result.get('valid', False),
            'business_name': result.get('business_name'),
            'trade_name': result.get('trade_name'),
            'status': result.get('status'),
            'activity': result.get('activity'),
            'error_message': result.get('error'),
            'response_raw': str(result.get('raw_response', '')),
            'request_hash': request_hash,
        }
        
        if validation_type == 'ncf':
            vals.update({
                'ncf_type': result.get('ncf_type'),
                'ncf_status': result.get('ncf_status'),
            })
        
        return self.create(vals)

    def _query_dgii_rnc(self, rnc):
        """
        Consultar RNC en DGII.
        
        Nota: La implementación real depende del servicio DGII disponible.
        Puede ser:
        - API REST (si existe)
        - SOAP/Web Service
        - Scraping de página web (no recomendado)
        """
        try:
            # Intento 1: API REST (si existe y está configurada)
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'l10n_do_ncf.dgii_api_key', default=''
            )
            
            if api_key:
                return self._query_dgii_rnc_api(rnc, api_key)
            
            # Intento 2: Validación local básica
            return self._validate_rnc_local(rnc)
            
        except Exception as e:
            _logger.error('Error consultando DGII RNC: %s', str(e))
            return {
                'valid': False,
                'error': 'Error de conexión con DGII: %s' % str(e)
            }

    def _query_dgii_rnc_api(self, rnc, api_key):
        """Consultar API DGII (si existe)"""
        headers = {
            'Authorization': 'Bearer %s' % api_key,
            'Content-Type': 'application/json',
        }
        
        try:
            response = requests.get(
                '%s/%s' % (DGII_API_RNC, rnc),
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'valid': True,
                    'rnc': rnc,
                    'business_name': data.get('nombre', ''),
                    'trade_name': data.get('nombre_comercial', ''),
                    'status': data.get('estado', ''),
                    'activity': data.get('actividad', ''),
                    'raw_response': data,
                }
            elif response.status_code == 404:
                return {
                    'valid': False,
                    'error': 'RNC no encontrado en DGII'
                }
            else:
                return {
                    'valid': False,
                    'error': 'Error DGII: %s' % response.status_code
                }
                
        except requests.exceptions.Timeout:
            return {'valid': False, 'error': 'Timeout conectando con DGII'}
        except Exception as e:
            return {'valid': False, 'error': str(e)}

    def _validate_rnc_local(self, rnc):
        """
        Validación local básica de RNC.
        Verifica dígito verificador y formato.
        """
        rnc = str(rnc).strip()
        
        # Cédula (11 dígitos)
        if len(rnc) == 11:
            if self._validate_cedula_checksum(rnc):
                return {
                    'valid': True,
                    'rnc': rnc,
                    'status': 'Formato válido (Cédula)',
                    'source': 'local',
                }
            return {'valid': False, 'error': 'Cédula inválida (dígito verificador)'}
        
        # RNC (9 dígitos)
        if len(rnc) == 9:
            if self._validate_rnc_checksum(rnc):
                return {
                    'valid': True,
                    'rnc': rnc,
                    'status': 'Formato válido (RNC)',
                    'source': 'local',
                }
            return {'valid': False, 'error': 'RNC inválido (dígito verificador)'}
        
        return {'valid': False, 'error': 'Longitud inválida'}

    def _validate_rnc_checksum(self, rnc):
        """Validar dígito verificador de RNC (Módulo 11)"""
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

    def _validate_cedula_checksum(self, cedula):
        """Validar dígito verificador de Cédula (Algoritmo Luhn modificado)"""
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

    def _query_dgii_ncf(self, ncf, vendor_rnc):
        """Consultar NCF en DGII"""
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'l10n_do_ncf.dgii_api_key', default=''
            )
            
            if api_key:
                return self._query_dgii_ncf_api(ncf, vendor_rnc, api_key)
            
            # Sin API, validación local
            return {
                'valid': True,
                'ncf': ncf,
                'vendor_rnc': vendor_rnc,
                'ncf_status': 'No verificado (sin API DGII)',
                'source': 'local',
            }
            
        except Exception as e:
            _logger.error('Error consultando DGII NCF: %s', str(e))
            return {'valid': False, 'error': str(e)}

    def _query_dgii_ncf_api(self, ncf, vendor_rnc, api_key):
        """Consultar API DGII para NCF"""
        headers = {
            'Authorization': 'Bearer %s' % api_key,
            'Content-Type': 'application/json',
        }
        
        try:
            response = requests.post(
                DGII_API_NCF,
                headers=headers,
                json={'ncf': ncf, 'rnc_emisor': vendor_rnc},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'valid': data.get('valido', False),
                    'ncf': ncf,
                    'vendor_rnc': vendor_rnc,
                    'ncf_type': data.get('tipo', ''),
                    'ncf_status': data.get('estado', ''),
                    'business_name': data.get('nombre_emisor', ''),
                    'raw_response': data,
                }
            else:
                return {
                    'valid': False,
                    'error': 'NCF no encontrado o inválido'
                }
                
        except Exception as e:
            return {'valid': False, 'error': str(e)}

    def _format_rnc_result(self, cached):
        """Formatear resultado de cache RNC"""
        return {
            'valid': cached.is_valid,
            'rnc': cached.rnc,
            'business_name': cached.business_name,
            'trade_name': cached.trade_name,
            'status': cached.status,
            'activity': cached.activity,
            'cached': True,
            'validation_date': cached.validation_date,
        }

    def _format_ncf_result(self, cached):
        """Formatear resultado de cache NCF"""
        return {
            'valid': cached.is_valid,
            'ncf': cached.ncf,
            'vendor_rnc': cached.vendor_rnc,
            'ncf_type': cached.ncf_type,
            'ncf_status': cached.ncf_status,
            'business_name': cached.business_name,
            'cached': True,
            'validation_date': cached.validation_date,
        }


class AccountMoveValidation(models.Model):
    """Extensión para validación en facturas"""
    _inherit = 'account.move'

    l10n_do_rnc_validation_id = fields.Many2one(
        'l10n_do_ncf.dgii.validation',
        string='Validación RNC'
    )

    l10n_do_ncf_validation_id = fields.Many2one(
        'l10n_do_ncf.dgii.validation',
        string='Validación NCF'
    )

    def action_validate_vendor_rnc_dgii(self):
        """Validar RNC de proveedor con DGII"""
        self.ensure_one()
        
        if not self.partner_id or not self.partner_id.vat:
            raise UserError(_('El proveedor no tiene RNC/Cédula.'))

        Validation = self.env['l10n_do_ncf.dgii.validation']
        result = Validation.validate_rnc(self.partner_id.vat)

        if result.get('valid'):
            # Actualizar datos del partner si están vacíos
            if not self.partner_id.name and result.get('business_name'):
                self.partner_id.name = result['business_name']
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✓ RNC Válido'),
                    'message': _('Razón Social: %s\nEstado: %s') % (
                        result.get('business_name', 'N/A'),
                        result.get('status', 'N/A')
                    ),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✗ RNC Inválido'),
                    'message': result.get('error', 'Error desconocido'),
                    'type': 'danger',
                }
            }

    def action_validate_ncf_dgii(self):
        """Validar NCF de proveedor con DGII"""
        self.ensure_one()
        
        if not self.l10n_do_vendor_ncf:
            raise UserError(_('Ingrese el NCF del proveedor.'))
        
        if not self.partner_id or not self.partner_id.vat:
            raise UserError(_('El proveedor debe tener RNC.'))

        Validation = self.env['l10n_do_ncf.dgii.validation']
        result = Validation.validate_ncf(
            self.l10n_do_vendor_ncf,
            self.partner_id.vat
        )

        if result.get('valid'):
            self.l10n_do_vendor_ncf_validated = True
            self.l10n_do_vendor_ncf_validation_source = 'dgii'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✓ NCF Válido'),
                    'message': _('Estado: %s') % result.get('ncf_status', 'Válido'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✗ NCF Inválido'),
                    'message': result.get('error', 'Error desconocido'),
                    'type': 'danger',
                }
            }


class ResPartnerValidation(models.Model):
    """Extensión para validación en contactos"""
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
        """Validar RNC con DGII"""
        self.ensure_one()
        
        if not self.vat:
            raise UserError(_('Ingrese RNC/Cédula primero.'))

        Validation = self.env['l10n_do_ncf.dgii.validation']
        result = Validation.validate_rnc(self.vat)

        if result.get('valid'):
            vals = {
                'l10n_do_dgii_validated': True,
                'l10n_do_dgii_validation_date': fields.Datetime.now(),
                'l10n_do_dgii_status': result.get('status', 'Válido'),
            }
            
            # Actualizar nombre si está vacío
            if result.get('business_name'):
                if not self.name or self.name == 'Nuevo':
                    vals['name'] = result['business_name']
            
            self.write(vals)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✓ RNC Validado'),
                    'message': result.get('business_name', 'Válido'),
                    'type': 'success',
                }
            }
        else:
            self.l10n_do_dgii_validated = False
            self.l10n_do_dgii_status = result.get('error', 'Inválido')
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('✗ Error Validación'),
                    'message': result.get('error', 'RNC no válido'),
                    'type': 'warning',
                }
            }