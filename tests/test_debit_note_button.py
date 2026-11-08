# -*- coding: utf-8 -*-
"""Nota de débito desde la factura de cliente confirmada.

Lo que encontró el contador al probar en Odoo.sh: el campo "Factura Origen ND"
ofrecía cualquier asiento (borradores, compras, la propia nota) y, al escribir
el e-NCF, "Crear" fabricaba un asiento vacío; el NCF afectado era de solo
lectura y no se guardaba; la casilla "Es Nota de Débito" se podía marcar en una
factura ya confirmada; y el botón de Odoo (account_debit_note) sacaba la nota
como una factura más (B01/E31).
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestDebitNoteButton(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_ncf_sequence('01')
        cls._create_ncf_sequence('03')
        cls._create_sales_ncf_sequences()
        cls.invoice = cls._create_invoice(cls.partner_taxpayer, post=True)

    def _open_debit_note(self, invoice=None):
        action = (invoice or self.invoice).action_l10n_do_debit_note()
        self.assertEqual(action['res_model'], 'account.move')
        return self.env['account.move'].browse(action['res_id'])

    # ---------------------------------------------------------------
    # Botón "Nota de débito"
    # ---------------------------------------------------------------
    def test_button_opens_prefilled_debit_note(self):
        self.assertTrue(self.invoice.l10n_do_can_debit_note)
        note = self._open_debit_note()
        self.assertEqual(note.state, 'draft')
        self.assertEqual(note.move_type, 'out_invoice')
        self.assertTrue(note.l10n_do_is_debit_note)
        self.assertEqual(note.partner_id, self.invoice.partner_id)
        self.assertEqual(note.journal_id, self.invoice.journal_id)
        self.assertEqual(note.currency_id, self.invoice.currency_id)
        self.assertEqual(note.l10n_do_debit_origin_move_id, self.invoice)
        self.assertEqual(note.l10n_do_debit_ncf_origin, self.invoice.l10n_do_ncf_number)
        self.assertEqual(note.l10n_do_ncf_type_id.prefix, 'B03')
        # El motivo lo elige el usuario.
        self.assertFalse(note.l10n_do_debit_note_reason)

    def test_debit_note_is_seen_from_the_origin(self):
        note = self._open_debit_note()
        self.assertEqual(self.invoice.l10n_do_debit_note_count, 1)
        action = self.invoice.action_l10n_do_view_debit_notes()
        self.assertEqual(action['res_id'], note.id)

    def test_debit_note_from_button_posts_as_b03(self):
        note = self._open_debit_note()
        note.write({
            'l10n_do_debit_note_reason': '01',
            'invoice_line_ids': [(0, 0, {'name': 'Intereses por mora', 'quantity': 1,
                                         'price_unit': 250.0, 'tax_ids': []})],
        })
        note.action_post()
        self.assertEqual(note.l10n_do_ncf_number[:3], 'B03')
        self.assertEqual(self.invoice.l10n_do_fiscal_status, 'debited')

    def test_button_only_on_posted_customer_invoices(self):
        draft = self._create_invoice(self.partner_taxpayer)
        self.assertFalse(draft.l10n_do_can_debit_note)
        with self.assertRaises(UserError):
            draft.action_l10n_do_debit_note()
        note = self._open_debit_note()
        self.assertFalse(note.l10n_do_can_debit_note, 'Una ND no lleva otra ND')

    def test_debit_note_reason_is_required_to_post(self):
        note = self._open_debit_note()
        note.invoice_line_ids = [(0, 0, {'name': 'Cargo', 'quantity': 1, 'price_unit': 100.0})]
        with self.assertRaisesRegex(UserError, 'Motivo ND'):
            note.action_post()

    # ---------------------------------------------------------------
    # Casilla "Es Nota de Débito" y factura origen
    # ---------------------------------------------------------------
    def test_posted_invoice_cannot_become_a_debit_note(self):
        with self.assertRaisesRegex(UserError, 'ya está confirmada'):
            self.invoice.write({'l10n_do_is_debit_note': True})
        self.assertFalse(self.invoice.l10n_do_is_debit_note)

    def test_debit_note_cannot_modify_itself(self):
        note = self._open_debit_note()
        with self.assertRaises(ValidationError):
            note.l10n_do_debit_origin_move_id = note

    def test_origin_field_only_offers_posted_invoices_of_the_customer(self):
        other = self._create_invoice(self.partner_consumer, post=True)
        draft = self._create_invoice(self.partner_taxpayer)
        note = self._open_debit_note()
        domain = note._fields['l10n_do_debit_origin_move_id'].domain
        self.assertIn("('state', '=', 'posted')", domain)
        self.assertIn("('commercial_partner_id', '=', commercial_partner_id)", domain)
        options = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('l10n_do_is_debit_note', '=', False), ('company_id', '=', note.company_id.id),
            ('commercial_partner_id', '=', note.commercial_partner_id.id),
        ])
        self.assertIn(self.invoice, options)
        self.assertNotIn(other, options)
        self.assertNotIn(draft, options)
        self.assertNotIn(note, options)

    def test_invoice_is_found_by_its_ncf(self):
        found = self.env['account.move'].name_search(self.invoice.l10n_do_ncf_number)
        self.assertIn(self.invoice.id, [rid for rid, _name in found])

    def test_form_saves_the_affected_ncf(self):
        """El NCF afectado es de solo lectura en el formulario: se guarda igual."""
        with Form(self.env['account.move'].with_context(default_move_type='out_invoice')) as form:
            form.partner_id = self.partner_taxpayer
            form.l10n_do_is_debit_note = True
            form.l10n_do_debit_origin_move_id = self.invoice
            form.l10n_do_debit_note_reason = '02'
            with form.invoice_line_ids.new() as line:
                line.name = 'Flete adicional'
                line.price_unit = 300.0
        note = form.save()
        self.assertEqual(note.l10n_do_debit_ncf_origin, self.invoice.l10n_do_ncf_number)
        self.assertEqual(note.l10n_do_ncf_type_id.prefix, 'B03')

    def test_affected_ncf_is_taken_from_origin(self):
        note = self._create_invoice(
            self.partner_taxpayer, l10n_do_is_debit_note=True, l10n_do_debit_note_reason='01')
        self.assertFalse(note.l10n_do_debit_ncf_origin)
        note.l10n_do_debit_origin_move_id = self.invoice
        self.assertEqual(note.l10n_do_debit_ncf_origin, self.invoice.l10n_do_ncf_number)
        note.action_post()
        self.assertEqual(note.l10n_do_ncf_number[:3], 'B03')

    # ---------------------------------------------------------------
    # Botón de Odoo (account_debit_note)
    # ---------------------------------------------------------------
    def test_std_debit_note_values_become_dominican_debit_note(self):
        vals = {'debit_origin_id': self.invoice.id, 'move_type': 'out_invoice'}
        self.env['account.move']._l10n_do_debit_vals_from_std(vals)
        self.assertTrue(vals['l10n_do_is_debit_note'])
        self.assertEqual(vals['l10n_do_debit_origin_move_id'], self.invoice.id)
        self.assertEqual(vals['l10n_do_debit_ncf_origin'], self.invoice.l10n_do_ncf_number)

    def test_std_debit_note_wizard_gives_b03(self):
        if 'account.debit.note' not in self.env:
            self.skipTest('account_debit_note no está instalado')
        self.assertTrue(self.invoice.l10n_do_std_debit_note)
        wizard = self.env['account.debit.note'].with_context(
            active_model='account.move', active_ids=self.invoice.ids,
        ).create({'reason': 'Intereses', 'copy_lines': True})
        note = self.env['account.move'].browse(wizard.create_debit()['res_id'])
        self.assertTrue(note.l10n_do_is_debit_note)
        self.assertEqual(note.l10n_do_debit_origin_move_id, self.invoice)
        self.assertEqual(note.l10n_do_ncf_type_id.prefix, 'B03')
        note.l10n_do_debit_note_reason = '01'
        note.action_post()
        self.assertEqual(note.l10n_do_ncf_number[:3], 'B03')
        # Nuestro botón y botón inteligente ceden el sitio a los de Odoo.
        self.assertEqual(self.invoice.l10n_do_debit_note_count, 1)
