# -*- coding: utf-8 -*-
from stdnum.do import rnc as stdnum_rnc

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NcfCommon


def _rnc(first_eight):
    """RNC de 9 dígitos con dígito verificador válido."""
    return first_eight + stdnum_rnc.calc_check_digit(first_eight)


@tagged('post_install', '-at_install')
class TestForeignCreditDebitNotes(NcfCommon):
    """NC (B04) y ND (B03) a clientes extranjeros con factura origen B16."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_ncf_sequence('16')
        cls._create_ncf_sequence('04')
        cls._create_ncf_sequence('03')
        cls.export = cls._create_invoice(cls.partner_foreign, post=True)

    def test_origin_is_b16(self):
        self.assertEqual(self.export.l10n_do_ncf_number, 'B1600000001')

    def test_credit_note_to_foreign_customer_gets_b04(self):
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=self.export.ids,
        ).create({'reason': 'Devolución', 'journal_id': self.export.journal_id.id})
        refund = self.env['account.move'].browse(wizard.reverse_moves()['res_id'])
        refund.l10n_do_credit_note_reason = '01'

        refund.action_post()

        self.assertEqual(refund.l10n_do_ncf_number, 'B0400000001')
        self.assertEqual(refund.l10n_do_ncf_origin, 'B1600000001')

    def test_debit_note_to_foreign_customer_gets_b03(self):
        debit = self._create_invoice(
            self.partner_foreign,
            l10n_do_is_debit_note=True,
            l10n_do_debit_note_reason='01',
            l10n_do_debit_origin_move_id=self.export.id,
            l10n_do_debit_ncf_origin=self.export.l10n_do_ncf_number,
        )
        self.assertEqual(debit.l10n_do_ncf_type_id.prefix, 'B03')

        debit.action_post()

        self.assertEqual(debit.l10n_do_ncf_number, 'B0300000001')

    def test_plain_invoice_to_foreign_customer_still_needs_b16(self):
        """La regla de exportación sigue aplicando a la factura normal."""
        invoice = self._create_invoice(self.partner_foreign)
        self.assertEqual(invoice.l10n_do_ncf_type_id.prefix, 'B16')


@tagged('post_install', '-at_install')
class TestDebitNoteTypePriority(NcfCommon):
    """La nota de débito es B03 sea cual sea el tipo de cliente."""

    def _debit_note_prefix(self, partner):
        debit = self._create_invoice(partner, l10n_do_is_debit_note=True)
        return debit.l10n_do_ncf_type_id.prefix

    def test_debit_note_to_foreign_customer_is_b03(self):
        self.assertEqual(self._debit_note_prefix(self.partner_foreign), 'B03')

    def test_debit_note_to_governmental_customer_is_b03(self):
        self.partner_consumer.l10n_do_dgii_tax_payer_type = 'governmental'
        self.assertEqual(self._debit_note_prefix(self.partner_consumer), 'B03')

    def test_debit_note_to_special_regime_customer_is_b03(self):
        self.partner_consumer.l10n_do_dgii_tax_payer_type = 'special_regime'
        self.assertEqual(self._debit_note_prefix(self.partner_consumer), 'B03')


@tagged('post_install', '-at_install')
class TestNcfTypeFrozenAfterNumber(NcfCommon):
    """Con NCF asignado, el tipo de comprobante ya no se recalcula."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_ncf_sequence('01')
        cls._create_ncf_sequence('11')
        cls._create_ncf_sequence('13')
        cls.invoice = cls._create_invoice(cls.partner_taxpayer, post=True)
        cls.informal_vendor = cls.env['res.partner'].create({
            'name': 'Proveedor Informal', 'country_id': cls.country_do.id,
        })

    def _assert_still_b01(self):
        self.env.flush_all()
        self.invoice.invalidate_recordset()
        self.assertEqual(self.invoice.l10n_do_ncf_number, 'B0100000001')
        self.assertEqual(self.invoice.l10n_do_ncf_type_id.prefix, 'B01')

    def test_changing_taxpayer_type_keeps_type_of_numbered_invoice(self):
        self.partner_taxpayer.l10n_do_dgii_tax_payer_type = 'final_consumer'
        self._assert_still_b01()

    def test_changing_to_governmental_keeps_type_of_numbered_invoice(self):
        self.partner_taxpayer.l10n_do_dgii_tax_payer_type = 'governmental'
        self._assert_still_b01()

    def test_changing_country_keeps_type_of_numbered_invoice(self):
        self.partner_taxpayer.country_id = self.env.ref('base.us')
        self._assert_still_b01()

    def test_draft_invoice_becomes_b16_when_customer_turns_foreign(self):
        draft = self._create_invoice(self.partner_taxpayer)
        self.assertEqual(draft.l10n_do_ncf_type_id.prefix, 'B01')

        self.partner_taxpayer.country_id = self.env.ref('base.us')

        self.assertEqual(draft.l10n_do_ncf_type_id.prefix, 'B16')
        self._assert_still_b01()

    def test_draft_invoice_leaves_b16_when_customer_turns_dominican(self):
        draft = self._create_invoice(self.partner_foreign)
        self.assertEqual(draft.l10n_do_ncf_type_id.prefix, 'B16')

        self.partner_foreign.country_id = self.country_do

        self.assertEqual(draft.l10n_do_ncf_type_id.prefix, 'B02')

    def test_changing_vat_keeps_type_of_numbered_invoice(self):
        self.partner_taxpayer.vat = False
        self._assert_still_b01()

    def test_draft_invoice_still_follows_taxpayer_type(self):
        draft = self._create_invoice(self.partner_taxpayer)
        self.assertEqual(draft.l10n_do_ncf_type_id.prefix, 'B01')
        self.partner_taxpayer.l10n_do_dgii_tax_payer_type = 'final_consumer'
        self.assertEqual(draft.l10n_do_ncf_type_id.prefix, 'B02')

    def _post_self_issued_bill(self, fiscal_type):
        bill = self._create_invoice(
            self.informal_vendor, move_type='in_invoice',
            l10n_do_fiscal_type=fiscal_type,
            l10n_do_informal_provider_name='Juan Pérez',
        )
        bill.invoice_line_ids.tax_ids = [Command.clear()]
        bill.action_post()
        return bill

    def test_fiscal_type_of_numbered_b11_cannot_be_changed(self):
        bill = self._post_self_issued_bill('informal')
        self.assertEqual(bill.l10n_do_ncf_number, 'B1100000001')

        with self.assertRaises(UserError):
            bill.l10n_do_fiscal_type = 'fiscal'

        self.assertEqual(bill.l10n_do_fiscal_type, 'informal')
        self.assertEqual(bill.l10n_do_ncf_type_id.prefix, 'B11')

    def test_fiscal_type_of_numbered_b13_cannot_be_changed(self):
        bill = self._post_self_issued_bill('minor_expense')
        self.assertEqual(bill.l10n_do_ncf_number, 'B1300000001')

        with self.assertRaises(UserError):
            bill.l10n_do_fiscal_type = 'informal'

        self.assertEqual(bill.l10n_do_ncf_type_id.prefix, 'B13')

    def test_rewriting_same_fiscal_type_on_numbered_bill_is_allowed(self):
        bill = self._post_self_issued_bill('informal')
        bill.write({'l10n_do_fiscal_type': 'informal'})
        self.assertEqual(bill.l10n_do_ncf_type_id.prefix, 'B11')

    def test_fiscal_type_of_draft_bill_can_be_changed(self):
        bill = self._create_invoice(
            self.informal_vendor, move_type='in_invoice', l10n_do_fiscal_type='informal',
        )
        bill.l10n_do_fiscal_type = 'minor_expense'
        self.assertEqual(bill.l10n_do_ncf_type_id.prefix, 'B13')


@tagged('post_install', '-at_install')
class TestExpenseTypeOnchange(NcfCommon):
    """El tipo de gasto del 606 no se relaciona con bienes/servicios."""

    def _onchange_results(self, bill):
        methods = self.env['account.move']._onchange_methods.get('l10n_do_expense_type', ())
        return [method(bill) for method in methods]

    def test_onchange_decorators_only_use_field_names(self):
        Move = self.env['account.move']
        self.assertFalse([name for name in Move._onchange_methods if name not in Move._fields])

    def test_personnel_expense_with_service_does_not_warn(self):
        service = self.env['product.product'].create({'name': 'Servicio', 'type': 'service'})
        bill = self._create_invoice(self.partner_taxpayer, move_type='in_invoice')
        bill.invoice_line_ids.product_id = service
        bill.l10n_do_expense_type = '01'
        self.assertFalse(any(self._onchange_results(bill)))

    def test_services_and_supplies_expense_with_goods_does_not_warn(self):
        bill = self._create_invoice(self.partner_taxpayer, move_type='in_invoice')
        self.assertTrue(bill.invoice_line_ids.product_id.type != 'service')
        bill.l10n_do_expense_type = '02'
        self.assertFalse(any(self._onchange_results(bill)))


@tagged('post_install', '-at_install')
class TestGovernmentRncPattern(NcfCommon):
    """El onchange y la validación al confirmar usan los mismos prefijos."""

    def _warnings(self, vat, taxpayer_type):
        partner = self.env['res.partner'].create({
            'name': 'Entidad %s' % vat,
            'is_company': True,
            'country_id': self.country_do.id,
            'vat': vat,
        })
        partner.l10n_do_dgii_tax_payer_type = taxpayer_type
        invoice = self._create_invoice(partner)
        onchange = invoice._onchange_validate_fiscal_coherence()
        posting = invoice._validate_fiscal_coherence()
        return bool(onchange), bool(posting.get('warnings'))

    def test_b15_with_government_prefixes_does_not_warn(self):
        for first_eight in ('40100000', '40150000', '40250000', '43000000', '43100000'):
            with self.subTest(prefix=first_eight):
                self.assertEqual(
                    self._warnings(_rnc(first_eight), 'governmental'), (False, False),
                )

    def test_b15_with_company_rnc_warns_in_both(self):
        self.assertEqual(self._warnings(_rnc('13000000'), 'governmental'), (True, True))

    def test_b01_with_government_prefixes_warns_in_both(self):
        for first_eight in ('40150000', '40250000', '43000000', '43100000'):
            with self.subTest(prefix=first_eight):
                self.assertEqual(
                    self._warnings(_rnc(first_eight), 'taxpayer'), (True, True),
                )
