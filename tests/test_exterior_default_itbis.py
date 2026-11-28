# -*- coding: utf-8 -*-
"""Pago al exterior con la configuración REAL de Odoo 16: la compañía tiene
impuesto de compra por defecto.

El resto de las pruebas del módulo trabajan con una compañía SIN impuesto de
compra por defecto (tests/common.py), que es la situación de la 19: un producto
sin impuestos de proveedor da una línea sin impuestos. Aquí se prueba el
recorrido que de verdad hace el contador en 16, donde
account.move.line._get_computed_taxes todavía cae en
company.account_purchase_tax_id (account/models/account_move_line.py:891-908) y
cargar el plan l10n_do deja ahí un ITBIS (account/models/chart_template.py:647):

1. la línea del servicio del proveedor extranjero NACE con ITBIS, así que la
   compra no es todavía un pago al exterior (un B17/E47 no lleva ITBIS);
2. el contador quita ese ITBIS y entonces sí: la compra pasa a "Pago al
   exterior" y se sugiere la retención de ISR del 27 %.

Lo que lo hace posible es que _compute_l10n_do_fiscal_type depende también de
invoice_line_ids.tax_ids en la 16 (en la 19 no hacía falta, porque la línea
nunca nacía con ITBIS).
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import NcfCommon, RNC_EMPRESA


@tagged('post_install', '-at_install')
class TestExteriorWithDefaultPurchaseTax(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig
        cls.company.vat = RNC_EMPRESA
        # La compañía SÍ tiene impuesto de compra por defecto: lo que deja el
        # plan l10n_do al cargarse. common.py lo quita para el resto de las
        # pruebas; aquí se repone a propósito.
        cls.itbis_18 = l10n_do_autoconfig.template_ref(
            cls.env, cls.company, 'tax_18_purch')
        if cls.itbis_18:
            cls.company.account_purchase_tax_id = cls.itbis_18
        cls.exterior_retention = cls.company.l10n_do_exterior_retention_tax_ids
        cls.foreign = cls.env['res.partner'].create({
            'name': 'Proveedor Exterior LLC', 'is_company': True,
            'country_id': cls.env.ref('base.us').id})
        cls.service = cls.env['product.product'].create({
            'name': 'Consultoría remota', 'type': 'service', 'supplier_taxes_id': False})

    def setUp(self):
        super().setUp()
        if not self.itbis_18 or not self.exterior_retention:
            self.skipTest('La compañía de prueba no tiene la plantilla l10n_do')

    @staticmethod
    def _drop_itbis(line):
        """Quita de la línea del formulario los impuestos positivos.

        Es lo que hace el contador: un pago al exterior no lleva ITBIS. Solo
        los positivos, para no tocar las retenciones (negativas).
        """
        for tax in list(line.tax_ids):
            if tax.amount > 0:
                line.tax_ids.remove(id=tax.id)

    def _exterior_form(self, lines=1):
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = self.foreign
        form.invoice_date = fields.Date.today()
        for _i in range(lines):
            with form.invoice_line_ids.new() as line:
                line.product_id = self.service
                line.price_unit = 1000.0
                # (1) nace con el ITBIS que pone Odoo 16
                self.assertEqual(
                    [tax.id for tax in line.tax_ids], self.itbis_18.ids,
                    'En Odoo 16 la línea nace con el impuesto de compra por defecto')
                # (2) el contador lo quita; lo que quede no puede ser ITBIS
                # (puede quedar la retención, que es negativa)
                self._drop_itbis(line)
                self.assertFalse([t for t in line.tax_ids if t.amount > 0])
        return form

    def test_removing_the_default_itbis_makes_it_a_payment_abroad(self):
        """Una línea: al quitar el ITBIS pasa a "Pago al exterior" con ISR 27 %."""
        form = self._exterior_form()
        self.assertEqual(form.l10n_do_purchase_kind, 'exterior')
        bill = form.save()
        self.assertEqual(bill.l10n_do_fiscal_type, 'exterior')
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.exterior_retention,
                         'La retención del pago al exterior se sugiere sola')
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.l10n_do_isr_retenido, 270.0)

    def test_two_lines_both_get_the_retention(self):
        """Dos líneas sin guardar: las dos acaban con la retención de ISR.

        Es lo que arregla el onchange de invoice_line_ids: en 16, al añadir la
        segunda línea el tipo de compra YA era "Pago al exterior", así que no
        había cambio de tipo que disparara la sugerencia y esa línea se quedaba
        sin retención (la factura se confirmaba con 270.00 en vez de 540.00).
        """
        form = self._exterior_form(lines=2)
        self.assertEqual(form.l10n_do_purchase_kind, 'exterior')
        bill = form.save()
        self.assertEqual(len(bill.invoice_line_ids), 2)
        for line in bill.invoice_line_ids:
            self.assertEqual(line.tax_ids, self.exterior_retention, line.name)
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.l10n_do_isr_retenido, 540.0)

    def test_posting_blocks_when_a_line_lost_its_retention(self):
        """Si a una línea se le quita la retención, no se puede confirmar.

        La comprobación al confirmar es por línea, así que no se cuela una
        factura infra-retenida.
        """
        bill = self._exterior_form(lines=2).save()
        bill.invoice_line_ids[1].tax_ids = False
        self.assertEqual(
            bill._l10n_do_exterior_lines_missing_retention(), bill.invoice_line_ids[1])
        with self.assertRaisesRegex(UserError, 'falta la retención de ISR'):
            bill.action_post()
        self.assertEqual(bill.state, 'draft')

    def test_kind_is_not_exterior_while_the_line_keeps_the_itbis(self):
        """Con el ITBIS puesto no es un pago al exterior: un B17 no lleva ITBIS."""
        form = Form(self.env['account.move'].with_context(default_move_type='in_invoice'))
        form.partner_id = self.foreign
        form.invoice_date = fields.Date.today()
        with form.invoice_line_ids.new() as line:
            line.product_id = self.service
            line.price_unit = 1000.0
        self.assertEqual(form.l10n_do_purchase_kind, 'vendor')
        bill = form.save()
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.itbis_18)
        self.assertEqual(bill.l10n_do_fiscal_type, 'fiscal')
