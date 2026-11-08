# -*- coding: utf-8 -*-
"""Retenciones de compras: una sola fuente de verdad, los impuestos de
retención de las líneas (los que generan asiento).

Casos del análisis:
- pestaña sola: en una factura nueva no se confirma; en una anterior a
  19.0.4 queda marcada "Retención sin asiento" y sus reportes no cambian;
- impuestos solos: el asiento, el 606, el IR-17 y la pestaña (copia) cuadran;
- los dos distintos: en una factura anterior se marca "No coincide";
- impuesto de retención sin tipo DGII: está en el asiento y no en los
  reportes: se marca;
- ISR 15 %: la copia de la pestaña lleva el impuesto, su tasa y su base
  (antes salía como "ISR Servicios Profesionales 10 %" con base 1,500).
La lista sale en el Panel ("Configuración pendiente") y la factura lo avisa.
"""
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestRetentionCheck(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Tax = cls.env['account.tax']

        def tax(name, amount, **vals):
            return Tax.create({'name': name, 'amount': amount, 'amount_type': 'percent',
                               'type_tax_use': 'purchase', 'company_id': cls.company.id, **vals})

        cls.tax_18 = tax('ITBIS 18% compras (ret)', 18.0, dgii_tax_kind='itbis')
        cls.ret_itbis = tax('-100% ITBIS (prueba)', -18.0, dgii_retention_type='itbis',
                            dgii_606_bucket='itbis_retenido')
        cls.ret_isr15 = tax('-15% ISR Honorarios (prueba)', -15.0, dgii_retention_type='isr',
                            dgii_606_bucket='isr_retenido', dgii_isr_retention_type='02')
        cls.ret_untyped = tax('Retención honorarios 10% (sin tipo)', -10.0)
        RetType = cls.env['l10n_do_ncf.retention.type']
        cls.rt_itbis_100 = RetType.search([('code', '=', 'ITBIS_100')], limit=1)
        cls.rt_isr_prof = RetType.search([('code', '=', 'ISR_PROF')], limit=1)
        cls.product = cls.env['product.product'].create({'name': 'Servicio', 'type': 'service'})
        cls._vendor_ncf = 100

    def _bill(self, taxes, tab=(), post=True, legacy=False):
        type(self)._vendor_ncf += 1
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_taxpayer.id,
            'invoice_date': fields.Date.today(),
            'l10n_do_vendor_ncf': 'B01%08d' % self._vendor_ncf,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id, 'name': 'Servicio', 'quantity': 1,
                'price_unit': 1000.0, 'tax_ids': [Command.set(taxes.ids)],
            })],
        })
        if tab:
            bill.l10n_do_retention_ids = [
                Command.create({'retention_type_id': kind.id, 'base_amount': base})
                for kind, base in tab]
        if legacy:
            # Factura de antes de 19.0.4: sus retenciones estaban en la pestaña.
            bill.l10n_do_retention_legacy = True
        if post:
            bill.action_post()
        return bill

    def _tab(self):
        return [(self.rt_itbis_100, 180.0), (self.rt_isr_prof, 1000.0)]

    # ---------------------------------------------------------------
    # Pestaña sola
    # ---------------------------------------------------------------
    def test_tab_only_new_bill_cannot_be_posted(self):
        bill = self._bill(self.tax_18, self._tab(), post=False)
        self.assertEqual(bill.l10n_do_retention_check, 'no_entry')
        with self.assertRaisesRegex(UserError, 'no generan asiento'):
            bill.action_post()

    def test_tab_only_legacy_bill_keeps_what_was_reported(self):
        bill = self._bill(self.tax_18, self._tab(), legacy=True)
        self.assertEqual(bill.amount_residual, 1180.0, 'La pestaña no reduce lo que se le debe')
        self.assertEqual(bill.l10n_do_retention_check, 'no_entry')
        self.assertEqual(bill.l10n_do_retention_gap, 280.0)
        self.assertEqual(bill.l10n_do_itbis_retenido, 180.0)
        self.assertEqual(bill.l10n_do_isr_retenido, 100.0)
        self.assertEqual(bill.l10n_do_total_isr_retention, 100.0)
        self.assertEqual(len(bill.l10n_do_retention_ids), 2, 'La pestaña anterior no se toca')

    # ---------------------------------------------------------------
    # Impuestos solos
    # ---------------------------------------------------------------
    def test_taxes_only_are_the_single_source(self):
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15)
        self.assertEqual(bill.amount_residual, 850.0)
        self.assertFalse(bill.l10n_do_retention_check)
        self.assertEqual(bill.l10n_do_itbis_retenido, 180.0)
        self.assertEqual(bill.l10n_do_isr_retenido, 150.0)
        self.assertEqual(bill.l10n_do_total_itbis_retention, 180.0)
        self.assertEqual(bill.l10n_do_total_isr_retention, 150.0)
        self.assertEqual(bill.l10n_do_gross_total, 1180.0)
        self.assertEqual(bill._l10n_do_isr_retention_type(), '02')
        self.assertEqual(bill._l10n_do_isr_retention_base(), 1000.0)
        self.assertEqual(len(bill.l10n_do_retention_line_ids), 2)

    def test_draft_reports_follow_the_line_taxes(self):
        bill = self._bill(self.tax_18 | self.ret_isr15, post=False)
        self.assertEqual(bill.l10n_do_isr_retenido, 150.0)
        bill.invoice_line_ids.tax_ids = self.tax_18
        self.assertEqual(bill.l10n_do_isr_retenido, 0.0)

    # ---------------------------------------------------------------
    # Los dos distintos
    # ---------------------------------------------------------------
    def test_tab_and_taxes_disagree_on_legacy_bill(self):
        # Asiento: ITBIS 180 + ISR 150. Pestaña: ITBIS 180 + ISR 100.
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15, self._tab(), legacy=True)
        self.assertEqual(bill.l10n_do_retention_check, 'mismatch')
        self.assertEqual(bill.l10n_do_retention_gap, 50.0)
        self.assertEqual(bill.l10n_do_isr_retenido, 100.0, 'Lo que se reportó')
        self.assertEqual(bill.amount_residual, 850.0)

    def test_tab_and_taxes_on_new_bill_cannot_be_posted(self):
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15, self._tab(), post=False)
        self.assertEqual(bill.l10n_do_retention_check, 'mismatch')
        with self.assertRaises(UserError):
            bill.action_post()
        # Borrando las filas de la pestaña se confirma con los impuestos.
        bill.l10n_do_retention_ids.unlink()
        bill.action_post()
        self.assertFalse(bill.l10n_do_retention_check)

    # ---------------------------------------------------------------
    # Impuesto sin tipo DGII
    # ---------------------------------------------------------------
    def test_untyped_retention_tax(self):
        bill = self._bill(self.tax_18 | self.ret_untyped)
        self.assertEqual(bill.amount_residual, 1080.0, 'El asiento sí la retiene')
        self.assertEqual(bill.l10n_do_retention_check, 'untyped')
        self.assertEqual(bill.l10n_do_retention_gap, 100.0)
        self.assertEqual(bill.l10n_do_total_isr_retention, 0.0, 'Los reportes no la ven')
        self.assertEqual(bill.l10n_do_isr_retenido, 0.0)
        action = bill.action_l10n_do_open_untyped_retention_taxes()
        self.assertEqual(action['domain'], [('id', 'in', self.ret_untyped.ids)])

    # ---------------------------------------------------------------
    # ISR 15 %: la copia de la pestaña es el impuesto, no un 10 % con base 1,500
    # ---------------------------------------------------------------
    def test_isr_15_copy_keeps_tax_rate_and_base(self):
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15)
        isr_row = bill.l10n_do_retention_ids.filtered(lambda r: r.tax_id == self.ret_isr15)
        self.assertEqual(len(isr_row), 1)
        self.assertFalse(isr_row.retention_type_id)
        self.assertEqual(isr_row.rate, 15.0)
        self.assertEqual(isr_row.base_amount, 1000.0)
        self.assertEqual(isr_row.retention_amount, 150.0)
        self.assertEqual(isr_row.dgii_606_bucket, 'isr_retenido')
        self.assertFalse(bill.l10n_do_retention_check)

    # ---------------------------------------------------------------
    # Panel y factura
    # ---------------------------------------------------------------
    def test_panel_lists_posted_bills_to_adjust(self):
        no_entry = self._bill(self.tax_18, self._tab(), legacy=True)
        mismatch = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15, self._tab(), legacy=True)
        untyped = self._bill(self.tax_18 | self.ret_untyped)
        fine = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15)
        draft = self._bill(self.tax_18, self._tab(), post=False)
        pending = self.company._l10n_do_pending_retentions()
        self.assertEqual(pending & (no_entry | mismatch | untyped | fine | draft),
                         no_entry | mismatch | untyped)
        groups = {g['key']: g for g in self.company._l10n_do_config_pending()}
        self.assertEqual(groups['retentions']['count'], len(pending))
        self.assertEqual(groups['retentions']['severity'], 'warning')
        action = self.company._l10n_do_config_pending_action('retentions')
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(action['domain'], [('id', 'in', pending.ids)])

    def test_bill_form_shows_the_warning_and_the_entry(self):
        arch = self.env['account.move'].get_view(
            self.env.ref('account.view_move_form').id, 'form')['arch']
        self.assertIn('Retenciones sin asiento', arch)
        self.assertIn('l10n_do_retention_gap', arch)
        self.assertIn('l10n_do_retention_line_ids', arch)


@tagged('post_install', '-at_install')
class TestRetentionSuggestions(NcfCommon):
    """Retenciones sugeridas como impuestos de línea y borradores convertidos."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Tax = cls.env['account.tax']

        def tax(name, amount, **vals):
            return Tax.create({'name': name, 'amount': amount, 'amount_type': 'percent',
                               'type_tax_use': 'purchase', 'company_id': cls.company.id, **vals})

        cls.tax_18 = tax('ITBIS 18% compras (sug)', 18.0, dgii_tax_kind='itbis')
        cls.ret_itbis = tax('-100% ITBIS (sug)', -18.0, dgii_retention_type='itbis',
                            dgii_606_bucket='itbis_retenido')
        cls.ret_isr = tax('-10% ISR (sug)', -10.0, dgii_retention_type='isr',
                          dgii_606_bucket='isr_retenido')
        cls.ret_ext = tax('-27% ISR exterior (sug)', -27.0, dgii_retention_type='isr',
                          dgii_606_bucket='isr_retenido')
        cls.service = cls.env['product.product'].create({
            'name': 'Plomería', 'type': 'service', 'supplier_taxes_id': [Command.set(cls.tax_18.ids)]})
        cls.good = cls.env['product.product'].create({
            'name': 'Tubo', 'type': 'consu', 'supplier_taxes_id': [Command.set(cls.tax_18.ids)]})
        cls.informal = cls.env['res.partner'].create({
            'name': 'Pedro Martínez', 'country_id': cls.country_do.id,
            'vat': '00113918205', 'l10n_do_is_informal_supplier': True})
        cls.foreign = cls.env['res.partner'].create({
            'name': 'Foreign Inc.', 'country_id': cls.env.ref('base.us').id})

    def _form_bill(self, partner, products):
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = partner
        form.invoice_date = fields.Date.today()
        for product in products:
            with form.invoice_line_ids.new() as line:
                line.product_id = product
                line.price_unit = 1000.0
        return form.save()

    def test_nothing_is_suggested_until_the_company_says_so(self):
        bill = self._form_bill(self.informal, self.service)
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.tax_18)
        self.assertFalse(bill.l10n_do_retention_ids)

    def test_informal_suggestions_are_line_taxes(self):
        self.company.l10n_do_informal_retention_tax_ids = self.ret_itbis | self.ret_isr
        bill = self._form_bill(self.informal, self.service | self.good)
        service_line, good_line = bill.invoice_line_ids.sorted(lambda l: l.product_id != self.service)
        self.assertEqual(service_line.tax_ids, self.tax_18 | self.ret_itbis | self.ret_isr)
        self.assertEqual(good_line.tax_ids, self.tax_18 | self.ret_itbis, 'El ISR solo en servicios')
        self.assertFalse(bill.l10n_do_retention_ids, 'Nada en la pestaña')
        self.assertEqual(bill.l10n_do_isr_retenido, 100.0)
        self.assertEqual(bill.l10n_do_itbis_retenido, 360.0)
        # Editables: se quitan de la línea.
        service_line.tax_ids -= self.ret_isr
        self.assertEqual(bill.l10n_do_isr_retenido, 0.0)

    def test_exterior_suggestion_and_kind_change(self):
        self.company.l10n_do_exterior_retention_tax_ids = self.ret_ext
        self.company.l10n_do_informal_retention_tax_ids = self.ret_itbis | self.ret_isr
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = self.foreign
        form.invoice_date = fields.Date.today()
        with form.invoice_line_ids.new() as line:
            # Pago al exterior: un servicio sin ITBIS de un proveedor extranjero.
            line.product_id = self.env['product.product'].create({
                'name': 'Licencia', 'type': 'service', 'supplier_taxes_id': False})
            line.price_unit = 1000.0
        self.assertEqual(form.l10n_do_purchase_kind, 'exterior')
        form.l10n_do_purchase_kind = 'minor_expense'
        form.l10n_do_purchase_kind = 'exterior'
        bill = form.save()
        self.assertIn(self.ret_ext, bill.invoice_line_ids.tax_ids)
        self.assertEqual(bill.l10n_do_isr_retenido, 270.0)
        form = Form(bill)
        form.l10n_do_purchase_kind = 'minor_expense'
        bill = form.save()
        self.assertFalse(bill.invoice_line_ids.tax_ids & self.ret_ext, 'Un gasto menor no lleva')

    def test_draft_with_tab_is_converted_when_the_equivalent_tax_is_set(self):
        rt_isr_prof = self.env['l10n_do_ncf.retention.type'].search([('code', '=', 'ISR_PROF')], limit=1)
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.informal.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'product_id': self.service.id, 'name': 'Plomería', 'quantity': 1,
                'price_unit': 1000.0, 'tax_ids': [Command.set(self.tax_18.ids)]})],
            'l10n_do_retention_ids': [Command.create({
                'retention_type_id': rt_isr_prof.id, 'base_amount': 1000.0})],
        })
        self.assertEqual(bill.l10n_do_retention_check, 'no_entry')
        # Sin impuesto equivalente no se convierte.
        self.assertFalse(self.env['account.move']._l10n_do_convert_tab_retentions())
        rt_isr_prof.tax_ids = self.ret_isr   # lo indica el contador
        self.assertFalse(bill.l10n_do_retention_ids)
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.tax_18 | self.ret_isr)
        self.assertEqual(bill.amount_residual, 1080.0)
        self.assertFalse(bill.l10n_do_retention_check)

    def test_draft_with_tab_is_not_converted_if_amounts_differ(self):
        rt_isr_prof = self.env['l10n_do_ncf.retention.type'].search([('code', '=', 'ISR_PROF')], limit=1)
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.informal.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'product_id': self.service.id, 'name': 'Plomería', 'quantity': 1,
                'price_unit': 1000.0, 'tax_ids': [Command.set(self.tax_18.ids)]})],
            'l10n_do_retention_ids': [Command.create({
                'retention_type_id': rt_isr_prof.id, 'base_amount': 700.0})],
        })
        rt_isr_prof.tax_ids = self.ret_isr
        self.assertEqual(len(bill.l10n_do_retention_ids), 1, 'Se queda para revisar')
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.tax_18)

    def test_migration_marks_posted_bills_with_tab_as_legacy(self):
        import importlib.util
        import os
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.informal.id,
            'invoice_date': fields.Date.today(), 'l10n_do_vendor_ncf': 'B0100000777',
            'l10n_do_fiscal_type': 'fiscal',
            'invoice_line_ids': [Command.create({
                'name': 'Servicio', 'quantity': 1, 'price_unit': 1000.0, 'tax_ids': []})],
        })
        bill.action_post()
        self.env['l10n_do_ncf.move.retention'].create({
            'move_id': bill.id, 'retention_type_id': self.env['l10n_do_ncf.retention.type'].search(
                [('code', '=', 'ISR_PROF')], limit=1).id, 'base_amount': 1000.0})
        self.env.flush_all()
        taxes_before = self.env['account.tax'].with_context(active_test=False).search_count([])
        path = os.path.join(os.path.dirname(__file__), '..', 'migrations', '19.0.4.0.0', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('l10n_do_ncf_mig_40', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.3.7.1')
        self.env.invalidate_all()
        self.assertTrue(bill.l10n_do_retention_legacy)
        self.assertEqual(self.env['account.tax'].with_context(active_test=False).search_count([]),
                         taxes_before, 'La migración no crea impuestos')
        self.assertEqual(bill.l10n_do_retention_check, 'no_entry')


@tagged('post_install', '-at_install')
class TestRetentionAutoconfig(NcfCommon):
    """La configuración automática no crea impuestos de retención: solo pone el
    tipo 606 de ISR donde el impuesto de la plantilla l10n_do es inequívoco."""

    def _tmpl(self, name):
        return self.env.ref('account.%s_%s' % (self.company.id, name), raise_if_not_found=False)

    def test_isr_type_only_where_unambiguous(self):
        from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig
        rent, fee = self._tmpl('ret_15_income_rent'), self._tmpl('ret_15_income_person')
        if not rent or not fee:
            self.skipTest('La compañía de prueba no tiene la plantilla l10n_do')
        Tax = self.env['account.tax'].with_context(active_test=False)
        count = Tax.search_count([])
        l10n_do_autoconfig.autoconfigure(self.env, self.company)
        self.assertEqual(Tax.search_count([]), count)
        self.assertEqual(rent.dgii_isr_retention_type, '01')
        self.assertEqual(fee.dgii_isr_retention_type, '02')
        for name in ('ret_10_income_dividend', 'ret_3_income_person', 'ret_2_income_transfer',
                     'ret_3_income_article_70', 'ret_27_income_remittance',
                     'ret_15_income_foreign_royalties_technology'):
            tax = self._tmpl(name)
            if tax:
                self.assertFalse(tax.dgii_isr_retention_type, name)
        self.assertFalse(self.company.l10n_do_informal_retention_tax_ids)
        # Pago al exterior: el ISR 27 % de la plantilla (Guía No. 5, pág. 5).
        self.assertEqual(self.company.l10n_do_exterior_retention_tax_ids,
                         self._tmpl('ret_27_income_remittance'))
