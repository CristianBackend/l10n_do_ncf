# -*- coding: utf-8 -*-
"""Formato 609 - Pagos por servicios al exterior.

Fuente: Norma General 07-2018 de la DGII, Anexo D, y la herramienta oficial
"Herramienta de Envio Formato 609.xlsm" (2018.5.0), que escribe los códigos tal
cual ("1", "21") y el país con su código ISO 3166 numérico ("840").
"""
import base64
import importlib.util
import os

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NcfCommon, RNC_EMPRESA


@tagged('post_install', '-at_install')
class TestDgii609(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = RNC_EMPRESA
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Foreign Supplier Inc.', 'is_company': True,
            'country_id': cls.env.ref('base.us').id, 'vat': 'EIN-12-3456789',
            'l10n_do_609_related_party': '0',
        })
        # La retención es el impuesto de la línea (desde 19.0.4).
        cls.isr_ext_tax = cls.env['account.tax'].create({
            'name': '-27% ISR exterior (prueba)', 'amount': -27.0, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id,
            'dgii_retention_type': 'isr', 'dgii_606_bucket': 'isr_retenido',
        })
        cls.today = fields.Date.today()

    def _bill(self, partner=None, retention_base=None, **vals):
        # retention_base: con retención de ISR del 27 % sobre la línea.
        taxes = self.isr_ext_tax if retention_base is not None else self.env['account.tax']
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': (partner or self.supplier).id,
            'invoice_date': self.today,
            'ref': 'INV-001',
            'l10n_do_fiscal_type': 'fiscal',
            'invoice_line_ids': [Command.create({
                'name': 'Licencia de software', 'quantity': 1, 'price_unit': 10000.0,
                'tax_ids': [Command.set(taxes.ids)],
            })],
            **vals,
        })
        bill.action_post()
        return bill

    def _report(self):
        wizard = self.env['l10n_do_ncf.dgii.report.wizard'].create({
            'company_id': self.company.id, 'report_type': '609',
            'date_from': self.today.replace(day=1), 'date_to': self.today,
        })
        wizard.action_generate_report()
        lines = base64.b64decode(wizard.file_data).decode('cp1252').split('\r\n')
        return wizard, lines

    def test_row_with_official_codes(self):
        self._bill(retention_base=10000.0, l10n_do_609_service_type='2',
                   l10n_do_609_service_detail='21')
        wizard, lines = self._report()
        date = self.today.strftime('%Y%m%d')
        self.assertEqual(lines[0], '609|%s|%s|1' % (RNC_EMPRESA, self.today.strftime('%Y%m')))
        self.assertEqual(lines[1], '|'.join([
            'Foreign Supplier Inc.', '2', 'EIN123456789', '840', '2', '21', '0', 'INV-001', date,
            '10000.00', date, '10000.00', '2700.00',
        ]))
        self.assertFalse(wizard.pending_message)

    def test_without_isr_retention_reports_zero_and_warns(self):
        """Nunca se inventa la retención: sin ISR registrado va 0.00."""
        self._bill(l10n_do_609_service_type='8', l10n_do_609_service_detail='84')
        wizard, lines = self._report()
        columns = lines[1].split('|')
        self.assertEqual(columns[10:], ['', '0.00', '0.00'])
        self.assertIn('no tiene retención de ISR registrada', wizard.pending_message)

    def test_missing_data_is_left_empty_and_listed(self):
        partner = self.supplier.copy({'vat': False, 'country_id': self.env.ref('base.cw').id})
        self._bill(partner=partner, retention_base=10000.0)
        wizard, lines = self._report()
        columns = lines[1].split('|')
        self.assertEqual(columns[2:6], ['', '', '', ''])
        for fragment in ('identificación tributaria', 'no está en la lista del 609',
                         'Tipo de Servicio Adquirido', 'Detalle del Servicio Adquirido'):
            self.assertIn(fragment, wizard.pending_message)

    def test_document_number_is_never_the_internal_name(self):
        bill = self._bill(retention_base=10000.0, ref=False, l10n_do_609_service_type='2',
                          l10n_do_609_service_detail='21')
        wizard, lines = self._report()
        self.assertEqual(lines[1].split('|')[7], '')
        self.assertNotIn(bill.name, lines[1])
        self.assertIn('número de documento', wizard.pending_message)

    def test_related_party_comes_from_the_contact(self):
        """Anexo D, casilla 7: 0 no relacionado, 1 relacionado. La herramienta
        609 no la admite en blanco; sin dato queda pendiente, nunca 0."""
        related = self.supplier.copy({'name': 'Casa Matriz Inc.', 'l10n_do_609_related_party': '1'})
        unknown = self.supplier.copy({'name': 'Sin dato Inc.', 'l10n_do_609_related_party': False})
        self._bill(partner=related, retention_base=10000.0, ref='REL-1',
                   l10n_do_609_service_type='2', l10n_do_609_service_detail='21')
        self._bill(partner=unknown, retention_base=10000.0, ref='UNK-1',
                   l10n_do_609_service_type='2', l10n_do_609_service_detail='21')
        wizard, lines = self._report()
        rows = {l.split('|')[7]: l.split('|') for l in lines[1:]}
        self.assertEqual(rows['REL-1'][6], '1')
        self.assertEqual(rows['UNK-1'][6], '')
        self.assertIn('UNK-1: falta si el proveedor es parte relacionada', wizard.pending_message)

    def test_detail_must_belong_to_its_type(self):
        with self.assertRaises(ValidationError):
            self._bill(l10n_do_609_service_type='2', l10n_do_609_service_detail='61')

    def test_reset_clears_pending(self):
        self._bill()
        wizard, _lines = self._report()
        self.assertTrue(wizard.pending_message)
        wizard.action_reset()
        self.assertFalse(wizard.pending_message)

    def test_migration_maps_only_clear_equivalences(self):
        person = self.supplier.copy({'is_company': False, 'name': 'John Smith'})
        bills = {
            old: self._bill(partner=partner, retention_base=1.0)
            for old, partner in [('01', self.supplier), ('02', self.supplier), ('03', self.supplier),
                                 ('04', self.supplier), ('05', self.supplier), ('06', self.supplier)]
        }
        bills['02p'] = self._bill(partner=person, retention_base=1.0)
        for key, bill in bills.items():
            self.env.cr.execute(
                'UPDATE account_move SET l10n_do_exterior_service_type = %s, '
                'l10n_do_609_service_type = NULL, l10n_do_609_service_detail = NULL WHERE id = %s',
                (key[:2], bill.id))
        path = os.path.join(os.path.dirname(__file__), '..', 'migrations', '19.0.3.3.0', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('l10n_do_ncf_mig_609', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.3.2.15')
        self.env.invalidate_all()
        result = {k: (b.l10n_do_609_service_type, b.l10n_do_609_service_detail) for k, b in bills.items()}
        self.assertEqual(result, {
            '01': (False, False),
            '02': ('2', '21'),
            '02p': ('2', '22'),
            '03': ('8', False),
            '04': ('6', False),
            '05': (False, False),
            '06': (False, False),
        })

    def test_name_outside_windows_1252_is_pending_not_replaced(self):
        partner = self.supplier.copy({'name': 'Łódź Software Sp.'})
        self._bill(partner=partner, retention_base=10000.0, l10n_do_609_service_type='2',
                   l10n_do_609_service_detail='21')
        wizard, lines = self._report()
        self.assertEqual(lines[1].split('|')[0], '')
        self.assertIn('no existen en Windows-1252', wizard.pending_message)
