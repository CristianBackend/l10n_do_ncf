# -*- coding: utf-8 -*-
from lxml import etree

from odoo.tests import Form, tagged

from .common import NcfCommon

DEBIT_NOTE_FIELDS = (
    'l10n_do_is_debit_note',
    'l10n_do_debit_note_reason',
    'l10n_do_debit_origin_move_id',
    'l10n_do_debit_ncf_origin',
)


@tagged('post_install', '-at_install')
class TestMoveFormView(NcfCommon):
    """El formulario de factura lleva dos vistas heredadas del módulo.

    Compartieron id y la segunda sobrescribía a la primera: la pestaña
    "Datos Fiscales", con los campos de nota de débito, no llegaba a la
    interfaz.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seq_b01 = cls._create_ncf_sequence('01')
        cls.seq_b03 = cls._create_ncf_sequence('03')
        cls.header_view = cls.env.ref('l10n_do_ncf.view_move_form_ncf')
        cls.tabs_view = cls.env.ref('l10n_do_ncf.view_move_form_ncf_fiscal_data')

    def _form_arch(self):
        view = self.env['account.move'].get_view(
            self.env.ref('account.view_move_form').id, 'form',
        )
        return etree.fromstring(view['arch'])

    def test_each_view_has_its_own_record(self):
        base = self.env.ref('account.view_move_form')
        self.assertNotEqual(self.header_view, self.tabs_view)
        for view in self.header_view + self.tabs_view:
            self.assertTrue(view.active)
            self.assertEqual(view.inherit_id, base)
        # Cada una conserva lo suyo.
        self.assertIn('fiscal_rd_group', self.header_view.arch_db)
        self.assertNotIn('fiscal_data', self.header_view.arch_db)
        self.assertIn('fiscal_data', self.tabs_view.arch_db)

    def test_fiscal_data_tab_has_the_debit_note_fields(self):
        arch = self._form_arch()
        pages = arch.xpath("//page[@name='fiscal_data']")
        self.assertEqual(len(pages), 1, 'Falta la pestaña "Datos Fiscales"')
        for field_name in DEBIT_NOTE_FIELDS:
            self.assertTrue(
                pages[0].xpath(".//field[@name='%s']" % field_name),
                'Falta %s en la pestaña "Datos Fiscales"' % field_name,
            )

    def test_purchase_tab_has_the_exchange_rate(self):
        arch = self._form_arch()
        pages = arch.xpath("//page[@name='fiscal_606']")
        self.assertEqual(len(pages), 1, 'Falta la pestaña "Datos Fiscales (606)"')
        self.assertTrue(pages[0].xpath(".//field[@name='l10n_do_exchange_rate']"))

    def test_views_do_not_repeat_each_other(self):
        arch = self._form_arch()
        # Lo que ya mostraba la interfaz sigue estando una sola vez.
        self.assertEqual(len(arch.xpath("//group[@name='fiscal_rd_group']")), 1)
        self.assertEqual(len(arch.xpath("//page[@name='retentions_page']")), 1)
        self.assertFalse(arch.xpath("//page[@name='retentions']"))
        outside_tabs = "//field[@name='%s'][not(ancestor::page)]"
        self.assertEqual(len(arch.xpath(outside_tabs % 'l10n_do_ncf_required')), 1)
        self.assertEqual(len(arch.xpath(outside_tabs % 'l10n_do_vendor_ncf')), 1)
        # Un solo banner de NCF: el de la vista de cabecera.
        self.assertEqual(len(arch.xpath("//div[hasclass('alert-success')]")), 1)

    def test_debit_note_can_be_created_from_the_form(self):
        """Form falla si el campo no está en la vista o no se puede editar."""
        origin = self._create_invoice(self.partner_taxpayer, post=True)

        move_form = Form(self.env['account.move'].with_context(default_move_type='out_invoice'))
        move_form.partner_id = self.partner_taxpayer
        move_form.l10n_do_is_debit_note = True
        move_form.l10n_do_debit_note_reason = '01'
        move_form.l10n_do_debit_origin_move_id = origin
        debit = move_form.save()

        self.assertTrue(debit.l10n_do_is_debit_note)
        self.assertEqual(debit.l10n_do_debit_note_reason, '01')
        self.assertEqual(debit.l10n_do_debit_origin_move_id, origin)
        self.assertEqual(debit.l10n_do_ncf_type_id.prefix, 'B03')

    def test_plain_invoice_and_refund_forms_still_save(self):
        """Los campos repetidos entre cabecera y pestaña no bloquean guardar."""
        invoice_form = Form(self.env['account.move'].with_context(default_move_type='out_invoice'))
        invoice_form.partner_id = self.partner_taxpayer
        invoice = invoice_form.save()
        self.assertEqual(invoice.l10n_do_ncf_type_id.prefix, 'B01')

        origin = self._create_invoice(self.partner_taxpayer, post=True)
        refund_form = Form(self.env['account.move'].with_context(default_move_type='out_refund'))
        refund_form.partner_id = self.partner_taxpayer
        refund_form.l10n_do_origin_move_id = origin
        refund_form.l10n_do_credit_note_reason = '03'
        refund = refund_form.save()
        self.assertEqual(refund.l10n_do_ncf_type_id.prefix, 'B04')

        bill_form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        bill_form.partner_id = self.partner_taxpayer
        bill_form.save()
