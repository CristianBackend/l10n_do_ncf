# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/bc_exchange_rate.py
# Descripción: Tasa de Cambio Banco Central RD
# Versión: 19.0.3.0.0 - Corregido para Odoo 19

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, timedelta
import requests
import logging

_logger = logging.getLogger(__name__)


class L10nDoBCExchangeRate(models.Model):
    """
    Tasas de Cambio del Banco Central de República Dominicana
    
    Almacena tasas históricas USD/DOP para:
    - Conversión automática en facturas multimoneda
    - Reportes DGII en DOP
    """
    _name = 'l10n_do_ncf.bc.exchange.rate'
    _description = 'Tasa de Cambio Banco Central RD'
    _order = 'date desc'
    _rec_name = 'date'

    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.today,
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

    # Constraint usando @api.constrains (Odoo 19)
    @api.constrains('date', 'currency_id', 'company_id')
    def _check_unique_date_currency(self):
        for record in self:
            existing = self.search([
                ('id', '!=', record.id),
                ('date', '=', record.date),
                ('currency_id', '=', record.currency_id.id),
                ('company_id', '=', record.company_id.id),
            ])
            if existing:
                raise ValidationError(_(
                    'Ya existe una tasa para %s en fecha %s.'
                ) % (record.currency_id.name, record.date))

    @api.depends('rate_buy', 'rate_sell')
    def _compute_average(self):
        for record in self:
            record.rate_average = (record.rate_buy + record.rate_sell) / 2

    @api.model
    def fetch_bc_rate(self, target_date=None):
        """
        Obtener tasa del Banco Central RD.
        """
        target_date = target_date or date.today()
        
        # Intentar API oficial
        rate = self._fetch_from_bc_api(target_date)
        
        if not rate:
            _logger.warning('No se pudo obtener tasa BC para %s', target_date)
            return None
            
        return rate

    def _fetch_from_bc_api(self, target_date):
        """
        Llamar API del Banco Central.
        Requiere API key configurada.
        """
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_ncf.bc_api_key', ''
        )
        
        if not api_key:
            _logger.info('API Key BC no configurada, usando fallback')
            return self._get_fallback_rate(target_date)

        try:
            url = 'https://api.bancentral.gov.do/rsavgDollarRate'
            headers = {'Authorization': 'Bearer %s' % api_key}
            params = {'date': target_date.strftime('%Y-%m-%d')}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'rate_buy': data.get('buyRate', 0),
                    'rate_sell': data.get('sellRate', 0),
                    'source': 'bc_api',
                }
        except Exception as e:
            _logger.error('Error API BC: %s', str(e))
        
        return None

    def _get_fallback_rate(self, target_date):
        """
        Fallback: buscar tasa más reciente en BD.
        """
        recent = self.search([
            ('date', '<=', target_date),
        ], limit=1, order='date desc')
        
        if recent:
            return {
                'rate_buy': recent.rate_buy,
                'rate_sell': recent.rate_sell,
                'source': 'manual',
            }
        
        # Tasa por defecto si no hay nada
        return {
            'rate_buy': 58.50,
            'rate_sell': 59.50,
            'source': 'manual',
        }

    @api.model
    def get_rate_for_date(self, target_date=None, currency=None, create_if_missing=True):
        """
        Obtener tasa para una fecha específica.
        """
        target_date = target_date or date.today()
        currency = currency or self.env.ref('base.USD', raise_if_not_found=False)
        
        if not currency:
            return 1.0
        
        # Buscar existente
        rate = self.search([
            ('date', '=', target_date),
            ('currency_id', '=', currency.id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        
        if rate:
            return rate.rate_sell
        
        # Crear si no existe
        if create_if_missing:
            rate_data = self.fetch_bc_rate(target_date)
            if rate_data:
                new_rate = self.create({
                    'date': target_date,
                    'currency_id': currency.id,
                    'rate_buy': rate_data['rate_buy'],
                    'rate_sell': rate_data['rate_sell'],
                    'source': rate_data['source'],
                })
                return new_rate.rate_sell
        
        # Fallback a tasa más reciente
        recent = self.search([
            ('currency_id', '=', currency.id),
            ('date', '<', target_date),
        ], limit=1, order='date desc')
        
        return recent.rate_sell if recent else 1.0

    @api.model
    def update_daily_rates(self):
        """
        Cron job para actualizar tasas diariamente.
        """
        today = date.today()
        
        # Verificar si ya existe
        existing = self.search([
            ('date', '=', today),
            ('company_id', '=', self.env.company.id),
        ])
        
        if existing:
            _logger.info('Tasa BC ya existe para %s', today)
            return
        
        rate_data = self.fetch_bc_rate(today)
        
        if rate_data:
            usd = self.env.ref('base.USD', raise_if_not_found=False)
            if usd:
                self.create({
                    'date': today,
                    'currency_id': usd.id,
                    'rate_buy': rate_data['rate_buy'],
                    'rate_sell': rate_data['rate_sell'],
                    'source': rate_data['source'],
                })
                _logger.info('Tasa BC creada: %s | Compra: %s | Venta: %s',
                           today, rate_data['rate_buy'], rate_data['rate_sell'])


class AccountMoveExchangeRate(models.Model):
    """Extensión para auto-llenar tasa BC en facturas"""
    _inherit = 'account.move'

    @api.onchange('invoice_date', 'currency_id')
    def _onchange_date_currency_rate(self):
        """Auto-llenar tasa de cambio desde BC"""
        if not self.invoice_date or not self.currency_id:
            return
        
        dop = self.env.ref('base.DOP', raise_if_not_found=False)
        if not dop or self.currency_id.id == dop.id:
            self.l10n_do_exchange_rate = 1.0
            return
        
        BCRate = self.env['l10n_do_ncf.bc.exchange.rate']
        rate = BCRate.get_rate_for_date(
            self.invoice_date,
            self.currency_id,
            create_if_missing=False
        )
        
        if rate and rate != 1.0:
            self.l10n_do_exchange_rate = rate


class ResConfigSettingsBC(models.TransientModel):
    """Configuración API Banco Central"""
    _inherit = 'res.config.settings'

    l10n_do_bc_api_key = fields.Char(
        string='API Key Banco Central',
        config_parameter='l10n_do_ncf.bc_api_key'
    )

    l10n_do_bc_auto_update = fields.Boolean(
        string='Actualizar Tasas Automáticamente',
        config_parameter='l10n_do_ncf.bc_auto_update',
        default=True
    )