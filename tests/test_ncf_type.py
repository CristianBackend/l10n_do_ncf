# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestNcfType(NcfCommon):
    """Selección automática del tipo de NCF (_compute_l10n_do_ncf_type_id)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_sales_ncf_sequences()

    def _assert_type(self, move, prefix):
        self.assertEqual(move.l10n_do_ncf_type_id.prefix, prefix)

    def test_company_is_dominican(self):
        self.assertEqual(self.company.country_id.code, 'DO')

    def test_sale_requires_ncf(self):
        invoice = self._create_invoice(self.partner_consumer)
        self.assertTrue(invoice.l10n_do_ncf_required)

    def test_final_consumer_gets_b02(self):
        self._assert_type(self._create_invoice(self.partner_consumer), 'B02')

    def test_rnc_partner_is_classified_as_taxpayer_and_gets_b01(self):
        self.assertEqual(self.partner_taxpayer.l10n_do_dgii_tax_payer_type, 'taxpayer')
        self._assert_type(self._create_invoice(self.partner_taxpayer), 'B01')

    def test_document_alone_does_not_give_b01(self):
        """Lo que decide B01 es el tipo de contribuyente, no tener documento."""
        self.partner_taxpayer.l10n_do_dgii_tax_payer_type = 'final_consumer'
        self._assert_type(self._create_invoice(self.partner_taxpayer), 'B02')

    def test_governmental_gets_b15(self):
        self.partner_consumer.l10n_do_dgii_tax_payer_type = 'governmental'
        self._assert_type(self._create_invoice(self.partner_consumer), 'B15')

    def test_special_regime_gets_b14(self):
        self.partner_consumer.l10n_do_dgii_tax_payer_type = 'special_regime'
        self._assert_type(self._create_invoice(self.partner_consumer), 'B14')

    def test_foreign_customer_gets_b16(self):
        self._assert_type(self._create_invoice(self.partner_foreign), 'B16')

    def test_type_follows_partner_change(self):
        invoice = self._create_invoice(self.partner_consumer)
        self._assert_type(invoice, 'B02')
        invoice.partner_id = self.partner_taxpayer
        self._assert_type(invoice, 'B01')

    def test_debit_note_gets_b03(self):
        invoice = self._create_invoice(self.partner_taxpayer, l10n_do_is_debit_note=True)
        self._assert_type(invoice, 'B03')

    def test_credit_note_gets_b04(self):
        refund = self._create_refund(
            self.partner_taxpayer, l10n_do_ncf_origin='B0100000001',
        )
        self._assert_type(refund, 'B04')

    def test_purchase_types(self):
        bill = self._create_invoice(self.partner_consumer, move_type='in_invoice')
        self.assertFalse(bill.l10n_do_ncf_type_id, 'Compra fiscal: el NCF es del proveedor')
        for fiscal_type, prefix in (
            ('informal', 'B11'),
            ('minor_expense', 'B13'),
            ('special', 'B14'),
            ('governmental', 'B15'),
            ('exterior', 'B17'),
        ):
            bill.l10n_do_fiscal_type = fiscal_type
            self._assert_type(bill, prefix)

    def test_never_selects_electronic_type(self):
        """Hoy ninguna ruta asigna tipos e-CF: lo hará el conector."""
        moves = (
            self._create_invoice(self.partner_consumer)
            + self._create_invoice(self.partner_taxpayer)
            + self._create_invoice(self.partner_foreign)
        )
        self.assertFalse(any(moves.mapped('l10n_do_ncf_type_id.is_electronic')))
