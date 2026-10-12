# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestGenerateNcf(NcfCommon):
    """Generación del número de NCF al confirmar (_generate_ncf)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seq_b02 = cls._create_ncf_sequence('02')
        cls.seq_b01 = cls._create_ncf_sequence('01')

    def test_post_assigns_first_number(self):
        invoice = self._create_invoice(self.partner_consumer, post=True)
        self.assertEqual(invoice.l10n_do_ncf_number, 'B0200000001')
        self.assertEqual(invoice.l10n_do_ncf_seq_id, self.seq_b02)
        self.assertEqual(invoice.l10n_do_fiscal_status, 'valid')

    def test_draft_has_no_number(self):
        invoice = self._create_invoice(self.partner_consumer)
        self.assertFalse(invoice.l10n_do_ncf_number)

    def test_numbers_are_consecutive_and_never_repeat(self):
        invoices = self.env['account.move']
        for _i in range(5):
            invoices += self._create_invoice(self.partner_consumer, post=True)

        numbers = invoices.mapped('l10n_do_ncf_number')
        self.assertEqual(numbers, ['B02%08d' % n for n in range(1, 6)])
        self.assertEqual(len(set(numbers)), 5)

        self.seq_b02.invalidate_recordset()
        self.assertEqual(self.seq_b02.current_number, 5)

    def test_each_type_uses_its_own_sequence(self):
        b02 = self._create_invoice(self.partner_consumer, post=True)
        b01 = self._create_invoice(self.partner_taxpayer, post=True)
        self.assertEqual(b02.l10n_do_ncf_number, 'B0200000001')
        self.assertEqual(b01.l10n_do_ncf_number, 'B0100000001')

    def test_generate_twice_keeps_number_and_does_not_consume(self):
        invoice = self._create_invoice(self.partner_consumer, post=True)
        number = invoice.l10n_do_ncf_number

        invoice._generate_ncf()

        self.assertEqual(invoice.l10n_do_ncf_number, number)
        self.seq_b02.invalidate_recordset()
        self.assertEqual(self.seq_b02.current_number, 1)

    def test_repost_after_draft_keeps_number(self):
        invoice = self._create_invoice(self.partner_consumer, post=True)
        number = invoice.l10n_do_ncf_number

        invoice.button_draft()
        invoice.action_post()

        self.assertEqual(invoice.l10n_do_ncf_number, number)
        self.seq_b02.invalidate_recordset()
        self.assertEqual(self.seq_b02.current_number, 1)

    def test_sequence_starts_at_range_from(self):
        self.seq_b01.unlink()
        self._create_ncf_sequence('01', range_from=500, range_to=600)
        invoice = self._create_invoice(self.partner_taxpayer, post=True)
        self.assertEqual(invoice.l10n_do_ncf_number, 'B0100000500')

    def test_no_sequence_blocks_posting(self):
        self.seq_b01.unlink()
        invoice = self._create_invoice(self.partner_taxpayer)
        with self.assertRaises(UserError):
            invoice.action_post()

    def test_exhausted_sequence_blocks_posting(self):
        self.seq_b01.unlink()
        self._create_ncf_sequence('01', range_from=1, range_to=2)
        self._create_invoice(self.partner_taxpayer, post=True)
        self._create_invoice(self.partner_taxpayer, post=True)

        invoice = self._create_invoice(self.partner_taxpayer)
        with self.assertRaises(UserError):
            invoice.action_post()

    def test_number_and_type_are_locked_once_assigned(self):
        invoice = self._create_invoice(self.partner_consumer, post=True)
        with self.assertRaises(UserError):
            invoice.write({'l10n_do_ncf_number': 'B0200000099'})

    def test_invoice_with_ncf_cannot_be_deleted(self):
        invoice = self._create_invoice(self.partner_consumer, post=True)
        invoice.button_draft()
        with self.assertRaises(UserError):
            invoice.unlink()
