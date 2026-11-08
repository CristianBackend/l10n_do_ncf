# -*- coding: utf-8 -*-
"""Tipo de compra de la factura de proveedor, sin códigos B/E a la vista.

El contador elige el proveedor y la factura sabe sola si es una compra con
comprobante del proveedor, a un proveedor informal (B11), un gasto menor (B13)
o un pago al exterior (B17). Se puede cambiar a mano.
"""
from odoo import Command, fields
from odoo.exceptions import RedirectWarning, UserError
from odoo.tests import Form, tagged

from .common import NcfCommon

CEDULA = '00113918205'


@tagged('post_install', '-at_install')
class TestPurchaseKind(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_informal = cls.env['res.partner'].create({
            'name': 'Pedro Martínez', 'country_id': cls.country_do.id,
            'vat': CEDULA, 'l10n_do_is_informal_supplier': True,
        })
        cls.partner_exterior = cls.env['res.partner'].create({
            'name': 'Foreign Supplier Inc.', 'is_company': True,
            'country_id': cls.env.ref('base.us').id,
        })
        cls.minor_partner = cls.company._l10n_do_minor_expense_partner()
        Tax = cls.env['account.tax']
        cls.ptax_18 = Tax.create({
            'name': 'ITBIS compras 18% (prueba)', 'amount': 18.0, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Servicio de limpieza', 'type': 'service',
            'supplier_taxes_id': [Command.set(cls.ptax_18.ids)],
        })
        cls.foreign_service = cls.env['product.product'].create({
            'name': 'Licencia de software (exterior)', 'type': 'service', 'supplier_taxes_id': False,
        })
        cls.foreign_good = cls.env['product.product'].create({
            'name': 'Silla de oficina (importada)', 'type': 'consu',
            'supplier_taxes_id': [Command.set(cls.ptax_18.ids)],
        })

    def _bill(self, partner, product=None, taxes=None, **vals):
        line = {'name': 'Servicio', 'quantity': 1, 'price_unit': 1000.0,
                'tax_ids': [Command.set(taxes.ids if taxes else [])]}
        if product:
            line['product_id'] = product.id
        return self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create(line)],
            **vals,
        })

    def _bill_form(self, partner):
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = partner
        form.invoice_date = fields.Date.today()
        return form

    # ---------------------------------------------------------------
    # Se elige solo según el proveedor
    # ---------------------------------------------------------------
    def test_kind_follows_the_supplier(self):
        cases = [
            (self.partner_taxpayer, 'vendor', 'fiscal', False),
            (self.partner_informal, 'informal', 'informal', 'B11'),
            (self.minor_partner, 'minor_expense', 'minor_expense', 'B13'),
            (self.partner_exterior, 'exterior', 'exterior', 'B17'),
        ]
        for partner, kind, fiscal_type, prefix in cases:
            with self.subTest(partner=partner.name):
                bill = self._bill(partner, product=self.foreign_service)
                self.assertEqual(bill.l10n_do_purchase_kind, kind)
                self.assertEqual(bill.l10n_do_fiscal_type, fiscal_type)
                self.assertEqual(bill.l10n_do_ncf_type_id.prefix or False, prefix)

    def test_kind_can_be_changed_by_hand(self):
        bill = self._bill(self.partner_taxpayer)
        bill.l10n_do_purchase_kind = 'minor_expense'
        self.assertEqual(bill.l10n_do_fiscal_type, 'minor_expense')
        self.assertEqual(bill.l10n_do_ncf_type_id.prefix, 'B13')
        bill.l10n_do_purchase_kind = 'vendor'
        self.assertEqual(bill.l10n_do_fiscal_type, 'fiscal')
        self.assertFalse(bill.l10n_do_ncf_type_id)

    def test_explicit_fiscal_type_is_kept(self):
        bill = self._bill(self.partner_taxpayer, l10n_do_fiscal_type='exterior')
        self.assertEqual(bill.l10n_do_purchase_kind, 'exterior')

    def test_form_changes_kind_with_the_supplier(self):
        form = self._bill_form(self.partner_informal)
        self.assertEqual(form.l10n_do_purchase_kind, 'informal')
        form.partner_id = self.partner_exterior
        # Extranjero sin líneas todavía: no se adivina.
        self.assertEqual(form.l10n_do_purchase_kind, 'vendor')
        with form.invoice_line_ids.new() as line:
            line.product_id = self.foreign_service
            line.price_unit = 500.0
        self.assertEqual(form.l10n_do_purchase_kind, 'exterior')
        form.l10n_do_purchase_kind = 'vendor'
        self.assertEqual(form.l10n_do_fiscal_type, 'fiscal')
        bill = form.save()
        self.assertTrue(bill.l10n_do_purchase_kind_manual)

    def test_posted_bill_keeps_its_kind(self):
        bill = self._bill(self.partner_taxpayer, l10n_do_vendor_ncf='B0100000099')
        bill.action_post()
        self.partner_taxpayer.country_id = self.env.ref('base.us')
        bill.invalidate_recordset()
        self.assertEqual(bill.l10n_do_fiscal_type, 'fiscal')

    def test_minor_expense_contact_per_company(self):
        partner = self.company.l10n_do_minor_expense_partner_id
        self.assertEqual(partner, self.minor_partner)
        self.assertEqual(partner.name, 'Gastos menores')
        self.assertFalse(partner.vat)
        self.assertEqual(partner.company_id, self.company)
        # Idempotente.
        self.assertEqual(self.company._l10n_do_minor_expense_partner(), partner)

    def test_choosing_minor_expense_without_supplier_sets_the_contact(self):
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.l10n_do_purchase_kind = 'minor_expense'
        self.assertEqual(form.partner_id, self.minor_partner)

    # ---------------------------------------------------------------
    # Gastos menores: Exento por defecto y sin retenciones
    # ---------------------------------------------------------------
    def test_minor_expense_new_lines_are_exempt(self):
        exempt = self.company._l10n_do_purchase_exempt_tax()
        form = self._bill_form(self.minor_partner)
        with form.invoice_line_ids.new() as line:
            line.product_id = self.product
            line.price_unit = 150.0
        bill = form.save()
        self.assertEqual(bill.invoice_line_ids.tax_ids, exempt)
        self.assertFalse(bill.l10n_do_retention_ids)
        # En una compra normal el mismo producto lleva su ITBIS.
        form = self._bill_form(self.partner_taxpayer)
        with form.invoice_line_ids.new() as line:
            line.product_id = self.product
        self.assertEqual(form.save().invoice_line_ids.tax_ids, self.ptax_18)

    def test_minor_expense_with_itbis_says_what_to_do(self):
        bill = self._bill(self.minor_partner)
        bill.invoice_line_ids.tax_ids = self.ptax_18
        self._create_ncf_sequence('13')
        with self.assertRaisesRegex(UserError, 'quite el impuesto'):
            bill.action_post()

    # ---------------------------------------------------------------
    # Proveedor informal
    # ---------------------------------------------------------------
    def test_informal_supplier_posts_with_contact_data(self):
        self._create_ncf_sequence('11')
        bill = self._bill(self.partner_informal)
        bill.action_post()
        self.assertEqual(bill.l10n_do_ncf_number[:3], 'B11')
        self.assertEqual(bill.l10n_do_informal_provider_name, 'Pedro Martínez')
        self.assertEqual(bill.l10n_do_informal_provider_cedula, CEDULA)
        self.assertEqual(bill._get_rnc_for_606(), CEDULA)

    def test_informal_supplier_with_rnc_opens_the_contact(self):
        self._create_ncf_sequence('11')
        bill = self._bill(self.partner_taxpayer, l10n_do_fiscal_type='informal')
        with self.assertRaises(RedirectWarning) as error:
            bill.action_post()
        self.assertIn('Con comprobante del proveedor', str(error.exception))
        self.assertEqual(error.exception.args[1]['res_id'], self.partner_taxpayer.id)

    def test_missing_sequence_offers_to_register_it(self):
        bill = self._bill(self.partner_informal)
        with self.assertRaises(RedirectWarning) as error:
            bill.action_post()
        self.assertIn('B11', str(error.exception))
        action = error.exception.args[1]
        self.assertEqual(action['res_model'], 'l10n_do_ncf.sequence')
        self.assertEqual(action['context']['default_ncf_type_id'], self._ncf_type('11').id)

    def test_exterior_without_isr_says_what_to_do(self):
        bill = self._bill(self.partner_exterior, product=self.foreign_service,
                          l10n_do_fiscal_type='exterior')
        self.assertFalse(bill.invoice_line_ids.tax_ids)
        with self.assertRaisesRegex(UserError, 'Retenciones'):
            bill.action_post()

    # ---------------------------------------------------------------
    # Proveedor extranjero: solo los servicios sin ITBIS son pago al exterior
    # (DGII, Guía del Contribuyente No. 5, pág. 5; instructivo del 606)
    # ---------------------------------------------------------------
    def test_foreign_goods_are_not_a_payment_abroad(self):
        bill = self._bill(self.partner_exterior, product=self.foreign_good, taxes=self.ptax_18,
                          l10n_do_vendor_ncf=False)
        self.assertEqual(bill.l10n_do_purchase_kind, 'vendor')
        self.assertFalse(bill.l10n_do_ncf_type_id)
        # Las reglas del B17/E47 (sin ITBIS, ISR obligatorio) no aplican.
        bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_foreign_service_with_itbis_is_not_a_payment_abroad(self):
        bill = self._bill(self.partner_exterior, product=self.foreign_service, taxes=self.ptax_18)
        self.assertEqual(bill.l10n_do_purchase_kind, 'vendor')

    def test_foreign_line_without_product_is_not_guessed(self):
        bill = self._bill(self.partner_exterior)
        self.assertEqual(bill.l10n_do_purchase_kind, 'vendor')

    def test_foreign_mixed_goods_and_services(self):
        bill = self._bill(self.partner_exterior, product=self.foreign_service)
        self.assertEqual(bill.l10n_do_purchase_kind, 'exterior')
        bill.invoice_line_ids = [Command.create({
            'product_id': self.foreign_good.id, 'name': 'Silla', 'quantity': 1,
            'price_unit': 100.0, 'tax_ids': []})]
        self.assertEqual(bill.l10n_do_purchase_kind, 'vendor')

    def test_kind_chosen_by_hand_is_kept_when_lines_change(self):
        bill = self._bill(self.partner_exterior, product=self.foreign_good)
        self.assertEqual(bill.l10n_do_purchase_kind, 'vendor')
        bill.l10n_do_purchase_kind = 'exterior'
        self.assertTrue(bill.l10n_do_purchase_kind_manual)
        bill.invoice_line_ids = [Command.create({
            'product_id': self.foreign_good.id, 'name': 'Otra silla', 'quantity': 1,
            'price_unit': 100.0, 'tax_ids': []})]
        self.assertEqual(bill.l10n_do_purchase_kind, 'exterior')

    def test_payment_abroad_suggests_isr_27(self):
        isr_27 = self.env.ref('account.%s_ret_27_income_remittance' % self.company.id,
                              raise_if_not_found=False)
        if not isr_27:
            self.skipTest('La compañía de prueba no tiene la plantilla l10n_do')
        self.assertEqual(self.company.l10n_do_exterior_retention_tax_ids, isr_27)
        form = self._bill_form(self.partner_exterior)
        with form.invoice_line_ids.new() as line:
            line.product_id = self.foreign_service
            line.price_unit = 1000.0
        bill = form.save()
        self.assertEqual(bill.l10n_do_purchase_kind, 'exterior')
        self.assertIn(isr_27, bill.invoice_line_ids.tax_ids)
        self.assertEqual(bill.l10n_do_isr_retenido, 270.0)
        # Editable: un convenio de doble tributación puede fijar otra tasa.
        bill.invoice_line_ids.tax_ids -= isr_27
        self.assertEqual(bill.l10n_do_isr_retenido, 0.0)
