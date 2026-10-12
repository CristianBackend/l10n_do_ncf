# -*- coding: utf-8 -*-
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

from .common import NcfTestMixin


@tagged('post_install', '-at_install')
class TestPosNcf(NcfTestMixin, CommonPosTest):
    """Confirmación desde el POS: el POS postea con _post(), no action_post()."""

    @classmethod
    @CommonPosTest.setup_country('do')
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_ncf_data()
        cls.seq_b02 = cls._create_ncf_sequence('02')
        cls.seq_b01 = cls._create_ncf_sequence('01')
        cls.seq_b04 = cls._create_ncf_sequence('04')
        cls.pos_config_usd.write({
            'l10n_do_ncf_enabled': True,
            'l10n_do_ncf_sequence_id': cls.seq_b02.id,
            'l10n_do_ncf_fiscal_sequence_id': cls.seq_b01.id,
        })

    def _pos_order(self, partner=False, to_invoice=False, refund=False):
        data = {
            'order_data': {
                'partner_id': partner.id if partner else False,
                'to_invoice': to_invoice,
            },
            'line_data': [
                {'product_id': self.ten_dollars_no_tax.product_variant_id.id},
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id, 'amount': 10},
            ],
        }
        if refund:
            data['refund_data'] = [
                {'payment_method_id': self.bank_payment_method.id, 'amount': -10},
            ]
        return self.create_backend_pos_order(data)

    def _current(self, sequence):
        sequence.invalidate_recordset()
        return sequence.current_number

    def test_paid_order_without_invoice_gets_b02(self):
        order, _refund = self._pos_order()

        self.assertEqual(order.state, 'paid')
        self.assertEqual(order.l10n_do_ncf_number, 'B0200000001')
        self.assertEqual(order.l10n_do_ncf_type, 'B02')
        self.assertEqual(order.l10n_do_ncf_seq_id, self.seq_b02)
        self.assertFalse(order.account_move)

    def test_invoiced_order_shares_its_ncf_with_the_invoice(self):
        order, _refund = self._pos_order(partner=self.partner_consumer, to_invoice=True)
        invoice = order.account_move

        self.assertTrue(invoice, 'La orden debe quedar facturada')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(order.l10n_do_ncf_number, 'B0200000001')
        self.assertEqual(invoice.l10n_do_ncf_number, order.l10n_do_ncf_number)
        self.assertEqual(invoice.l10n_do_ncf_type_id.prefix, 'B02')
        self.assertEqual(self._current(self.seq_b02), 1, 'Una venta consume un solo NCF')

    def test_taxpayer_order_uses_b01_sequence(self):
        order, _refund = self._pos_order(partner=self.partner_taxpayer, to_invoice=True)

        self.assertEqual(order.l10n_do_ncf_number, 'B0100000001')
        self.assertEqual(order.account_move.l10n_do_ncf_number, 'B0100000001')
        self.assertEqual(order.account_move.l10n_do_ncf_type_id.prefix, 'B01')
        self.assertEqual(self._current(self.seq_b02), 0)

    def test_consecutive_orders_do_not_repeat_ncf(self):
        orders = self.env['pos.order']
        for _i in range(3):
            orders += self._pos_order(partner=self.partner_consumer, to_invoice=True)[0]

        self.assertEqual(
            orders.mapped('l10n_do_ncf_number'),
            ['B0200000001', 'B0200000002', 'B0200000003'],
        )
        self.assertEqual(
            orders.account_move.mapped('l10n_do_ncf_number'),
            orders.mapped('l10n_do_ncf_number'),
        )

    def test_invoiced_refund_gets_b04_with_origin(self):
        order, refund = self._pos_order(
            partner=self.partner_consumer, to_invoice=True, refund=True,
        )
        credit_note = refund.account_move

        self.assertTrue(credit_note, 'La devolución debe generar nota de crédito')
        self.assertEqual(credit_note.move_type, 'out_refund')
        self.assertEqual(credit_note.l10n_do_ncf_number, 'B0400000001')
        self.assertEqual(credit_note.l10n_do_ncf_origin, order.l10n_do_ncf_number)
        self.assertEqual(credit_note.l10n_do_credit_note_reason, '03')
        # La orden de devolución refleja el B04 para el recibo térmico
        self.assertEqual(refund.l10n_do_ncf_number, 'B0400000001')
        self.assertEqual(refund.l10n_do_ncf_origin, order.l10n_do_ncf_number)
        self.assertEqual(self._current(self.seq_b02), 1, 'La devolución no consume B02')

    def test_ncf_disabled_pos_does_not_consume(self):
        self.pos_config_usd.l10n_do_ncf_enabled = False
        order, _refund = self._pos_order()

        self.assertFalse(order.l10n_do_ncf_number)
        self.assertEqual(self._current(self.seq_b02), 0)
