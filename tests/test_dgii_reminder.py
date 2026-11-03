# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import TransactionCase, tagged

SUBJECT = 'Recordatorio: Enviar Reportes DGII'


@tagged('post_install', '-at_install')
class TestDgiiReminder(TransactionCase):
    """Cron del recordatorio mensual DGII (send_monthly_reminder)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Empresa Recordatorio DGII',
            'vat': '131793916',
        })
        cls.other_company = cls.env['res.company'].create({
            'name': 'Otra Empresa DGII',
            'vat': '101010101',
        })
        cls.accountant = cls._user('dgii_contador', 'account.group_account_manager')
        cls.admin = cls._user('dgii_admin', 'base.group_system')
        cls.billing = cls._user('dgii_facturacion', 'account.group_account_invoice')

    @classmethod
    def _user(cls, login, group_xmlid, companies=None):
        companies = companies or cls.company
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'company_id': companies[0].id,
            'company_ids': [Command.set(companies.ids)],
            'group_ids': [Command.set([cls.env.ref(group_xmlid).id])],
        })

    def _reminders(self, user):
        return self.env['mail.message'].search([
            ('model', '=', 'res.partner'),
            ('res_id', '=', user.partner_id.id),
            ('subject', 'like', SUBJECT),
        ])

    def test_reminder_reaches_accountant_and_admin_only(self):
        self.env['l10n_do_ncf.dgii.reminder'].send_monthly_reminder()

        self.assertEqual(len(self._reminders(self.accountant)), 1)
        self.assertEqual(len(self._reminders(self.admin)), 1)
        self.assertFalse(self._reminders(self.billing))

    def test_reminder_body_is_html(self):
        self.env['l10n_do_ncf.dgii.reminder'].send_monthly_reminder()
        body = str(self._reminders(self.accountant).body)
        # El HTML se guarda como tal, no escapado como texto.
        self.assertIn('<strong>606</strong>', body)
        self.assertNotIn('&lt;', body)

    def test_multi_company_user_gets_one_reminder(self):
        both = self.company | self.other_company
        user = self._user('dgii_contador_multi', 'account.group_account_manager', both)

        self.env['l10n_do_ncf.dgii.reminder'].send_monthly_reminder()

        self.assertEqual(len(self._reminders(user)), 1)

    def test_inactive_and_portal_users_are_skipped(self):
        archived = self._user('dgii_contador_archivado', 'account.group_account_manager')
        archived.active = False
        portal = self._user('dgii_portal', 'base.group_portal')

        self.env['l10n_do_ncf.dgii.reminder'].send_monthly_reminder()

        self.assertFalse(self._reminders(archived))
        self.assertFalse(self._reminders(portal))
