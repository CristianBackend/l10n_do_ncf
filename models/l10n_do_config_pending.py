# -*- coding: utf-8 -*-
"""Configuración fiscal que falta completar a mano (tarjeta del Panel e-CF).

Lo que se deduce sin ambigüedad lo llena l10n_do_autoconfig; aquí se cuenta lo
que queda, por grupo, con la lista filtrada para completarlo. El conector e-CF
añade sus propios grupos (conexión y rangos).
"""
from odoo import _, api, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _l10n_do_pending_taxes_kind(self):
        """Impuestos positivos sin "Clase DGII" que el 606/607 no puede
        clasificar (un 18 % o 16 % sin clase ya se toma como ITBIS)."""
        self.ensure_one()
        Tax = self.env['account.tax']
        return Tax.search([
            *Tax._check_company_domain(self),
            ('type_tax_use', 'in', ('sale', 'purchase')),
            ('amount_type', '=', 'percent'),
            ('amount', '>', 0),
            ('dgii_tax_kind', '=', False),
        ]).filtered(lambda t: t.amount not in (18.0, 16.0))

    def _l10n_do_pending_taxes_zero(self):
        """Impuestos al 0 % sin "Tipo ITBIS 0 %": el e-CF no sabe si son tasa
        cero (indicador 3) o exentos (indicador 4) y bloquea la factura."""
        self.ensure_one()
        Tax = self.env['account.tax']
        return Tax.search([
            *Tax._check_company_domain(self),
            ('type_tax_use', 'in', ('sale', 'purchase')),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 0),
            ('dgii_itbis_zero_type', '=', False),
        ])

    def _l10n_do_pending_journals(self):
        self.ensure_one()
        return self.env['account.journal'].search([
            ('company_id', '=', self.id),
            ('type', 'in', ('bank', 'cash', 'credit')),
            ('l10n_do_payment_form', '=', False),
        ])

    def _l10n_do_pending_accounts(self):
        """Cuentas usadas en facturas de proveedor confirmadas sin "Tipo 606"."""
        self.ensure_one()
        groups = self.env['account.move.line']._read_group([
            ('company_id', '=', self.id),
            ('parent_state', '=', 'posted'),
            ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ('display_type', '=', 'product'),
            ('account_id.l10n_do_606_expense_type', '=', False),
        ], ['account_id'])
        return self.env['account.account'].union(*[account for account, in groups])

    def _l10n_do_config_pending(self):
        """[{key, title, hint, count}] de lo que falta, solo grupos con algo."""
        self.ensure_one()
        groups = [
            ('taxes_kind', _('Impuestos sin clase DGII'),
             _('ITBIS, ISC, propina u otros: la casilla del 606/607 donde va cada uno.'),
             self._l10n_do_pending_taxes_kind()),
            ('taxes_zero', _('Impuestos de 0 % sin indicador'),
             _('Indique si son ITBIS 0 % (tasa cero) o Exento: sin eso el e-CF se bloquea.'),
             self._l10n_do_pending_taxes_zero()),
            ('journals', _('Diarios sin forma de pago DGII'),
             _('Forma de pago con que el 606/607 reporta los pagos de cada diario.'),
             self._l10n_do_pending_journals()),
            ('accounts', _('Cuentas de gasto usadas sin Tipo 606'),
             _('Tipo de bienes y servicios con que se reportan las compras de cada cuenta.'),
             self._l10n_do_pending_accounts()),
        ]
        return [{'key': key, 'title': title, 'hint': hint, 'count': len(records)}
                for key, title, hint, records in groups if records]

    def _l10n_do_config_pending_action(self, key):
        """Lista filtrada para completar un grupo de la tarjeta."""
        self.ensure_one()
        lists = {
            'taxes_kind': ('account.tax', _('Impuestos sin clase DGII'),
                           self._l10n_do_pending_taxes_kind()),
            'taxes_zero': ('account.tax', _('Impuestos de 0 % sin indicador'),
                           self._l10n_do_pending_taxes_zero()),
            'journals': ('account.journal', _('Diarios sin forma de pago DGII'),
                         self._l10n_do_pending_journals()),
            'accounts': ('account.account', _('Cuentas de gasto sin Tipo 606'),
                         self._l10n_do_pending_accounts()),
        }
        if key not in lists:
            return False
        model, name, records = lists[key]
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'domain': [('id', 'in', records.ids)],
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
        }


class NcfDashboard(models.AbstractModel):
    _inherit = 'l10n_do_ncf.dashboard'

    @api.model
    def get_dashboard_data(self):
        data = super().get_dashboard_data()
        if isinstance(data, dict):
            # Siempre se manda la clave: el panel hace Object.assign y, sin
            # ella, una tarjeta ya resuelta seguiría visible tras "Actualizar".
            data['config_pending'] = self.env.company._l10n_do_config_pending()
        return data

    @api.model
    def l10n_do_open_config_pending(self, key):
        """Botón de cada grupo de "Configuración pendiente"."""
        return self.env.company._l10n_do_config_pending_action(key)
