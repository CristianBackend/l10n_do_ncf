# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestExtensionPoints(NcfCommon):
    """Puntos de extensión para un conector de e-CF.

    El conector los sobrescribe por herencia; aquí se simula con patch para
    probarlos sin depender de él.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seq_b01 = cls._create_ncf_sequence('01')
        cls.seq_b02 = cls._create_ncf_sequence('02')
        cls._create_sales_ncf_sequences()

    def _patch_move(self, method, value):
        return patch.object(
            type(self.env['account.move']), method, lambda move: value,
        )

    def _current(self, sequence):
        sequence.invalidate_recordset()
        return sequence.current_number

    # ---------------------------------------------------------------
    # _l10n_do_get_ncf_type_code
    # ---------------------------------------------------------------
    def test_type_code_matches_selected_type(self):
        refund = self._create_refund(
            self.partner_taxpayer, l10n_do_ncf_origin='B0100000001',
        )
        cases = (
            (self._create_invoice(self.partner_consumer), '02'),
            (self._create_invoice(self.partner_taxpayer), '01'),
            (self._create_invoice(self.partner_foreign), '16'),
            (self._create_invoice(self.partner_taxpayer, l10n_do_is_debit_note=True), '03'),
            (refund, '04'),
        )
        for move, code in cases:
            self.assertEqual(move._l10n_do_get_ncf_type_code(), code)
            self.assertEqual(move.l10n_do_ncf_type_id.code, code)

    def test_type_code_of_documents_without_own_ncf_is_false(self):
        bill = self._create_invoice(self.partner_consumer, move_type='in_invoice')
        self.assertFalse(bill._l10n_do_get_ncf_type_code())
        bill.l10n_do_fiscal_type = 'informal'
        self.assertEqual(bill._l10n_do_get_ncf_type_code(), '11')

    def test_overridden_type_code_decides_the_type(self):
        with self._patch_move('_l10n_do_get_ncf_type_code', '31'):
            invoice = self._create_invoice(self.partner_taxpayer)
            self.assertEqual(invoice.l10n_do_ncf_type_id.prefix, 'E31')
            self.assertTrue(invoice.l10n_do_ncf_type_id.is_electronic)

    # ---------------------------------------------------------------
    # _l10n_do_uses_external_numbering
    # ---------------------------------------------------------------
    def test_numbering_is_local_by_default(self):
        invoice = self._create_invoice(self.partner_consumer)
        self.assertFalse(invoice._l10n_do_uses_external_numbering())

    def test_external_numbering_does_not_consume_local_sequence(self):
        with self._patch_move('_l10n_do_uses_external_numbering', True):
            invoice = self._create_invoice(self.partner_consumer, post=True)

        self.assertEqual(invoice.state, 'posted')
        self.assertFalse(invoice.l10n_do_ncf_number)
        self.assertFalse(invoice.l10n_do_ncf_seq_id)
        self.assertNotEqual(invoice.l10n_do_fiscal_status, 'valid')
        self.assertEqual(self._current(self.seq_b02), 0)

    def test_external_numbering_does_not_need_a_local_sequence(self):
        self.seq_b01.unlink()
        with self._patch_move('_l10n_do_uses_external_numbering', True):
            invoice = self._create_invoice(self.partner_taxpayer, post=True)
        self.assertEqual(invoice.state, 'posted')
        self.assertFalse(invoice.l10n_do_ncf_number)

    def test_external_numbering_keeps_an_existing_number(self):
        invoice = self._create_invoice(self.partner_consumer, post=True)
        with self._patch_move('_l10n_do_uses_external_numbering', True):
            invoice._generate_ncf()
        self.assertEqual(invoice.l10n_do_ncf_number, 'B0200000001')

    # ---------------------------------------------------------------
    # _l10n_do_refund_needs_local_sequence (asistente de NC)
    # ---------------------------------------------------------------
    def _reversal_wizard(self, invoice):
        return self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'reason': 'Devolución', 'journal_id': invoice.journal_id.id})

    def test_refund_needs_local_sequence_only_with_ncf(self):
        wizard = self.env['account.move.reversal']
        invoice = self._create_invoice(self.partner_taxpayer)
        self.assertFalse(wizard._l10n_do_refund_needs_local_sequence(invoice))
        invoice.action_post()
        self.assertTrue(wizard._l10n_do_refund_needs_local_sequence(invoice))

    def test_reversal_without_b04_sequence_when_numbered_externally(self):
        invoice = self._create_invoice(self.partner_taxpayer, post=True)
        wizard = self._reversal_wizard(invoice)
        with patch.object(
            type(wizard), '_l10n_do_refund_needs_local_sequence',
            lambda wiz, move: False,
        ):
            action = wizard.reverse_moves()
        refund = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(refund.move_type, 'out_refund')
        self.assertEqual(refund.l10n_do_ncf_origin, invoice.l10n_do_ncf_number)
