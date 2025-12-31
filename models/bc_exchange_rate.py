# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/bc_exchange_rate.py
# Descripción: Tasa de cambio automática del Banco Central RD
# Versión: 19.0.2.3.0

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta
import requests
import logging
import json

_logger = logging.getLogger(__name__)

# URLs del Banco Central RD
BC_API_URL = 'https://api.bancentral.gov.do/rsavgDollarRate'
BC_FALLBACK_URL = 'https://www.bancentral.gov.do/a/servicios/api'


class L10nDoBCExchangeRate(models.Model):
    """
    Tasa de Cambio del Banco Central RD
    
    Almacena tasas históricas USD/DOP para:
    - Reportes 606/607 (siempre en DOP)
    - IT-1
    - Conversión automática en facturas
    """
    _name = 'l10n_do_ncf.bc.exchange.rate'
    _description = 'Tasa de Cambio BC RD'
    _order = 'date desc'
    _rec_name = 'date'

    date = fields.Date(
        string='Fecha',
        required=True,
        index=True
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        required=True,
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False)
    )

    rate_buy = fields.Float(
        string='Tasa Compra',
        digits=(12, 4),
        required=True
    )

    rate_sell = fields.Float(
        string='Tasa Venta',
        digits=(12, 4),
        required=True
    )

    rate_average = fields.Float(
        string='Tasa Promedio',
        digits=(12, 4),
        compute='_compute_average',
        store=True
    )

    source = fields.Selection([
        ('bc_api', 'API Banco Central'),
        ('bc_web', 'Web Banco Central'),
        ('manual', 'Manual'),
    ], string='Fuente', default='manual')

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company
    )

    _sql_constraints = [
        ('unique_date_currency_company',
         'UNIQUE(date, currency_id, company_id)',
         'Solo puede existir una tasa por fecha, moneda y compañía.')
    ]

    @api.depends('rate_buy', 'rate_sell')
    def _compute_average(self):
        for record in self:
            record.rate_average = (record.rate_buy + record.rate_sell) / 2

    @api.model
    def fetch_bc_rate(self, target_date=None):
        """
        Obtener tasa del Banco Central RD.
        
        Args:
            target_date: Fecha para la tasa (default: hoy)
            
        Returns:
            dict con rate_buy, rate_sell o False si falla
        """
        target_date = target_date or date.today()
        
        # Intentar API oficial primero
        try:
            result = self._fetch_from_bc_api(target_date)
            if result:
                return result
        except Exception as e:
            _logger.warning('Error API BC: %s', str(e))

        # Fallback: scraping web (si está configurado)
        try:
            result = self._fetch_from_bc_web(target_date)
            if result:
                return result
        except Exception as e:
            _logger.warning('Error Web BC: %s', str(e))

        return False

    def _fetch_from_bc_api(self, target_date):
        """
        Llamar API del Banco Central.
        Nota: La API real puede requerir registro/API key.
        """
        # Configuración API
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_ncf.bc_api_key', default=''
        )

        if not api_key:
            _logger.info('API key BC no configurada')
            return False

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % api_key,
        }

        params = {
            'fecha': target_date.strftime('%Y-%m-%d'),
        }

        try:
            response = requests.get(
                BC_API_URL,
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    'rate_buy': float(data.get('compra', 0)),
                    'rate_sell': float(data.get('venta', 0)),
                    'source': 'bc_api',
                }
        except Exception as e:
            _logger.error('Error llamando API BC: %s', str(e))

        return False

    def _fetch_from_bc_web(self, target_date):
        """
        Obtener tasa desde página web BC (fallback).
        Esto es un ejemplo - ajustar según estructura real.
        """
        # Por seguridad, solo usar si está habilitado
        use_web = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_ncf.bc_use_web_scraping', default='False'
        )
        
        if use_web != 'True':
            return False

        # Aquí iría la lógica de scraping
        # Por ahora retornamos False
        return False

    @api.model
    def get_rate_for_date(self, target_date=None, currency=None, create_if_missing=True):
        """
        Obtener tasa para una fecha específica.
        
        Args:
            target_date: Fecha (default: hoy)
            currency: Moneda (default: USD)
            create_if_missing: Si True, intenta obtener de BC
            
        Returns:
            Record de tasa o False
        """
        target_date = target_date or date.today()
        currency = currency or self.env.ref('base.USD', raise_if_not_found=False)

        if not currency:
            return False

        # Buscar existente
        rate = self.search([
            ('date', '=', target_date),
            ('currency_id', '=', currency.id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if rate:
            return rate

        # Intentar obtener de BC
        if create_if_missing:
            bc_data = self.fetch_bc_rate(target_date)
            if bc_data:
                rate = self.create({
                    'date': target_date,
                    'currency_id': currency.id,
                    'rate_buy': bc_data['rate_buy'],
                    'rate_sell': bc_data['rate_sell'],
                    'source': bc_data.get('source', 'bc_api'),
                })
                return rate

        # Buscar tasa más reciente
        rate = self.search([
            ('date', '<=', target_date),
            ('currency_id', '=', currency.id),
            ('company_id', '=', self.env.company.id),
        ], limit=1, order='date desc')

        return rate or False

    @api.model
    def update_daily_rates(self):
        """
        Cron job para actualizar tasas diariamente.
        Configurar en: Configuración → Acciones programadas
        """
        _logger.info('Actualizando tasas BC...')
        
        today = date.today()
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        
        if not usd:
            _logger.warning('Moneda USD no encontrada')
            return

        # Verificar si ya existe
        existing = self.search([
            ('date', '=', today),
            ('currency_id', '=', usd.id),
        ], limit=1)

        if existing:
            _logger.info('Tasa de hoy ya existe: %s', existing.rate_sell)
            return existing

        # Obtener de BC
        bc_data = self.fetch_bc_rate(today)
        
        if bc_data:
            rate = self.create({
                'date': today,
                'currency_id': usd.id,
                'rate_buy': bc_data['rate_buy'],
                'rate_sell': bc_data['rate_sell'],
                'source': bc_data.get('source', 'bc_api'),
            })
            _logger.info('Tasa BC actualizada: Compra=%s, Venta=%s', 
                        rate.rate_buy, rate.rate_sell)
            return rate
        else:
            _logger.warning('No se pudo obtener tasa BC para %s', today)
            return False


class AccountMoveExchangeRate(models.Model):
    """Extensión para auto-llenar tasa en facturas"""
    _inherit = 'account.move'

    @api.onchange('invoice_date', 'currency_id')
    def _onchange_date_currency_rate(self):
        """Auto-llenar tasa BC al cambiar fecha o moneda"""
        if not self.invoice_date or not self.currency_id:
            return

        dop = self.env.ref('base.DOP', raise_if_not_found=False)
        
        # Solo si la factura NO es en DOP
        if dop and self.currency_id.id != dop.id:
            BCRate = self.env['l10n_do_ncf.bc.exchange.rate']
            rate = BCRate.get_rate_for_date(
                self.invoice_date, 
                self.currency_id,
                create_if_missing=False  # No crear en onchange
            )
            
            if rate:
                self.l10n_do_exchange_rate = rate.rate_sell
            else:
                # Buscar tasa más reciente como fallback
                rate = BCRate.search([
                    ('currency_id', '=', self.currency_id.id),
                ], limit=1, order='date desc')
                
                if rate:
                    self.l10n_do_exchange_rate = rate.rate_sell


class ResConfigSettingsBC(models.TransientModel):
    """Configuración de API Banco Central"""
    _inherit = 'res.config.settings'

    l10n_do_bc_api_key = fields.Char(
        string='API Key Banco Central',
        config_parameter='l10n_do_ncf.bc_api_key'
    )

    l10n_do_bc_auto_update = fields.Boolean(
        string='Actualizar tasas automáticamente',
        config_parameter='l10n_do_ncf.bc_auto_update',
        default=True
    )