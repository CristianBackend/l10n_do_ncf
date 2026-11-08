# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_do_ncf_next_expiration_alert = fields.Integer(
        string='Días Alerta Vencimiento NCF',
        default=30,
        help='Días antes del vencimiento para alertar sobre secuencias NCF'
    )
    
    l10n_do_ncf_low_sequence_alert = fields.Integer(
        string='Alerta Secuencia Baja',
        default=50,
        help='Alertar cuando queden menos de esta cantidad de NCF'
    )
    
    l10n_do_fiscal_journal_id = fields.Many2one(
        'account.journal',
        string='Diario Fiscal por Defecto',
        domain=[('type', '=', 'sale')],
        help='Diario de ventas por defecto para facturas fiscales'
    )
    
    l10n_do_informal_vendor_journal_id = fields.Many2one(
        'account.journal',
        string='Diario Compras Informales',
        domain=[('type', '=', 'purchase')],
        help='Diario para compras a proveedores informales'
    )

    # Retenciones que se agregan solas a las líneas según el "Tipo de compra".
    # Vacías hasta que el contador las confirme (docs/retenciones_tabla.md):
    # la configuración automática no las elige.
    l10n_do_informal_retention_tax_ids = fields.Many2many(
        'account.tax', 'l10n_do_company_informal_ret_tax_rel', 'company_id', 'tax_id',
        string='Retenciones al proveedor informal',
        domain="[('type_tax_use', '=', 'purchase'), ('amount', '<', 0), ('company_id', '=', id)]",
        help='Impuestos de retención que se agregan a las líneas de una compra a un '
             'proveedor informal: los de ITBIS a las líneas con ITBIS y los de ISR a los '
             'servicios. Se pueden quitar en cada línea.')
    l10n_do_exterior_retention_tax_ids = fields.Many2many(
        'account.tax', 'l10n_do_company_exterior_ret_tax_rel', 'company_id', 'tax_id',
        string='Retenciones del pago al exterior',
        domain="[('type_tax_use', '=', 'purchase'), ('amount', '<', 0), ('company_id', '=', id)]",
        help='Impuestos de retención que se agregan a las líneas de un pago al exterior. '
             'Por defecto el ISR del 27 % (DGII, Guía del Contribuyente No. 5, pág. 5; '
             'arts. 297 y 305 del Código Tributario). Se puede cambiar en cada línea: un '
             'convenio de doble tributación puede fijar otra tasa.')

    l10n_do_minor_expense_partner_id = fields.Many2one(
        'res.partner', string='Contacto "Gastos menores"',
        help='Contacto genérico (sin RNC) de las facturas de gastos menores: peajes, '
             'parqueos y gastos sin comprobante. Una factura de proveedor a este '
             'contacto nace como "Gastos menores" (e-CF E43, o B13 en papel).')

    def _l10n_do_minor_expense_partner(self):
        """El contacto "Gastos menores" de la compañía; lo crea si falta."""
        self.ensure_one()
        partner = self.sudo().l10n_do_minor_expense_partner_id
        if partner:
            return partner
        partner = self.env['res.partner'].sudo().with_context(
            l10n_do_skip_auto_type=True).create({
                'name': _('Gastos menores'),
                'company_id': self.id,
                'country_id': self.env.ref('base.do').id,
                'is_company': False,
                'l10n_do_dgii_tax_payer_type': 'final_consumer',
                'comment': _('Contacto genérico para las facturas de gastos menores '
                             '(peajes, parqueos y gastos sin comprobante). Sin RNC.'),
            })
        self.sudo().l10n_do_minor_expense_partner_id = partner
        return partner

    def _l10n_do_purchase_exempt_tax(self):
        """Impuesto de compras "ITBIS Exento" de la compañía (o vacío)."""
        self.ensure_one()
        Tax = self.env['account.tax']
        taxes = Tax.search([
            *Tax._check_company_domain(self),
            ('type_tax_use', '=', 'purchase'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 0),
            ('dgii_itbis_zero_type', '=', 'exempt'),
        ])
        template = self.env.ref('account.%s_tax_0_purch' % self.id, raise_if_not_found=False)
        if template and template in taxes:
            return template
        return taxes[:1]


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_do_ncf_next_expiration_alert = fields.Integer(
        related='company_id.l10n_do_ncf_next_expiration_alert',
        readonly=False
    )
    
    l10n_do_ncf_low_sequence_alert = fields.Integer(
        related='company_id.l10n_do_ncf_low_sequence_alert',
        readonly=False
    )
    
    l10n_do_fiscal_journal_id = fields.Many2one(
        related='company_id.l10n_do_fiscal_journal_id',
        readonly=False
    )
    
    l10n_do_informal_vendor_journal_id = fields.Many2one(
        related='company_id.l10n_do_informal_vendor_journal_id',
        readonly=False
    )
    l10n_do_informal_retention_tax_ids = fields.Many2many(
        related='company_id.l10n_do_informal_retention_tax_ids', readonly=False)
    l10n_do_exterior_retention_tax_ids = fields.Many2many(
        related='company_id.l10n_do_exterior_retention_tax_ids', readonly=False)
