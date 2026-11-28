# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # En Odoo 16 no existe product.template.fiscal_country_codes (lo anade
    # account en 17+), asi que la vista no puede preguntar
    # "'DO' not in (fiscal_country_codes or '')". Este booleano lleva la misma
    # logica con las mismas entradas: el pais fiscal de la compania de la
    # plantilla o, si no tiene, de las companias permitidas. store=False, como
    # el campo de la 19.
    l10n_do_fiscal_country_is_do = fields.Boolean(
        compute='_compute_l10n_do_fiscal_country_is_do',
        string='Pais fiscal dominicano',
        help='Tecnico: muestra el apartado de Republica Dominicana solo cuando '
             'el pais fiscal de la compania es RD.')

    @api.depends_context('company', 'allowed_company_ids')
    def _compute_l10n_do_fiscal_country_is_do(self):
        for record in self:
            companies = record.company_id or self.env.companies
            record.l10n_do_fiscal_country_is_do = 'DO' in companies.mapped(
                'account_fiscal_country_id.code')

    l10n_do_no_exterior_retention = fields.Boolean(
        string='Sin retención en pagos al exterior',
        help='En un pago al exterior (B17/E47) no se sugiere la retención de ISR en las '
             'líneas con este producto; por ejemplo, viáticos de un viaje fuera del país. '
             'Las demás líneas sí la llevan, y la retención se puede poner o quitar a mano '
             'en cualquier línea.')
