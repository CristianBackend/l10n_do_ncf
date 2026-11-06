# -*- coding: utf-8 -*-
"""Formatos 606, 607 y 608 (Norma General 07-2018, Anexos A, B y C).

Fuentes de cada regla, además de la Norma:
- Preguntas frecuentes de Facturación Electrónica (Generales) de la DGII.
- Instructivos "Llenado y Remisión" 606 (julio 2025), 607 y 608 (septiembre 2020).
- Herramientas oficiales de envío: 606 versión 2025, 607 versión 2023.1.1,
  608 versión 2018.2.1.
"""
import base64

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NcfCommon, RNC_EMPRESA

CEDULA = '00113918205'


@tagged('post_install', '-at_install')
class TestDgiiReports(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = RNC_EMPRESA
        cls._create_sales_ncf_sequences()
        cls.today = fields.Date.today()
        cls.partner_consumer.vat = CEDULA
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Local SRL', 'is_company': True,
            'country_id': cls.country_do.id, 'vat': RNC_EMPRESA,
        })
        RetType = cls.env['l10n_do_ncf.retention.type']
        cls.isr_prof = RetType.search([('code', '=', 'ISR_PROF')], limit=1)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
    def _report(self, report_type):
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': report_type,
            'date_from': self.today.replace(day=1), 'date_to': self.today,
        })
        wizard.action_generate_report()
        content = base64.b64decode(wizard.file_data).decode()
        return wizard, content.replace('\r\n', '\n').split('\n')

    def _sale(self, partner, price=1000.0, **vals):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'invoice_date': self.today,
            'invoice_line_ids': [Command.create({
                'name': 'Venta', 'quantity': 1, 'price_unit': price, 'tax_ids': [],
            })],
            **vals,
        })
        invoice.action_post()
        return invoice

    def _bill(self, partner=None, retentions=(), **vals):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': (partner or self.supplier).id,
            'invoice_date': self.today, 'l10n_do_vendor_ncf': 'B0100000001',
            'invoice_line_ids': [Command.create({
                'name': 'Servicio', 'quantity': 1, 'price_unit': 1000.0, 'tax_ids': [],
            })],
            **vals,
        })
        if retentions:
            bill.l10n_do_retention_ids = [
                Command.create({'retention_type_id': kind.id, 'base_amount': base})
                for kind, base in retentions]
        bill.action_post()
        return bill

    def _set(self, move, **values):
        """Escribe por SQL lo que la interfaz no deja tocar en un asiento
        confirmado (un e-NCF, el estado anulado, un RNC sin validar)."""
        self.env.flush_all()
        table = move._table
        sets = ', '.join('%s = %%s' % k for k in values)
        self.env.cr.execute('UPDATE %s SET %s WHERE id = %%s' % (table, sets),
                            (*values.values(), move.id))
        move.invalidate_recordset()

    # ---------------------------------------------------------------
    # Grupo 1: lo que la DGII rechazaría
    # ---------------------------------------------------------------
    def test_607_excludes_ecf(self):
        """Preguntas frecuentes e-CF 1.4.13: el emisor electrónico no remite
        sus e-CF en el 607."""
        paper = self._sale(self.partner_taxpayer)
        ecf = self._sale(self.partner_taxpayer)
        self._set(ecf, l10n_do_ncf_number='E310000000001')
        _wizard, lines = self._report('607')
        body = '\n'.join(lines[1:])
        self.assertIn(paper.l10n_do_ncf_number, body)
        self.assertNotIn('E310000000001', body)

    def test_607_consumer_invoices_only_from_250k(self):
        """NG 10-18: facturas de consumo en el 607 solo desde RD$250,000.00."""
        small = self._sale(self.partner_consumer, price=249999.99)
        large = self._sale(self.partner_consumer, price=250000.0)
        self.assertEqual(small.l10n_do_ncf_type_id.code, '02')
        _wizard, lines = self._report('607')
        body = '\n'.join(lines[1:])
        self.assertNotIn(small.l10n_do_ncf_number, body)
        self.assertIn(large.l10n_do_ncf_number, body)
        self.assertEqual(lines[0].split('|')[3], '1')

    def test_607_retention_needs_its_date(self):
        """Instructivo 607, casillas 10 y 12: con retención, fecha (casilla 7)."""
        without = self._sale(self.partner_taxpayer, l10n_do_third_party_retention_isr=20.0)
        dated = self._sale(self.partner_taxpayer, l10n_do_third_party_retention_isr=20.0,
                           l10n_do_retention_date=self.today)
        wizard, lines = self._report('607')
        rows = {l.split('|')[2]: l.split('|') for l in lines[1:]}
        self.assertEqual(rows[without.l10n_do_ncf_number][6], '')
        self.assertEqual(rows[dated.l10n_do_ncf_number][6], self.today.strftime('%Y%m%d'))
        self.assertIn(without.l10n_do_ncf_number, wizard.pending_message)
        self.assertNotIn(dated.l10n_do_ncf_number, wizard.pending_message)

    def test_608_excludes_ecf_and_never_sends_an_empty_file(self):
        """Herramienta 608: de 1 a 5,000 registros; sin anulados, declaración
        en cero. Los e-CF no van al 608."""
        ecf = self._sale(self.partner_taxpayer)
        self._set(ecf, l10n_do_ncf_number='E310000000002', state='cancel')
        with self.assertRaises(UserError) as raised:
            self._report('608')
        self.assertIn('Declaración en cero', str(raised.exception))
        paper = self._sale(self.partner_taxpayer)
        self._set(paper, state='cancel')
        _wizard, lines = self._report('608')
        self.assertEqual(lines[0].split('|')[3], '1')
        self.assertTrue(lines[1].startswith(paper.l10n_do_ncf_number + '|'))

    def test_606_id_type_only_rnc_or_cedula(self):
        """Herramienta 606 (2025): tipo 1 (RNC, 9) o 2 (cédula, 11); nunca 3."""
        person = self.env['res.partner'].create({
            'name': 'Persona', 'country_id': self.country_do.id, 'vat': CEDULA})
        odd = self.env['res.partner'].create({'name': 'Raro', 'country_id': self.country_do.id})
        self._set(odd, vat='1234567')
        self._bill(self.supplier, l10n_do_vendor_ncf='B0100000011')
        self._bill(person, l10n_do_vendor_ncf='B0100000012')
        self._bill(odd, l10n_do_vendor_ncf='B0100000013')
        wizard, lines = self._report('606')
        rows = {l.split('|')[3]: l.split('|') for l in lines[1:]}
        self.assertEqual(rows['B0100000011'][1], '1')
        self.assertEqual(rows['B0100000012'][1], '2')
        self.assertEqual(rows['B0100000013'][1], '')
        self.assertIn('no tiene 9 dígitos', wizard.pending_message)

    def test_606_minor_expense_id_type_follows_the_company_id(self):
        self._set(self.company.partner_id, vat=CEDULA)
        self.company.invalidate_recordset()
        self._create_ncf_sequence('13')
        self._bill(self.partner_consumer, l10n_do_fiscal_type='minor_expense',
                   l10n_do_vendor_ncf=False)
        _wizard, lines = self._report('606')
        self.assertEqual(lines[1].split('|')[:2], [CEDULA, '2'])

    def test_606_retention_without_payment_has_no_invented_date(self):
        """Instructivo 606 (julio 2025), casillas 12, 17 y 18: con retención,
        fecha de pago obligatoria; nunca la fecha de la factura."""
        bill = self._bill(retentions=[(self.isr_prof, 1000.0)])
        wizard, lines = self._report('606')
        self.assertEqual(lines[1].split('|')[6], '')
        self.assertIn('no fecha de pago', wizard.pending_message)
        self.assertIn(bill.l10n_do_vendor_ncf, wizard.pending_message)
