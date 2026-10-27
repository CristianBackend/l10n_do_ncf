# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestCreditDebitOrigin(NcfCommon):
    """NCF afectado en notas de crédito (B04) y de débito (B03)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_ncf_sequence('01')
        cls._create_ncf_sequence('03')
        cls.seq_b04 = cls._create_ncf_sequence('04')
        cls._create_sales_ncf_sequences()
        cls.invoice = cls._create_invoice(cls.partner_taxpayer, post=True)

    def _reverse(self, invoice):
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({
            'reason': 'Devolución',
            'journal_id': invoice.journal_id.id,
        })
        action = wizard.reverse_moves()
        return self.env['account.move'].browse(action['res_id'])

    # ---------------------------------------------------------------
    # Notas de crédito
    # ---------------------------------------------------------------
    def test_credit_note_without_origin_can_be_drafted_but_not_posted(self):
        refund = self._create_refund(self.partner_taxpayer)
        self.assertEqual(refund.state, 'draft')
        refund.l10n_do_credit_note_reason = '01'
        with self.assertRaises(UserError):
            refund.action_post()

    def test_credit_note_with_typed_origin_is_accepted(self):
        refund = self._create_refund(
            self.partner_taxpayer, l10n_do_ncf_origin='B0100000001',
        )
        self.assertEqual(refund.l10n_do_ncf_origin, 'B0100000001')

    def test_reversal_wizard_sets_origin(self):
        refund = self._reverse(self.invoice)

        self.assertEqual(refund.move_type, 'out_refund')
        self.assertEqual(refund.l10n_do_ncf_origin, self.invoice.l10n_do_ncf_number)
        self.assertEqual(refund.l10n_do_origin_move_id, self.invoice)
        self.assertEqual(refund.l10n_do_ncf_type_id.prefix, 'B04')
        self.assertFalse(refund.l10n_do_ncf_number, 'El B04 se asigna al confirmar')

    def test_credit_note_requires_reason_to_post(self):
        refund = self._reverse(self.invoice)
        with self.assertRaises(UserError):
            refund.action_post()

    def test_full_credit_note_gets_b04_and_annuls_origin(self):
        refund = self._reverse(self.invoice)
        refund.l10n_do_credit_note_reason = '01'
        refund.action_post()

        self.assertEqual(refund.l10n_do_ncf_number, 'B0400000001')
        self.assertEqual(refund.l10n_do_ncf_origin, 'B0100000001')
        self.assertEqual(self.invoice.l10n_do_fiscal_status, 'annulled')
        self.assertEqual(self.invoice.l10n_do_credited_amount, self.invoice.amount_total)

    def test_partial_credit_note_marks_origin_partial(self):
        refund = self._reverse(self.invoice)
        refund.l10n_do_credit_note_reason = '04'
        refund.invoice_line_ids[0].price_unit = 100.0
        refund.action_post()

        self.assertEqual(self.invoice.l10n_do_fiscal_status, 'partial_credit')

    def test_reversal_needs_b04_sequence(self):
        self.seq_b04.unlink()
        with self.assertRaises(UserError):
            self._reverse(self.invoice)

    # ---------------------------------------------------------------
    # Notas de débito
    # ---------------------------------------------------------------
    def test_debit_note_without_origin_cannot_be_posted(self):
        debit = self._create_invoice(
            self.partner_taxpayer,
            l10n_do_is_debit_note=True,
            l10n_do_debit_note_reason='01',
        )
        with self.assertRaises(UserError):
            debit.action_post()

    def test_debit_note_without_reason_cannot_be_posted(self):
        debit = self._create_invoice(
            self.partner_taxpayer,
            l10n_do_is_debit_note=True,
            l10n_do_debit_origin_move_id=self.invoice.id,
            l10n_do_debit_ncf_origin=self.invoice.l10n_do_ncf_number,
        )
        with self.assertRaises(UserError):
            debit.action_post()

    def test_debit_note_gets_b03_and_marks_origin(self):
        debit = self._create_invoice(
            self.partner_taxpayer,
            l10n_do_is_debit_note=True,
            l10n_do_debit_note_reason='01',
            l10n_do_debit_origin_move_id=self.invoice.id,
            l10n_do_debit_ncf_origin=self.invoice.l10n_do_ncf_number,
        )
        debit.action_post()

        self.assertEqual(debit.l10n_do_ncf_number, 'B0300000001')
        self.assertEqual(debit.l10n_do_debit_ncf_origin, 'B0100000001')
        self.assertEqual(self.invoice.l10n_do_fiscal_status, 'debited')
