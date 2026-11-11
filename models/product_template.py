# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    l10n_do_no_exterior_retention = fields.Boolean(
        string='Sin retención en pagos al exterior',
        help='En un pago al exterior (B17/E47) no se sugiere la retención de ISR en las '
             'líneas con este producto; por ejemplo, viáticos de un viaje fuera del país. '
             'Las demás líneas sí la llevan, y la retención se puede poner o quitar a mano '
             'en cualquier línea.')
