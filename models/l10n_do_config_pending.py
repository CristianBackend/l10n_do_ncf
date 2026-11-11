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

    def _l10n_do_pending_retentions(self):
        """Facturas de proveedor confirmadas cuyas retenciones no cuadran con
        el asiento: en la pestaña y no en el asiento, distintas, o en un
        impuesto sin tipo DGII. Las ajusta el contador a mano."""
        self.ensure_one()
        return self.env['account.move'].search([
            ('company_id', '=', self.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '=', 'posted'),
            ('l10n_do_retention_check', '!=', False),
        ])

    def _l10n_do_pending_user_tz(self):
        """Usuarios contables de la compañía con otra zona horaria que la de RD.

        Odoo toma "hoy" de la zona del usuario: con una zona adelantada a RD (o
        sin zona, UTC) la factura nueva puede nacer con fecha de mañana. Una zona
        elegida no se cambia sola (res_users.py): se avisa aquí."""
        self.ensure_one()
        from .l10n_do_autoconfig import is_dominican
        from .res_users import DO_TZ
        if not is_dominican(self):
            return self.env['res.users']
        group = self.env.ref('account.group_account_invoice', raise_if_not_found=False)
        if not group:
            return self.env['res.users']
        return self.env['res.users'].sudo().search([
            ('share', '=', False),
            ('company_ids', 'in', self.id),
            ('all_group_ids', 'in', group.id),
            '|', ('tz', '=', False), ('tz', '!=', DO_TZ),
        ])

    def _l10n_do_config_pending(self):
        """Lo que falta, solo los grupos con algo:
        [{key, severity, count, text}].

        severity: 'danger' si BLOQUEA la emisión del e-CF, 'warning' si solo
        afecta los reportes DGII (606/607). El texto va con el número delante.
        """
        self.ensure_one()

        def text(count, one, many):
            return (one if count == 1 else many) % count

        zero = len(self._l10n_do_pending_taxes_zero())
        kind = len(self._l10n_do_pending_taxes_kind())
        journals = len(self._l10n_do_pending_journals())
        accounts = len(self._l10n_do_pending_accounts())
        retentions = len(self._l10n_do_pending_retentions())
        user_tz = len(self._l10n_do_pending_user_tz())
        groups = [
            ('taxes_zero', 'danger', zero, text(
                zero,
                _('%s impuesto de 0 %% no indica si es Exento o tasa cero. '
                  'Sin eso no se puede emitir el e-CF.'),
                _('%s impuestos de 0 %% no indican si son Exentos o tasa cero. '
                  'Sin eso no se puede emitir el e-CF.'))),
            ('taxes_kind', 'warning', kind, text(
                kind,
                _('%s impuesto sin clasificar para el 606 y el 607.'),
                _('%s impuestos sin clasificar para el 606 y el 607.'))),
            ('journals', 'warning', journals, text(
                journals,
                _('%s diario sin forma de pago para el 606 y el 607.'),
                _('%s diarios sin forma de pago para el 606 y el 607.'))),
            ('accounts', 'warning', accounts, text(
                accounts,
                _('%s cuenta de gasto sin tipo de bienes y servicios para el 606.'),
                _('%s cuentas de gasto sin tipo de bienes y servicios para el 606.'))),
            ('retentions', 'warning', retentions, text(
                retentions,
                _('%s factura de proveedor con retenciones sin asiento o que no coinciden: '
                  'el contador debe ajustarla.'),
                _('%s facturas de proveedor con retenciones sin asiento o que no coinciden: '
                  'el contador debe ajustarlas.'))),
            ('user_tz', 'warning', user_tz, text(
                user_tz,
                _('%s usuario contable con una zona horaria distinta de la de República '
                  'Dominicana (America/Santo_Domingo): sus facturas pueden salir con la fecha '
                  'de otro día.'),
                _('%s usuarios contables con una zona horaria distinta de la de República '
                  'Dominicana (America/Santo_Domingo): sus facturas pueden salir con la fecha '
                  'de otro día.'))),
        ]
        return [{'key': key, 'severity': severity, 'count': count, 'text': message}
                for key, severity, count, message in groups if count]

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
            'user_tz': ('res.users', _('Usuarios con otra zona horaria'),
                        self._l10n_do_pending_user_tz()),
        }
        if key == 'retentions':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Retenciones sin asiento / que no coinciden'),
                'res_model': 'account.move',
                'domain': [('id', 'in', self._l10n_do_pending_retentions().ids)],
                'views': [[self.env.ref('l10n_do_ncf.view_move_tree_retention_check').id, 'list'],
                          [False, 'form']],
                'context': {'create': False},
                'target': 'current',
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
