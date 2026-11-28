# -*- coding: utf-8 -*-
"""IR-17 - Resumen de retenciones del periodo.

No es un archivo de la DGII: es el resumen interno con el que el contador
llena la declaracion IR-17 (Retenciones y Retribuciones Complementarias). Lo
que se prueba aqui:

- entran las facturas de compra CON retencion y solo esas; una compra sin
  retenciones no aparece;
- las notas de credito de proveedor no entran (el resumen solo mira
  move_type = in_invoice);
- los montos van en pesos, convertidos con la tasa con la que la factura
  quedo asentada, no con la que tenga la tabla despues;
- los totales del asistente (ISR, ITBIS y total a pagar a la DGII) cuadran
  con las lineas;
- sin facturas con retencion en el periodo, avisa y no genera archivo.
"""
import base64

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NcfCommon, RNC_EMPRESA


@tagged('post_install', '-at_install')
class TestIr17Summary(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = RNC_EMPRESA
        cls.today = fields.Date.today()
        Tax = cls.env['account.tax']

        def tax(name, amount, **vals):
            return Tax.create({
                'name': name, 'amount': amount, 'amount_type': 'percent',
                'type_tax_use': 'purchase', 'company_id': cls.company.id, **vals})

        cls.itbis_18 = tax('ITBIS 18% compras (IR-17)', 18.0, dgii_tax_kind='itbis')
        cls.ret_itbis = tax('-100% ITBIS (IR-17)', -18.0, dgii_retention_type='itbis',
                            dgii_606_bucket='itbis_retenido')
        cls.ret_isr = tax('-10% ISR Honorarios (IR-17)', -10.0, dgii_retention_type='isr',
                          dgii_606_bucket='isr_retenido', dgii_isr_retention_type='02')
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Honorarios SRL', 'is_company': True,
            'country_id': cls.country_do.id, 'vat': RNC_EMPRESA,
        })
        cls._ncf = 200

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
    def _bill(self, taxes, price=1000.0, move_type='in_invoice', post=True, **vals):
        type(self)._ncf += 1
        bill = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.supplier.id,
            'invoice_date': self.today,
            'l10n_do_vendor_ncf': 'B01%08d' % self._ncf,
            'invoice_line_ids': [Command.create({
                'name': 'Honorarios', 'quantity': 1, 'price_unit': price,
                'tax_ids': [Command.set(taxes.ids)],
            })],
            **vals,
        })
        if post:
            bill.action_post()
        return bill

    def _ir17(self):
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': 'ir17',
            'date_from': self.today.replace(day=1), 'date_to': self.today,
        })
        wizard.action_generate_report()
        # El IR-17 se escribe en utf-8, no en cp1252 como los 606/607/608.
        content = base64.b64decode(wizard.file_data).decode('utf-8')
        return wizard, content

    @staticmethod
    def _row(content, ncf):
        """La fila del resumen de un NCF, ya en celdas."""
        for line in content.split('\n'):
            if ncf in line and '|' in line:
                return [cell.strip() for cell in line.split('|')]
        return None

    # ---------------------------------------------------------------
    # Pruebas
    # ---------------------------------------------------------------
    def test_ir17_lists_the_retentions_and_adds_them_up(self):
        """Una compra de honorarios con las dos retenciones."""
        bill = self._bill(self.itbis_18 | self.ret_itbis | self.ret_isr)
        self.assertEqual(bill.l10n_do_total_isr_retention, 100.0)
        self.assertEqual(bill.l10n_do_total_itbis_retention, 180.0)

        wizard, content = self._ir17()
        row = self._row(content, bill.l10n_do_vendor_ncf)
        self.assertTrue(row, 'la factura con retenciones no sale en el IR-17')
        # RNC | proveedor | NCF | fecha | base | ITBIS | ISR ret. | ITBIS ret. | tipo
        self.assertEqual(row[0], RNC_EMPRESA)
        self.assertEqual(row[2], bill.l10n_do_vendor_ncf)
        self.assertEqual(row[3], str(bill.invoice_date))
        self.assertEqual(row[4], '1000.00')
        self.assertEqual(row[5], '180.00')
        self.assertEqual(row[6], '100.00')
        self.assertEqual(row[7], '180.00')
        # Casilla 17 del 606: el tipo de retencion de ISR del impuesto.
        self.assertEqual(row[8], '02')

        self.assertEqual(wizard.record_count, 1)
        self.assertAlmostEqual(wizard.ir17_total_isr, 100.0, places=2)
        self.assertAlmostEqual(wizard.ir17_total_itbis, 180.0, places=2)
        self.assertAlmostEqual(wizard.ir17_total, 280.0, places=2)
        self.assertIn('TOTAL A PAGAR DGII:      RD$ 280.00', content)
        self.assertEqual(wizard.file_name,
                         'IR17_Resumen_%s_%s.txt' % (RNC_EMPRESA,
                                                     self.today.strftime('%Y%m')))

    def test_ir17_leaves_out_what_has_no_retention(self):
        """Una compra sin retenciones no entra; la que si tiene, si."""
        plain = self._bill(self.itbis_18)
        with_ret = self._bill(self.itbis_18 | self.ret_isr)
        wizard, content = self._ir17()
        self.assertIsNone(self._row(content, plain.l10n_do_vendor_ncf))
        self.assertTrue(self._row(content, with_ret.l10n_do_vendor_ncf))
        self.assertEqual(wizard.record_count, 1)
        self.assertAlmostEqual(wizard.ir17_total, 100.0, places=2)

    def test_ir17_leaves_out_supplier_credit_notes(self):
        """El resumen solo mira facturas de compra, no notas de credito."""
        bill = self._bill(self.itbis_18 | self.ret_isr)
        note = self._bill(self.itbis_18 | self.ret_isr, move_type='in_refund')
        self.assertEqual(note.l10n_do_total_isr_retention, 100.0)
        wizard, content = self._ir17()
        self.assertTrue(self._row(content, bill.l10n_do_vendor_ncf))
        self.assertIsNone(self._row(content, note.l10n_do_vendor_ncf))
        self.assertEqual(wizard.record_count, 1)

    def test_ir17_amounts_are_in_pesos_at_the_posted_rate(self):
        """Una compra en dolares se resume en pesos con SU tasa.

        Despues de asentar la factura se cambia la tasa de la tabla: el
        resumen tiene que seguir mostrando los pesos con los que la factura
        quedo registrada, que son los que estan en la contabilidad.
        """
        usd = self.env.ref('base.USD')
        usd.active = True
        Rate = self.env['res.currency.rate']
        Rate.search([('currency_id', '=', usd.id)]).unlink()
        rate = Rate.create({
            'name': self.today, 'currency_id': usd.id,
            'company_id': self.company.id, 'rate': 1.0 / 60.0,
        })
        bill = self._bill(self.ret_isr, price=100.0, currency_id=usd.id)
        self.assertEqual(bill.l10n_do_total_isr_retention, 10.0)
        # La base del ISR (renta presunta del 609) va en la moneda de la
        # factura: 100 USD, no 6,000 pesos. En Odoo 16 la tasa la calcula el
        # modulo, porque el campo del nucleo invoice_currency_rate llego en la
        # 17; sin ese equivalente, confirmar una compra en moneda extranjera
        # con retencion se caia.
        self.assertAlmostEqual(bill._l10n_do_isr_retention_base(), 100.0, places=2)

        # La tabla cambia de tasa; el asiento ya esta hecho.
        rate.rate = 1.0 / 70.0

        _wizard, content = self._ir17()
        row = self._row(content, bill.l10n_do_vendor_ncf)
        self.assertTrue(row)
        # 100 USD de base y 10 USD de ISR, a los 60 pesos por dolar del asiento.
        self.assertEqual(row[4], '6000.00')
        self.assertEqual(row[6], '600.00')

    def test_ir17_without_retentions_says_so_and_writes_nothing(self):
        """Sin retenciones en el periodo: aviso, y no se genera archivo."""
        self._bill(self.itbis_18)
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': 'ir17',
            'date_from': self.today.replace(day=1), 'date_to': self.today,
        })
        with self.assertRaises(UserError) as caught:
            wizard.action_generate_report()
        self.assertIn('No hay facturas con retenciones', str(caught.exception))
        self.assertFalse(wizard.file_data)
