# -*- coding: utf-8 -*-
"""Retenciones de la pestaña frente a las del asiento (entrega 1).

Solo los impuestos negativos de la línea generan asiento (pasivo con la DGII y
menos por pagar al proveedor). La pestaña "Retenciones" no, pero el 606, el
IR-17 y el e-CF la leen primero. Cada caso del análisis:
- pestaña sola: la factura queda marcada "Retención sin asiento";
- impuestos solos: cuadra;
- los dos distintos: "No coincide con el asiento";
- impuesto de retención sin tipo DGII: está en el asiento y no en los reportes;
- ISR 15 % como impuesto: cuadra en montos.
La lista sale en el Panel ("Configuración pendiente") y la factura lo avisa.
"""
from odoo import Command, fields
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
                            dgii_606_bucket='isr_retenido')
        cls.ret_untyped = tax('Retención honorarios 10% (sin tipo)', -10.0)
        RetType = cls.env['l10n_do_ncf.retention.type']
        cls.rt_itbis_100 = RetType.search([('code', '=', 'ITBIS_100')], limit=1)
        cls.rt_isr_prof = RetType.search([('code', '=', 'ISR_PROF')], limit=1)
        cls.product = cls.env['product.product'].create({'name': 'Servicio', 'type': 'service'})
        cls._vendor_ncf = 100

    def _bill(self, taxes, tab=(), post=True):
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
        if post:
            bill.action_post()
        return bill

    def _tab(self):
        return [(self.rt_itbis_100, 180.0), (self.rt_isr_prof, 1000.0)]

    # ---------------------------------------------------------------
    # Casos del análisis
    # ---------------------------------------------------------------
    def test_tab_only_has_no_entry(self):
        bill = self._bill(self.tax_18, self._tab())
        self.assertEqual(bill.amount_residual, 1180.0, 'La pestaña no reduce lo que se le debe')
        self.assertEqual(bill.l10n_do_retention_check, 'no_entry')
        self.assertEqual(bill.l10n_do_retention_gap, 280.0)
        # Los reportes sí la ven.
        self.assertEqual(bill.l10n_do_itbis_retenido, 180.0)
        self.assertEqual(bill.l10n_do_isr_retenido, 100.0)

    def test_taxes_only_match(self):
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15)
        self.assertEqual(bill.amount_residual, 850.0)
        self.assertFalse(bill.l10n_do_retention_check)
        self.assertEqual(bill.l10n_do_retention_gap, 0.0)

    def test_tab_and_taxes_disagree(self):
        # Asiento: ITBIS 180 + ISR 150. Pestaña: ITBIS 180 + ISR 100.
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15, self._tab())
        self.assertEqual(bill.l10n_do_retention_check, 'mismatch')
        self.assertEqual(bill.l10n_do_retention_gap, 50.0)
        # El 606 usa la pestaña (100), el asiento retiene 150.
        self.assertEqual(bill.l10n_do_isr_retenido, 100.0)
        self.assertEqual(bill.amount_residual, 850.0)

    def test_tab_and_taxes_equal_are_fine(self):
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15,
                          [(self.rt_itbis_100, 180.0), (self.rt_isr_prof, 1500.0)])
        self.assertFalse(bill.l10n_do_retention_check)

    def test_untyped_retention_tax(self):
        bill = self._bill(self.tax_18 | self.ret_untyped)
        self.assertEqual(bill.amount_residual, 1080.0, 'El asiento sí la retiene')
        self.assertEqual(bill.l10n_do_retention_check, 'untyped')
        self.assertEqual(bill.l10n_do_retention_gap, 100.0)
        self.assertEqual(bill.l10n_do_total_isr_retention, 0.0, 'Los reportes no la ven')
        action = bill.action_l10n_do_open_untyped_retention_taxes()
        self.assertEqual(action['domain'], [('id', 'in', self.ret_untyped.ids)])

    def test_isr_15_as_tax_is_consistent_in_amounts(self):
        bill = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15)
        self.assertFalse(bill.l10n_do_retention_check)
        self.assertEqual(bill.l10n_do_total_isr_retention, 150.0)
        self.assertEqual(bill.l10n_do_isr_retenido, 150.0)

    def test_draft_is_warned_too(self):
        bill = self._bill(self.tax_18, self._tab(), post=False)
        self.assertEqual(bill.l10n_do_retention_check, 'no_entry')

    # ---------------------------------------------------------------
    # Panel y factura
    # ---------------------------------------------------------------
    def test_panel_lists_posted_bills_to_adjust(self):
        no_entry = self._bill(self.tax_18, self._tab())
        mismatch = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15, self._tab())
        fine = self._bill(self.tax_18 | self.ret_itbis | self.ret_isr15)
        draft = self._bill(self.tax_18, self._tab(), post=False)
        pending = self.company._l10n_do_pending_retentions()
        self.assertIn(no_entry, pending)
        self.assertIn(mismatch, pending)
        self.assertNotIn(fine, pending)
        self.assertNotIn(draft, pending, 'Solo las confirmadas: un borrador se corrige')
        groups = {g['key']: g for g in self.company._l10n_do_config_pending()}
        self.assertEqual(groups['retentions']['count'], len(pending))
        self.assertEqual(groups['retentions']['severity'], 'warning')
        action = self.company._l10n_do_config_pending_action('retentions')
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(action['domain'], [('id', 'in', pending.ids)])

    def test_bill_form_shows_the_warning(self):
        arch = self.env['account.move'].get_view(
            self.env.ref('account.view_move_form').id, 'form')['arch']
        self.assertIn('Retenciones sin asiento', arch)
        self.assertIn('l10n_do_retention_gap', arch)

    # ---------------------------------------------------------------
    # Proveedor informal: ya no se sugiere nada en la pestaña
    # ---------------------------------------------------------------
    def test_informal_supplier_gets_nothing_in_the_tab(self):
        informal = self.env['res.partner'].create({
            'name': 'Pedro Martínez', 'country_id': self.country_do.id,
            'vat': '00113918205', 'l10n_do_is_informal_supplier': True})
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = informal
        form.invoice_date = fields.Date.today()
        with form.invoice_line_ids.new() as line:
            line.product_id = self.product
            line.price_unit = 1000.0
            line.tax_ids.add(self.tax_18)
        bill = form.save()
        self.assertEqual(bill.l10n_do_purchase_kind, 'informal')
        self.assertFalse(bill.l10n_do_retention_ids)
