# -*- coding: utf-8 -*-
"""Zona horaria de los usuarios de una compañía dominicana.

Sin zona horaria Odoo usa UTC: de 8 p. m. a medianoche en República
Dominicana (UTC-4) ya es mañana, y una factura nueva toma la fecha contable
y el vencimiento de mañana. Al instalar o actualizar el módulo y al crear un
usuario interno se pone America/Santo_Domingo si no tiene zona; una zona ya
elegida no se toca.
"""
from datetime import datetime

from freezegun import freeze_time

from odoo import fields
from odoo.tests import new_test_user, tagged

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestUserTimezone(NcfCommon):

    def _user(self, login, **vals):
        return new_test_user(self.env, login=login, company_id=self.company.id,
                             company_ids=[(6, 0, self.company.ids)], **vals)

    def test_new_internal_user_gets_dominican_tz(self):
        user = self._user('do_tz_new', tz=False)
        self.assertEqual(user.tz, 'America/Santo_Domingo')

    def test_chosen_tz_is_kept(self):
        user = self._user('do_tz_kept', tz='Europe/Madrid')
        self.assertEqual(user.tz, 'Europe/Madrid')

    def test_portal_user_is_not_touched(self):
        user = self._user('do_tz_portal', tz=False, groups='base.group_portal')
        self.assertFalse(user.tz)

    def test_other_country_company_is_not_touched(self):
        other = self.env['res.company'].create({
            'name': 'Otra (US)', 'country_id': self.env.ref('base.us').id})
        user = new_test_user(self.env, login='us_tz', company_id=other.id,
                             company_ids=[(6, 0, other.ids)], tz=False)
        self.assertFalse(user.tz)

    def test_update_fills_existing_users_without_tz(self):
        user = self._user('do_tz_update')
        kept = self._user('do_tz_update_kept', tz='America/New_York')
        user.tz = False
        l10n_do_autoconfig.autoconfigure(self.env, self.company)
        self.assertEqual(user.tz, 'America/Santo_Domingo')
        self.assertEqual(kept.tz, 'America/New_York')

    def _default_date(self, user):
        """Fecha contable con la que nace una factura nueva de ese usuario."""
        Move = self.env['account.move'].with_user(user).with_context(tz=user.tz)
        return Move.new({'move_type': 'out_invoice'}).date

    def test_new_bill_date_at_2330_utc(self):
        """23:30 UTC del 9 = 7:30 p. m. del 9 en RD: mismo día en las dos."""
        with freeze_time(datetime(2026, 11, 9, 23, 30)):
            user = self._user('do_tz_2330utc', tz=False,
                              groups='base.group_user,account.group_account_invoice')
            self.assertEqual(user.tz, 'America/Santo_Domingo')
            self.assertEqual(fields.Date.to_date(self._default_date(user)),
                             datetime(2026, 11, 9).date())

    def test_new_bill_date_at_2330_rd(self):
        """23:30 del 9 en RD = 03:30 UTC del 10: sin zona, Odoo pondría el 10."""
        with freeze_time(datetime(2026, 11, 10, 3, 30)):
            user = self._user('do_tz_2330rd', tz=False,
                              groups='base.group_user,account.group_account_invoice')
            self.assertEqual(fields.Date.to_date(self._default_date(user)),
                             datetime(2026, 11, 9).date())
            user.tz = False
            self.assertEqual(fields.Date.to_date(self._default_date(user)),
                             datetime(2026, 11, 10).date(), 'El problema sin zona horaria')

    def test_panel_warns_accounting_users_with_other_tz(self):
        """Una zona elegida no se pisa, pero el Panel lo avisa."""
        accounting = 'base.group_user,account.group_account_invoice'
        madrid = self._user('do_tz_madrid', tz='Europe/Madrid', groups=accounting)
        self._user('do_tz_ok', tz='America/Santo_Domingo', groups=accounting)
        self._user('do_tz_sales', tz='Europe/Madrid', groups='base.group_user')
        pending = self.company._l10n_do_pending_user_tz()
        self.assertIn(madrid, pending)
        self.assertFalse(pending.filtered(lambda u: u.login in ('do_tz_ok', 'do_tz_sales')))
        group = next(g for g in self.company._l10n_do_config_pending() if g['key'] == 'user_tz')
        self.assertEqual(group['severity'], 'warning')
        self.assertEqual(group['count'], len(pending))
        action = self.company._l10n_do_config_pending_action('user_tz')
        self.assertEqual(action['res_model'], 'res.users')
        self.assertIn(madrid.id, action['domain'][0][2])
