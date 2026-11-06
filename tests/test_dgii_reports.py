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
        content = base64.b64decode(wizard.file_data).decode('cp1252')
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

    # ---------------------------------------------------------------
    # Grupo 2: nunca inventar ni poner valores por defecto sin dato
    # ---------------------------------------------------------------
    def _pay(self, move, journal, amount=None):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create({
                'journal_id': journal.id,
                **({'amount': amount} if amount is not None else {}),
            })
        wizard._create_payments()
        move.invalidate_recordset()

    def _row(self, lines, ncf):
        for line in lines[1:]:
            columns = line.split('|')
            if ncf in columns:
                return columns
        self.fail('%s no está en el reporte' % ncf)

    def test_606_no_supplier_id_is_pending_never_zeros(self):
        nobody = self.env['res.partner'].create({'name': 'Sin RNC', 'country_id': self.country_do.id})
        self._bill(nobody, l10n_do_vendor_ncf='B0100000021')
        wizard, lines = self._report('606')
        self.assertNotIn('00000000000', '\n'.join(lines))
        self.assertEqual(self._row(lines, 'B0100000021')[:2], ['', ''])
        self.assertIn('falta el RNC o la cédula del proveedor', wizard.pending_message)

    def test_606_goods_and_services_type_from_the_expense_account(self):
        bill = self._bill(l10n_do_vendor_ncf='B0100000022')
        wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000022')[2], '')
        self.assertIn('falta el tipo de bienes y servicios', wizard.pending_message)
        bill.invoice_line_ids.account_id.l10n_do_606_expense_type = '03'
        _wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000022')[2], '03')
        # El de la factura manda sobre el de la cuenta.
        self._set(bill, l10n_do_expense_type='11')
        _wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000022')[2], '11')

    def test_606_lines_without_product_are_not_assumed_services(self):
        self._bill(l10n_do_vendor_ncf='B0100000023')
        wizard, lines = self._report('606')
        row = self._row(lines, 'B0100000023')
        self.assertEqual(row[7:9], ['', ''])
        self.assertIn('hay líneas sin producto', wizard.pending_message)
        service = self.env['product.product'].create({'name': 'Servicio', 'type': 'service'})
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.supplier.id, 'invoice_date': self.today,
            'l10n_do_vendor_ncf': 'B0100000024',
            'invoice_line_ids': [Command.create({
                'product_id': service.id, 'quantity': 1, 'price_unit': 500.0, 'tax_ids': []})],
        })
        bill.action_post()
        wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000024')[7:10], ['500.00', '', '500.00'])

    def test_606_isr_type_is_never_assumed(self):
        bill = self._bill(retentions=[(self.isr_prof, 1000.0)], l10n_do_vendor_ncf='B0100000025')
        self._pay(bill, self.company_data['default_journal_bank'])
        wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000025')[16], '')
        self.assertIn('falta el tipo de retención de ISR', wizard.pending_message)

    def test_payment_form_comes_from_the_real_payment(self):
        bank = self.company_data['default_journal_bank']
        cash = self.company_data['default_journal_cash']
        # El plan l10n_do ya le pone 02 al banco; aquí se prueba uno sin forma.
        bank.l10n_do_payment_form = False
        cash.l10n_do_payment_form = False
        unpaid = self._bill(l10n_do_vendor_ncf='B0100000031')
        by_bank = self._bill(l10n_do_vendor_ncf='B0100000032')
        by_cash = self._bill(l10n_do_vendor_ncf='B0100000033')
        mixed = self._bill(l10n_do_vendor_ncf='B0100000034')
        self._pay(by_bank, bank)
        self._pay(by_cash, cash)
        self._pay(mixed, cash, amount=400.0)
        self.assertEqual(unpaid._l10n_do_payment_form_code(), '04')
        self.assertFalse(by_bank._l10n_do_payment_form_code())
        self.assertEqual(by_cash._l10n_do_payment_form_code(), '01')
        self.assertEqual(mixed._l10n_do_payment_form_code(), '07')
        wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000032')[22], '')
        self.assertIn('Forma de pago DGII', wizard.pending_message)
        bank.l10n_do_payment_form = '03'
        _wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0100000032')[22], '03')

    def test_607_income_type_is_the_ecf_field(self):
        typed = self._sale(self.partner_taxpayer, l10n_do_ecf_income_type='2')
        untyped = self._sale(self.partner_taxpayer)
        self._set(untyped, l10n_do_ecf_income_type=None)
        wizard, lines = self._report('607')
        self.assertEqual(self._row(lines, typed.l10n_do_ncf_number)[4], '2')
        self.assertEqual(self._row(lines, untyped.l10n_do_ncf_number)[4], '')
        self.assertIn('%s: falta el tipo de ingreso' % untyped.l10n_do_ncf_number,
                      wizard.pending_message)

    def test_607_without_customer_id_is_pending(self):
        large = self._sale(self.partner_consumer, price=300000.0)
        self._set(self.partner_consumer, vat=None)
        wizard, lines = self._report('607')
        self.assertEqual(self._row(lines, large.l10n_do_ncf_number)[:2], ['', ''])
        self.assertIn('falta el RNC, la cédula o el ID del cliente', wizard.pending_message)

    def test_607_payment_columns_from_the_real_payments(self):
        cash = self.company_data['default_journal_cash']
        invoice = self._sale(self.partner_taxpayer, price=1000.0, l10n_do_ecf_income_type='1')
        self._pay(invoice, cash, amount=600.0)
        wizard, lines = self._report('607')
        row = self._row(lines, invoice.l10n_do_ncf_number)
        # 17 efectivo, 18 cheque, 19 tarjeta, 20 crédito
        self.assertEqual(row[16:20], ['600.00', '', '', '400.00'])
        self.assertFalse(wizard.pending_message)

    def _annul(self, invoice, annulment_type='04'):
        wizard = self.env['l10n_do_ncf.invoice.annul.wizard'].with_context(
            active_id=invoice.id).create({
                'annul_reason': 'Error en el cliente', 'action_type': 'annul',
                'annulment_type': annulment_type})
        wizard.action_confirm()
        invoice.invalidate_recordset()

    def test_annul_wizard_asks_the_608_code_and_stores_the_date(self):
        invoice = self._sale(self.partner_taxpayer)
        wizard = self.env['l10n_do_ncf.invoice.annul.wizard'].with_context(
            active_id=invoice.id).create({'annul_reason': 'x', 'action_type': 'annul'})
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self._annul(invoice, '05')
        self.assertEqual(invoice.state, 'cancel')
        self.assertEqual(invoice.l10n_do_annulment_type, '05')
        self.assertEqual(invoice.l10n_do_annulment_date, fields.Date.context_today(invoice))
        _wizard, lines = self._report('608')
        # Casilla 2: fecha de emisión (instructivo 608, septiembre 2020).
        self.assertEqual(lines[1], '%s|%s|05' % (
            invoice.l10n_do_ncf_number, invoice.invoice_date.strftime('%Y%m%d')))

    def test_608_period_by_annulment_date_column_with_issue_date(self):
        """El PERÍODO lo decide la fecha de anulación (Norma General 07-2018,
        Anexo C); la casilla 2 lleva la fecha de emisión del comprobante
        (instructivo 608, septiembre 2020)."""
        from dateutil.relativedelta import relativedelta
        issued = self.today - relativedelta(months=2)
        old = self._sale(self.partner_taxpayer)
        self._set(old, invoice_date=issued)
        self._annul(old)
        self.assertEqual(old.l10n_do_annulment_date, fields.Date.context_today(old))
        # Se reporta en el mes de la anulación...
        wizard, lines = self._report('608')
        self.assertEqual(lines[1], '%s|%s|04' % (old.l10n_do_ncf_number, issued.strftime('%Y%m%d')))
        self.assertFalse(wizard.pending_message)
        # ...y no en el mes en que se emitió.
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': '608',
            'date_from': issued.replace(day=1),
            'date_to': issued.replace(day=1) + relativedelta(months=1, days=-1),
        })
        with self.assertRaises(UserError):
            wizard.action_generate_report()

    def test_608_legacy_annulment_without_data_is_pending(self):
        legacy = self._sale(self.partner_taxpayer)
        self._set(legacy, state='cancel')
        wizard, lines = self._report('608')
        self.assertEqual(lines[1], '%s|%s|' % (
            legacy.l10n_do_ncf_number, legacy.invoice_date.strftime('%Y%m%d')))
        self.assertIn('no tiene fecha de anulación', wizard.pending_message)
        self.assertIn('falta el tipo de anulación', wizard.pending_message)

    def test_txt_formatter_has_no_defaults(self):
        validator = self.env['l10n_do_ncf.dgii.txt.validator']
        line = validator.format_606_line({}).split('|')
        self.assertEqual((line[1], line[2], line[22]), ('', '', ''))
        self.assertEqual(validator.format_607_line({}).split('|')[4], '')

    # ---------------------------------------------------------------
    # Grupo 3: documentos y montos
    # ---------------------------------------------------------------
    def _tax(self, name, amount, use='purchase', **vals):
        return self.env['account.tax'].create({
            'name': name, 'amount': amount, 'amount_type': 'percent',
            'type_tax_use': use, 'company_id': self.company.id, **vals})

    def _line(self, price, taxes=(), **vals):
        return Command.create({'name': 'Línea', 'quantity': 1, 'price_unit': price,
                               'tax_ids': [Command.set([t.id for t in taxes])], **vals})

    def test_606_vendor_credit_and_debit_notes_with_their_modified_ncf(self):
        service = self.env['product.product'].create({'name': 'Servicio', 'type': 'service'})
        lines = lambda price: [self._line(price, product_id=service.id)]  # noqa: E731
        self._bill(l10n_do_vendor_ncf='B0100000041', invoice_line_ids=lines(1000.0))
        refund = self.env['account.move'].create({
            'move_type': 'in_refund', 'partner_id': self.supplier.id, 'invoice_date': self.today,
            'l10n_do_vendor_ncf': 'B0400000041', 'l10n_do_ncf_origin': 'B0100000041',
            'invoice_line_ids': lines(200.0)})
        refund.action_post()
        self._bill(l10n_do_vendor_ncf='B0300000042', l10n_do_is_vendor_debit_note=True,
                   l10n_do_vendor_debit_ncf_origin='B0100000041', invoice_line_ids=lines(1000.0))
        wizard, lines = self._report('606')
        self.assertEqual(self._row(lines, 'B0400000041')[4], 'B0100000041')
        self.assertEqual(self._row(lines, 'B0300000042')[4], 'B0100000041')
        # La nota de crédito resta del total (herramienta 606).
        self.assertAlmostEqual(wizard.total_amount, 1000.0 - 200.0 + 1000.0, places=2)

    def test_606_note_without_modified_ncf_is_pending(self):
        refund = self.env['account.move'].create({
            'move_type': 'in_refund', 'partner_id': self.supplier.id, 'invoice_date': self.today,
            'l10n_do_vendor_ncf': 'B0400000043', 'invoice_line_ids': [self._line(200.0)]})
        refund.action_post()
        wizard, _lines = self._report('606')
        self.assertIn('B0400000043: falta el NCF que modifica la nota', wizard.pending_message)

    def test_606_includes_own_foreign_payments_and_minor_expenses(self):
        """Instructivo 606 (julio 2025) y preguntas frecuentes e-CF 1.2.29:
        B17/E47 y B13/E43 van en el 606 con el RNC del encabezado."""
        foreign = self.env['res.partner'].create({
            'name': 'Foreign Inc.', 'country_id': self.env.ref('base.us').id, 'vat': 'EIN1'})
        isr_ext = self.env['l10n_do_ncf.retention.type'].search([('code', '=', 'ISR_EXT')], limit=1)
        bill = self._bill(foreign, retentions=[(isr_ext, 1000.0)], l10n_do_fiscal_type='exterior',
                          l10n_do_vendor_ncf=False)
        self._set(bill, l10n_do_ncf_number='E470000000001', l10n_do_propina_legal=50.0,
                  l10n_do_itbis_proporcionalidad=10.0)
        wizard, lines = self._report('606')
        row = self._row(lines, 'E470000000001')
        self.assertEqual(row[:2], [RNC_EMPRESA, '1'])
        # Sin ITBIS retenido, proporcionalidad, costo, ISR percibido, ISC,
        # otros ni propina.
        for index in (11, 12, 13, 15, 18, 19, 20, 21):
            self.assertEqual(row[index], '', index)

    def test_606_itbis_to_advance_is_billed_minus_cost(self):
        itbis = self._tax('ITBIS compras 18 %', 18.0)
        bill = self._bill(invoice_line_ids=[self._line(1000.0, [itbis])],
                          l10n_do_vendor_ncf='B0100000044')
        self._set(bill, l10n_do_itbis_proporcionalidad=50.0, l10n_do_itbis_costo=30.0)
        _wizard, lines = self._report('606')
        row = self._row(lines, 'B0100000044')
        # 11 facturado, 13 proporcionalidad, 14 costo, 15 por adelantar
        self.assertEqual([row[10], row[12], row[13], row[14]], ['180.00', '50.00', '30.00', '150.00'])

    def test_606_and_607_taxes_in_their_own_columns(self):
        itbis = self._tax('ITBIS compras 18 %', 18.0)
        isc = self._tax('ISC alcohol', 10.0, dgii_tax_kind='isc')
        tip = self._tax('Propina legal', 10.0, dgii_tax_kind='tip')
        loose = self._tax('Tasa sin clase', 2.0)
        self._bill(invoice_line_ids=[self._line(1000.0, [itbis, isc, tip])],
                   l10n_do_vendor_ncf='B0100000045')
        self._bill(invoice_line_ids=[self._line(1000.0, [loose])], l10n_do_vendor_ncf='B0100000046')
        wizard, lines = self._report('606')
        row = self._row(lines, 'B0100000045')
        self.assertEqual([row[10], row[19], row[20], row[21]], ['180.00', '100.00', '', '100.00'])
        self.assertEqual(self._row(lines, 'B0100000046')[10], '')
        self.assertIn('el impuesto "Tasa sin clase" no tiene "Clase DGII"', wizard.pending_message)

        sale_itbis = self._tax('ITBIS ventas 18 %', 18.0, use='sale')
        sale_tip = self._tax('Propina ventas', 10.0, use='sale', dgii_tax_kind='tip')
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner_taxpayer.id,
            'invoice_date': self.today, 'l10n_do_ecf_income_type': '1',
            'invoice_line_ids': [self._line(1000.0, [sale_itbis, sale_tip])]})
        invoice.action_post()
        _wizard, lines = self._report('607')
        row = self._row(lines, invoice.l10n_do_ncf_number)
        # 8 monto, 9 ITBIS, 14 ISC, 15 otros, 16 propina
        self.assertEqual([row[7], row[8], row[13], row[14], row[15]],
                         ['1000.00', '180.00', '', '', '100.00'])

    def test_ncf_longer_than_allowed_is_an_error_not_cut(self):
        self._bill(l10n_do_vendor_ncf='B0100000047')
        bill = self._bill(l10n_do_vendor_ncf='B0100000048')
        self._set(bill, l10n_do_vendor_ncf='B01000000489')
        wizard, lines = self._report('606')
        body = '\n'.join(lines)
        self.assertNotIn('B0100000048|', body)
        self.assertIn('ERROR: el NCF B01000000489 tiene 12 caracteres', wizard.pending_message)

    def test_607_credit_and_debit_notes(self):
        invoice = self._sale(self.partner_taxpayer, price=1000.0, l10n_do_ecf_income_type='3')
        refund = self.env['account.move'].create({
            'move_type': 'out_refund', 'partner_id': self.partner_taxpayer.id,
            'invoice_date': self.today, 'l10n_do_origin_move_id': invoice.id,
            'l10n_do_ncf_origin': invoice.l10n_do_ncf_number, 'l10n_do_credit_note_reason': '03',
            'invoice_line_ids': [self._line(300.0)]})
        refund.action_post()
        debit = self._sale(self.partner_taxpayer, price=100.0, l10n_do_is_debit_note=True,
                           l10n_do_debit_ncf_origin=invoice.l10n_do_ncf_number,
                           l10n_do_debit_note_reason='01', l10n_do_ecf_income_type='3')
        wizard, lines = self._report('607')
        refund_row = self._row(lines, refund.l10n_do_ncf_number)
        self.assertEqual(refund_row[3], invoice.l10n_do_ncf_number)
        # La nota lleva el tipo de ingreso de la factura y no lleva formas de pago.
        self.assertEqual(refund_row[4], '3')
        self.assertEqual(refund_row[16:23], [''] * 7)
        self.assertEqual(self._row(lines, debit.l10n_do_ncf_number)[3], invoice.l10n_do_ncf_number)
        self.assertNotIn(refund.l10n_do_ncf_number, wizard.pending_message or '')
        self.assertAlmostEqual(wizard.total_amount, 1000.0 - 300.0 + 100.0, places=2)

    def test_607_note_on_small_consumer_invoice_needs_no_id(self):
        """Herramienta 607: una NC/ND sobre una factura de consumo menor de
        RD$250,000 no exige identificación."""
        anonymous = self.env['res.partner'].create({'name': 'Cliente', 'country_id': self.country_do.id})
        small = self._sale(anonymous, price=500.0)
        self.assertEqual(small.l10n_do_ncf_type_id.code, '02')
        refund = self.env['account.move'].create({
            'move_type': 'out_refund', 'partner_id': anonymous.id, 'invoice_date': self.today,
            'l10n_do_origin_move_id': small.id, 'l10n_do_ncf_origin': small.l10n_do_ncf_number,
            'l10n_do_credit_note_reason': '03', 'invoice_line_ids': [self._line(100.0)]})
        refund.action_post()
        wizard, lines = self._report('607')
        self.assertEqual(self._row(lines, refund.l10n_do_ncf_number)[:2], ['', ''])
        self.assertNotIn('falta el RNC', wizard.pending_message or '')

    # ---------------------------------------------------------------
    # Grupo 4: formato igual a la herramienta oficial
    # ---------------------------------------------------------------
    def _raw(self, report_type):
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': report_type,
            'date_from': self.today.replace(day=1), 'date_to': self.today,
        })
        wizard.action_generate_report()
        return wizard, base64.b64decode(wizard.file_data).decode('cp1252')

    def test_files_as_the_official_tools_write_them(self):
        """Herramientas 606 (2025), 607 (2023.1.1) y 608 (2018.2.1): líneas con
        CRLF, sin salto al final, y nombre DGII_F_<formato>_<RNC>_<período>."""
        period = self.today.strftime('%Y%m')
        self._bill(l10n_do_vendor_ncf='B0100000051')
        self._bill(l10n_do_vendor_ncf='B0100000052')
        sale = self._sale(self.partner_taxpayer)
        self._sale(self.partner_taxpayer)
        cancelled = self._sale(self.partner_taxpayer)
        self._annul(cancelled)
        names = {'606': 'TXT', '607': 'txt', '608': 'txt'}
        for report, extension in names.items():
            wizard, content = self._raw(report)
            self.assertEqual(wizard.file_name, 'DGII_F_%s_%s_%s.%s' % (
                report, RNC_EMPRESA, period, extension))
            self.assertNotIn('\n', content.replace('\r\n', ''), report)
            self.assertFalse(content.endswith('\n'), report)
            self.assertGreaterEqual(content.count('\r\n'), 1, report)
        self.assertTrue(sale.l10n_do_ncf_number)

    def test_607_income_type_has_one_digit_like_the_tool(self):
        """Herramienta 607: Mid(celda, 2, 1) sobre "01 - Ingresos ..." = "1"."""
        invoice = self._sale(self.partner_taxpayer, l10n_do_ecf_income_type='6')
        _wizard, lines = self._report('607')
        self.assertEqual(self._row(lines, invoice.l10n_do_ncf_number)[4], '6')

    def test_606_and_608_codes_keep_two_digits_like_the_tool(self):
        """Herramientas 606 y 608: Mid(celda, 1, 2) sobre "01-..." = "01"."""
        invoice = self._sale(self.partner_taxpayer)
        self._annul(invoice, '04')
        _wizard, lines = self._report('608')
        self.assertTrue(lines[1].endswith('|04'))

    def test_annul_notification_names_the_608(self):
        invoice = self._sale(self.partner_taxpayer)
        wizard = self.env['l10n_do_ncf.invoice.annul.wizard'].with_context(
            active_id=invoice.id).create({
                'annul_reason': 'x', 'action_type': 'annul', 'annulment_type': '04'})
        result = wizard.action_confirm()
        self.assertIn('en el 608', result['params']['message'])
        self.assertNotIn('607', result['params']['message'])

    # ---------------------------------------------------------------
    # Decisiones: codificación y retenciones
    # ---------------------------------------------------------------
    def test_files_are_windows_1252(self):
        """Las herramientas oficiales escriben con "Print #" (Windows-1252)."""
        person = self.env['res.partner'].create({
            'name': 'Peña', 'country_id': self.country_do.id, 'vat': CEDULA})
        self._bill(person, l10n_do_vendor_ncf='B0100000061')
        self._sale(self.partner_taxpayer)
        cancelled = self._sale(self.partner_taxpayer)
        self._annul(cancelled)
        for report in ('606', '607', '608'):
            wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
                'company_id': self.company.id, 'report_type': report,
                'date_from': self.today.replace(day=1), 'date_to': self.today})
            wizard.action_generate_report()
            raw = base64.b64decode(wizard.file_data)
            self.assertEqual(raw.decode('cp1252').encode('cp1252'), raw, report)

    def test_character_outside_windows_1252_is_pending_not_replaced(self):
        bill = self._bill(l10n_do_vendor_ncf='B0100000062')
        self._set(bill, l10n_do_vendor_ncf='B01000000Ł2')
        wizard, lines = self._report('606')
        self.assertNotIn('Ł', '\n'.join(lines))
        self.assertNotIn('?', '\n'.join(lines))
        self.assertIn('no existen en Windows-1252 (Ł)', wizard.pending_message)

    def test_withholding_taxes_are_never_itbis(self):
        """La regla "18 % o 16 % = ITBIS" solo mira impuestos positivos: una
        retención (negativa) al 18 % no es ITBIS facturado."""
        itbis = self._tax('ITBIS compras 18 % (r)', 18.0)
        withholding = self._tax('Retención ITBIS 100 % (18)', -18.0)
        bill = self._bill(invoice_line_ids=[self._line(1000.0, [itbis, withholding])],
                          l10n_do_vendor_ncf='B0100000063')
        self.assertAlmostEqual(bill.l10n_do_itbis_facturado, 180.0, places=2)
        wizard, lines = self._report('606')
        row = self._row(lines, 'B0100000063')
        self.assertEqual(row[10], '180.00')
        self.assertNotIn('Retención ITBIS 100 % (18)', wizard.pending_message or '')
