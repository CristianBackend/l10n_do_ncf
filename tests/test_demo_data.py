# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDemoData(TransactionCase):
    """Carga de los datos demo de contabilidad en una compañía dominicana."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Compañía Demo RD',
            'country_id': cls.env.ref('base.do').id,
            'currency_id': cls.env.ref('base.DOP').id,
        })
        cls.env.user.company_ids |= cls.company

    def _skip_without_demo(self):
        if not self.env.ref('base.res_partner_12', raise_if_not_found=False):
            self.skipTest('Base sin datos demo')

    def _load_demo(self):
        self.env['account.chart.template'].with_company(self.company).try_loading(
            'do', self.company, install_demo=True,
        )
        return self.env['account.move'].search([
            ('company_id', '=', self.company.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
        ])

    def test_demo_invoices_are_posted_with_ncf(self):
        self._skip_without_demo()

        with self.assertNoLogs('odoo.addons.account.demo.account_demo', 'ERROR'), \
                self.assertNoLogs('odoo.addons.account.models.chart_template', 'ERROR'):
            moves = self._load_demo()

        self.assertTrue(moves)
        self.assertEqual(set(moves.mapped('state')), {'posted'})
        self.assertTrue(all(moves.mapped('l10n_do_ncf_number')))
        numbers = moves.mapped('l10n_do_ncf_number')
        self.assertEqual(len(numbers), len(set(numbers)))
        refunds = moves.filtered(lambda m: m.move_type == 'out_refund')
        self.assertTrue(refunds)
        self.assertTrue(all(refunds.mapped('l10n_do_ncf_origin')))

    def test_demo_sequences_only_for_types_in_use(self):
        self._skip_without_demo()

        moves = self._load_demo()

        sequences = self.env['l10n_do_ncf.sequence'].search([
            ('company_id', '=', self.company.id),
        ])
        self.assertEqual(
            set(sequences.mapped('prefix')),
            set(moves.mapped('l10n_do_ncf_type_id.prefix')),
        )
        self.assertEqual(set(sequences.mapped('state')), {'active'})

    def test_no_sequences_without_demo_load(self):
        """Cargar el plan sin demo no crea secuencias."""
        self.env['account.chart.template'].with_company(self.company).try_loading(
            'do', self.company, install_demo=False,
        )
        self.assertFalse(self.env['l10n_do_ncf.sequence'].search([
            ('company_id', '=', self.company.id),
        ]))
