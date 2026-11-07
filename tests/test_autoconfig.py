# -*- coding: utf-8 -*-
"""Configuración DGII que se deduce del plan contable l10n_do y tarjeta
"Configuración pendiente" del panel."""
from odoo import Command
from odoo.tests import tagged

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestAutoconfig(NcfCommon):

    @classmethod
    def _new_do_company(cls, name='Compañía Nueva SRL'):
        company = cls.env['res.company'].create({
            'name': name, 'country_id': cls.env.ref('base.do').id,
            'currency_id': cls.env.ref('base.DOP').id,
        })
        cls.env.user.company_ids |= company
        cls.env['account.chart.template'].try_loading('do', company, install_demo=False)
        return company

    def _tax(self, company, template):
        return self.env.ref('account.%s_%s' % (company.id, template))

    def test_new_company_with_the_do_chart_has_nothing_pending_in_taxes_or_journals(self):
        company = self._new_do_company()
        self.assertFalse(company._l10n_do_pending_taxes_kind())
        self.assertFalse(company._l10n_do_pending_taxes_zero())
        self.assertFalse(company._l10n_do_pending_journals())
        pending = {g['key'] for g in company._l10n_do_config_pending()}
        self.assertFalse(pending & {'taxes_kind', 'taxes_zero', 'journals'})
        # El caso real: "ITBIS Exempt" de ventas sale ya como Exento.
        exempt = self._tax(company, 'tax_0_sale')
        self.assertEqual(exempt.name, 'ITBIS Exempt')
        self.assertEqual(exempt.dgii_itbis_zero_type, 'exempt')
        self.assertEqual(self._tax(company, 'tax_18_sale').dgii_tax_kind, 'itbis')
        self.assertEqual(self._tax(company, 'tax_tip_sale').dgii_tax_kind, 'tip')
        self.assertEqual(self._tax(company, 'tax_10_telco').dgii_tax_kind, 'isc')
        self.assertEqual(self._tax(company, 'ret_27_income_remittance').dgii_606_bucket, 'isr_retenido')
        self.assertEqual(self._tax(company, 'ret_100_tax_person').dgii_retention_type, 'itbis')
        # Exportación: la plantilla no trae ITBIS 0 %; se crea uno a tasa cero.
        export = self.env['account.tax'].search([
            ('company_id', '=', company.id), ('dgii_itbis_zero_type', '=', 'zero_rated')])
        self.assertEqual(export.mapped('amount'), [0.0])
        # Diarios: efectivo 01, banco 02 (tabla de formas de pago del 606/607).
        journals = self.env['account.journal'].search([('company_id', '=', company.id)])
        for journal in journals.filtered(lambda j: j.type == 'cash'):
            self.assertEqual(journal.l10n_do_payment_form, '01')
        for journal in journals.filtered(lambda j: j.type == 'bank'):
            self.assertEqual(journal.l10n_do_payment_form, '02')

    def test_a_value_set_by_the_user_is_never_overwritten(self):
        company = self._new_do_company('Valores del Usuario SRL')
        exempt = self._tax(company, 'tax_0_sale')
        tip = self._tax(company, 'tax_tip_sale')
        bank = self.env['account.journal'].search(
            [('company_id', '=', company.id), ('type', '=', 'bank')], limit=1)
        exempt.dgii_itbis_zero_type = 'zero_rated'
        tip.dgii_tax_kind = 'other'
        bank.l10n_do_payment_form = '03'
        # Lo que hace la actualización del módulo (migración 19.0.3.4.0).
        l10n_do_autoconfig.autoconfigure(self.env, company)
        self.assertEqual(exempt.dgii_itbis_zero_type, 'zero_rated')
        self.assertEqual(tip.dgii_tax_kind, 'other')
        self.assertEqual(bank.l10n_do_payment_form, '03')
        # Lo vacío sí se completa.
        exempt_purchase = self._tax(company, 'tax_0_purch')
        exempt_purchase.dgii_itbis_zero_type = False
        l10n_do_autoconfig.autoconfigure(self.env, company)
        self.assertEqual(exempt_purchase.dgii_itbis_zero_type, 'exempt')

    def test_new_bank_journal_gets_its_payment_form(self):
        journal = self.env['account.journal'].create({
            'name': 'Banco Nuevo', 'type': 'bank', 'code': 'BNKN', 'company_id': self.company.id})
        self.assertEqual(journal.l10n_do_payment_form, '02')

    def test_pending_card_counts(self):
        company = self.company
        Tax = self.env['account.tax']
        # Partir de cero en la compañía de prueba
        Tax.search([('company_id', '=', company.id)]).write({
            'dgii_tax_kind': 'itbis', 'dgii_itbis_zero_type': 'exempt'})
        self.env['account.journal'].search([('company_id', '=', company.id)]).filtered(
            lambda j: j.type in ('bank', 'cash', 'credit')).l10n_do_payment_form = '02'
        self.assertFalse([g for g in company._l10n_do_config_pending()
                          if g['key'] in ('taxes_kind', 'taxes_zero', 'journals')])

        def tax(name, amount, **vals):
            return Tax.create({'name': name, 'amount': amount, 'amount_type': 'percent',
                               'type_tax_use': 'purchase', 'company_id': company.id, **vals})
        tax('Tasa municipal', 2.0)
        tax('Contribución', 3.0)
        tax('ITBIS 18 % sin clase', 18.0)      # se toma como ITBIS: no cuenta
        tax('Retención', -10.0)                # negativo: no cuenta
        tax('Cero sin indicador', 0.0)
        self.env['account.journal'].create({
            'name': 'Banco sin forma', 'type': 'bank', 'code': 'BSF', 'company_id': company.id,
            'l10n_do_payment_form': False})
        journal = self.env['account.journal'].search(
            [('company_id', '=', company.id), ('code', '=', 'BSF')])
        journal.l10n_do_payment_form = False
        account = self.env['account.account'].create({
            'name': 'Gasto sin tipo', 'code': '61999999', 'account_type': 'expense'})
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.partner_taxpayer.id,
            'invoice_date': '2026-11-01', 'l10n_do_vendor_ncf': 'B0100000099',
            'invoice_line_ids': [Command.create({
                'name': 'Gasto', 'quantity': 1, 'price_unit': 100.0, 'tax_ids': [],
                'account_id': account.id})],
        })
        bill.action_post()
        pending = company._l10n_do_config_pending()
        counts = {g['key']: g['count'] for g in pending}
        self.assertEqual(counts['taxes_kind'], 2)
        self.assertEqual(counts['taxes_zero'], 1)
        self.assertEqual(counts['journals'], 1)
        # Lo que bloquea la emisión va marcado aparte de lo que solo afecta
        # los reportes; el texto lleva el número delante y concuerda.
        by_key = {g['key']: g for g in pending}
        self.assertEqual(by_key['taxes_zero']['severity'], 'danger')
        self.assertEqual(by_key['taxes_zero']['text'],
                         '1 impuesto de 0 % no indica si es Exento o tasa cero. '
                         'Sin eso no se puede emitir el e-CF.')
        self.assertEqual(by_key['taxes_kind']['severity'], 'warning')
        self.assertEqual(by_key['taxes_kind']['text'],
                         '2 impuestos sin clasificar para el 606 y el 607.')
        self.assertEqual(by_key['journals']['text'],
                         '1 diario sin forma de pago para el 606 y el 607.')
        self.assertEqual(by_key['accounts']['severity'], 'warning')
        self.assertEqual(by_key['accounts']['text'],
                         '%s cuenta%s de gasto sin tipo de bienes y servicios para el 606.' % (
                             by_key['accounts']['count'],
                             '' if by_key['accounts']['count'] == 1 else 's'))
        self.assertIn(account, company._l10n_do_pending_accounts())
        # Cada grupo abre su lista filtrada.
        action = self.env['l10n_do_ncf.dashboard'].l10n_do_open_config_pending('taxes_kind')
        self.assertEqual(action['res_model'], 'account.tax')
        self.assertEqual(len(action['domain'][0][2]), 2)
        data = self.env['l10n_do_ncf.dashboard'].get_dashboard_data()
        self.assertEqual({g['key'] for g in data['config_pending']} >= {'taxes_kind', 'taxes_zero', 'journals', 'accounts'}, True)

    def test_expense_accounts_get_their_606_type(self):
        """Mapeo aprobado (docs/mapeo_cuentas_606.md): solo cuentas de
        categoría clara; las dudosas y las cinco de revisión quedan vacías."""
        company = self._new_do_company('Cuentas 606 SRL')

        def account(code):
            return self.env.ref('account.%s_l10n_do_%s' % (company.id, code))

        expected = {
            '61010900': '01', '61020100': '02', '61030211': '02', '61020800': '03',
            '61050100': '04', '61060200': '05', '61070400': '07', '51010100': '09',
            '12010202': '10', '61021100': '11',
        }
        for code, tipo in expected.items():
            self.assertEqual(account(code).l10n_do_606_expense_type, tipo, code)
        # Pendientes de revisión del contador y dudosas: vacías.
        for code in ('61060400', '61060500', '61060300', '61021500', '61070200',
                     '61010100', '61010102', '61021400', '61060700', '61040100'):
            self.assertFalse(account(code).l10n_do_606_expense_type, code)

    def test_account_606_type_set_by_the_user_is_kept(self):
        company = self._new_do_company('Cuenta del Usuario SRL')
        rent = self.env.ref('account.%s_l10n_do_61020800' % company.id)
        rent.l10n_do_606_expense_type = '02'
        l10n_do_autoconfig.autoconfigure(self.env, company)
        self.assertEqual(rent.l10n_do_606_expense_type, '02')
