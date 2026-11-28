# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class NcfType(models.Model):
    _name = 'l10n_do_ncf.type'
    _description = 'Tipo de Comprobante Fiscal NCF'
    _order = 'code'

    name = fields.Char(
        string='Nombre',
        required=True,
        help='Nombre del tipo de comprobante fiscal'
    )
    code = fields.Char(
        string='Codigo',
        required=True,
        size=2,
        help='Codigo de 2 digitos del tipo de NCF (ej: 01, 02, 11)'
    )
    prefix = fields.Char(
        string='Prefijo NCF',
        required=True,
        size=3,
        help='Prefijo del NCF (ej: B01, E31)'
    )
    is_electronic = fields.Boolean(
        string='Es Electronico (e-CF)',
        default=False,
        help='Indica si es un comprobante fiscal electronico'
    )
    requires_rnc = fields.Boolean(
        string='Requiere RNC',
        default=True,
        help='Indica si requiere RNC del cliente'
    )
    for_sale = fields.Boolean(
        string='Para Ventas',
        default=True,
        help='Disponible para facturas de venta'
    )
    for_purchase = fields.Boolean(
        string='Para Compras',
        default=False,
        help='Disponible para facturas de compra'
    )
    aplica_vencimiento = fields.Boolean(
        string='Aplica Vencimiento',
        default=True,
        help='Indica si las secuencias de este tipo de NCF estan sujetas a vencimiento de 2 anos.'
    )
    vigencia_anos = fields.Integer(
        string='Anos de Vigencia',
        default=2,
        help='Cantidad de anos de vigencia para las secuencias (por defecto 2 anos segun Norma 06-2018)'
    )
    active = fields.Boolean(
        string='Activo',
        default=True
    )
    description = fields.Text(
        string='Descripcion',
        help='Descripcion detallada del uso de este tipo de NCF'
    )
    sequence_ids = fields.One2many(
        'l10n_do_ncf.sequence',
        'ncf_type_id',
        string='Secuencias'
    )

    @api.constrains('code')
    def _check_code_unique(self):
        for record in self:
            existing = self.search([
                ('code', '=', record.code),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(_('El codigo del tipo de NCF debe ser unico.'))

    @api.constrains('prefix')
    def _check_prefix_unique(self):
        for record in self:
            existing = self.search([
                ('prefix', '=', record.prefix),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(_('El prefijo del NCF debe ser unico.'))

    def _l10n_do_label(self):
        self.ensure_one()
        return f"[{self.prefix}] {self.name}"

    @api.depends('prefix', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record._l10n_do_label()

    def name_get(self):
        # Odoo 16 toma la etiqueta de name_get (odoo/models.py:1574) y calcula
        # display_name a partir de el (models.py:1558). Se definen los dos
        # sobre la misma funcion para que no puedan divergir.
        return [(record.id, record._l10n_do_label()) for record in self]
