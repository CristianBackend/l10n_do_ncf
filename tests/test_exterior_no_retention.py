# -*- coding: utf-8 -*-
"""Pago al exterior (B17/E47) sin retención: productos marcados "Sin
retención en pagos al exterior".

Regla (indicada por el contador): no todo pago al exterior lleva la
retención de ISR del 27 % (DGII, Guía del Contribuyente No. 5, pág. 5;
arts. 297 y 305 del Código Tributario). Por ejemplo, los viáticos de un
viaje fuera del país se registran con el comprobante de pago al exterior,
pero sin retención. Por eso:
- todas las líneas marcadas: no se sugiere y la factura se confirma sin ISR;
- mezcla: se sugiere solo en las líneas sin la casilla;
- la retención se puede poner o quitar a mano en cualquier línea;
- 606: casillas 17 y 18 vacías; 609: ISR 0.00 sin aviso de pendiente.
"""
import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import NcfCommon, RNC_EMPRESA


@tagged('post_install', '-at_install')
class TestExteriorNoRetention(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = RNC_EMPRESA
        cls.ret_ext = cls.env['account.tax'].create({
            'name': '-27% ISR exterior (viáticos)', 'amount': -27.0, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id,
            'dgii_retention_type': 'isr', 'dgii_606_bucket': 'isr_retenido',
            'dgii_isr_retention_type': '03'})
        cls.company.l10n_do_exterior_retention_tax_ids = cls.ret_ext
        Product = cls.env['product.product']
        cls.travel = Product.create({
            'name': 'Viáticos exterior', 'type': 'service', 'supplier_taxes_id': False,
            'l10n_do_no_exterior_retention': True})
        cls.service = Product.create({
            'name': 'Consultoría remota', 'type': 'service', 'supplier_taxes_id': False})
        cls.foreign = cls.env['res.partner'].create({
            'name': 'Hotel Miami LLC', 'is_company': True, 'vat': 'EIN-99',
            'country_id': cls.env.ref('base.us').id})

    def _form_bill(self, products):
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = self.foreign
        form.invoice_date = fields.Date.today()
        form.ref = 'HOTEL-%s' % len(products)
        for product in products:
            with form.invoice_line_ids.new() as line:
                line.product_id = product
                line.price_unit = 1000.0
        return form.save()

    def _line(self, bill, product):
        return bill.invoice_line_ids.filtered(lambda l: l.product_id == product)

    def test_field_defaults_to_unchecked(self):
        self.assertFalse(self.service.l10n_do_no_exterior_retention)

    def test_only_travel_expenses_get_no_retention(self):
        bill = self._form_bill([self.travel])
        self.assertEqual(bill.l10n_do_purchase_kind, 'exterior')
        self.assertFalse(bill.invoice_line_ids.tax_ids)
        self.assertTrue(bill._l10n_do_exterior_without_retention())
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.l10n_do_isr_retenido, 0.0)
        self.assertEqual(bill.amount_total, 1000.0)

    def test_mix_suggests_only_on_unchecked_lines(self):
        bill = self._form_bill([self.travel, self.service])
        self.assertEqual(bill.l10n_do_purchase_kind, 'exterior')
        self.assertFalse(self._line(bill, self.travel).tax_ids)
        self.assertEqual(self._line(bill, self.service).tax_ids, self.ret_ext)
        self.assertFalse(bill._l10n_do_exterior_without_retention())
        bill.action_post()
        self.assertEqual(bill.l10n_do_isr_retenido, 270.0)

    def test_normal_service_still_gets_27(self):
        bill = self._form_bill([self.service])
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.ret_ext)
        self.assertEqual(bill.l10n_do_isr_retenido, 270.0)
        # Sin la retención y sin productos marcados sigue bloqueada.
        bill.invoice_line_ids.tax_ids = False
        with self.assertRaisesRegex(UserError, 'falta la retención de ISR'):
            bill.action_post()

    def test_retention_is_editable_on_any_line(self):
        bill = self._form_bill([self.travel, self.service])
        self._line(bill, self.travel).tax_ids = self.ret_ext
        self._line(bill, self.service).tax_ids = False
        bill.action_post()
        self.assertEqual(bill.l10n_do_isr_retenido, 270.0)

    def test_kind_change_keeps_travel_lines_clean(self):
        bill = self._form_bill([self.travel, self.service])
        form = Form(bill)
        form.l10n_do_purchase_kind = 'minor_expense'
        form.l10n_do_purchase_kind = 'exterior'
        bill = form.save()
        self.assertFalse(self._line(bill, self.travel).tax_ids)
        self.assertEqual(self._line(bill, self.service).tax_ids, self.ret_ext)

    def _report(self, report_type):
        today = fields.Date.today()
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': report_type,
            'date_from': today.replace(day=1), 'date_to': today})
        wizard.action_generate_report()
        content = base64.b64decode(wizard.file_data).decode('cp1252')
        return wizard, content.replace('\r\n', '\n').split('\n')

    def _row(self, lines, ncf):
        for line in lines[1:]:
            columns = line.split('|')
            if ncf in columns:
                return columns
        self.fail('%s no está en el reporte' % ncf)

    def test_606_and_609_without_retention(self):
        bill = self._form_bill([self.travel])
        bill.action_post()
        self.env.flush_all()
        self.env.cr.execute('UPDATE account_move SET l10n_do_ncf_number = %s WHERE id = %s',
                            ('E470000000077', bill.id))
        bill.invalidate_recordset()

        wizard, lines = self._report('606')
        row = self._row(lines, 'E470000000077')
        self.assertEqual(row[0], RNC_EMPRESA)
        self.assertEqual(row[7], '1000.00', 'Monto servicios')
        # 17 tipo de retención ISR y 18 ISR retenido: vacías (sin retención).
        self.assertEqual([row[16], row[17]], ['', ''])
        pending = wizard.pending_message or ''
        self.assertNotIn('tiene retenciones pero no fecha de pago', pending)
        self.assertNotIn('tipo de retención de ISR', pending)

        wizard, lines = self._report('609')
        row = self._row(lines, 'E470000000077')
        # 11 fecha de retención vacía, 12 renta presunta y 13 ISR en 0.00.
        self.assertEqual(row[10:], ['', '0.00', '0.00'])
        pending = wizard.pending_message or ''
        self.assertNotIn('no tiene retención de ISR', pending)
        self.assertNotIn('renta presunta', pending)
