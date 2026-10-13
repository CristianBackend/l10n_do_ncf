# -*- coding: utf-8 -*-
import psycopg2

from odoo import SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.l10n_do_ncf import hooks

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestNcfUniqueIndex(NcfCommon):
    """Índices únicos de NCF e impuestos que crea hooks.py."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_ncf_sequence('02')
        cls.invoice = cls._create_invoice(cls.partner_consumer, post=True)
        cls.vendor_a = cls.env['res.partner'].create({
            'name': 'Proveedor A', 'is_company': True, 'country_id': cls.country_do.id,
        })
        cls.vendor_b = cls.env['res.partner'].create({
            'name': 'Proveedor B', 'is_company': True, 'country_id': cls.country_do.id,
        })

    def _index_names(self):
        self.env.cr.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'account_move'"
        )
        return {row[0] for row in self.env.cr.fetchall()}

    def _force_duplicate(self):
        """Segunda factura con el mismo NCF, saltando el ORM."""
        other = self._create_invoice(self.partner_consumer)
        self.env.cr.execute(
            "UPDATE account_move SET l10n_do_ncf_number = %s WHERE id = %s",
            (self.invoice.l10n_do_ncf_number, other.id),
        )
        return other

    def _bill(self, vendor, **vals):
        return self._create_invoice(vendor, move_type='in_invoice', **vals)

    def _force_duplicate_b11(self, ncf='B1100000001'):
        """Dos compras a proveedores distintos con el mismo B11, saltando el ORM."""
        bills = self._bill(self.vendor_a) + self._bill(self.vendor_b)
        self.env.cr.execute(
            "UPDATE account_move SET l10n_do_ncf_number = %s WHERE id IN %s",
            (ncf, tuple(bills.ids)),
        )
        return bills

    # ---------------------------------------------------------------
    # Índice
    # ---------------------------------------------------------------
    def test_indexes_exist_after_install(self):
        names = self._index_names()
        self.assertIn('unique_ncf_per_company', names)
        self.assertIn('unique_vendor_ncf_per_company', names)
        self.assertIn('idx_ncf_search', names)

    def test_same_ncf_twice_in_company_is_rejected(self):
        other = self._create_invoice(self.partner_consumer)
        with self.assertRaises(psycopg2.errors.UniqueViolation), \
                mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            other.l10n_do_ncf_number = self.invoice.l10n_do_ncf_number
            other.flush_recordset()

    def test_same_ncf_twice_is_rejected_at_sql_level(self):
        with self.assertRaises(psycopg2.errors.UniqueViolation), \
                mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._force_duplicate()

    def test_invoices_without_ncf_do_not_collide(self):
        drafts = (
            self._create_invoice(self.partner_consumer)
            + self._create_invoice(self.partner_consumer)
        )
        drafts.flush_recordset()
        self.assertEqual(drafts.mapped('l10n_do_ncf_number'), [False, False])

    # ---------------------------------------------------------------
    # B11 / B13: los emite la compañía aunque sean compras
    # ---------------------------------------------------------------
    def test_same_b11_twice_is_rejected_even_for_different_vendors(self):
        with self.assertRaises(psycopg2.errors.UniqueViolation),                 mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._force_duplicate_b11()

    def test_same_b13_twice_is_rejected(self):
        with self.assertRaises(psycopg2.errors.UniqueViolation),                 mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._force_duplicate_b11('B1300000001')

    def test_emitted_ncf_is_unique_across_sales_and_purchases(self):
        bill = self._bill(self.vendor_a)
        with self.assertRaises(psycopg2.errors.UniqueViolation),                 mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            bill.l10n_do_ncf_number = self.invoice.l10n_do_ncf_number
            bill.flush_recordset()

    # ---------------------------------------------------------------
    # NCF de proveedor: único por compañía + proveedor
    # ---------------------------------------------------------------
    def test_same_vendor_ncf_for_different_vendors_is_accepted(self):
        bills = (
            self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
            + self._bill(self.vendor_b, l10n_do_vendor_ncf='B0100000123')
        )
        bills.flush_recordset()
        self.assertEqual(
            bills.mapped('l10n_do_vendor_ncf'), ['B0100000123', 'B0100000123'],
        )

    def test_same_vendor_ncf_twice_for_same_vendor_is_rejected(self):
        """Con el índice puesto, la base de datos lo rechaza antes que la
        validación Python, y el usuario recibe un mensaje legible."""
        self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
        with self.assertRaises(psycopg2.errors.UniqueViolation) as error,                 mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
        self.assertIn(
            'proveedor', self.env['account.move']._sql_error_to_message(error.exception),
        )

    def test_python_check_rejects_same_vendor_and_accepts_another(self):
        """La validación Python sola (sin índice) aplica el mismo criterio."""
        self.env.cr.execute('DROP INDEX unique_vendor_ncf_per_company')
        self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')

        self._bill(self.vendor_b, l10n_do_vendor_ncf='B0100000123')
        with self.assertRaises(ValidationError):
            self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')

    def test_python_check_catches_case_variants_the_index_misses(self):
        self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
        self._bill(self.vendor_b, l10n_do_vendor_ncf='b0100000123')
        with self.assertRaises(ValidationError):
            self._bill(self.vendor_a, l10n_do_vendor_ncf='b0100000123')

    def test_vendor_ncf_duplicate_is_checked_on_the_commercial_partner(self):
        contact = self.env['res.partner'].create({
            'name': 'Sucursal de A', 'parent_id': self.vendor_a.id,
        })
        self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
        with self.assertRaises(psycopg2.errors.UniqueViolation),                 mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self._bill(contact, l10n_do_vendor_ncf='B0100000123')

    def test_cancelled_bill_frees_the_vendor_ncf(self):
        bill = self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
        bill.button_cancel()
        other = self._bill(self.vendor_a, l10n_do_vendor_ncf='B0100000123')
        other.flush_recordset()
        self.assertEqual(other.l10n_do_vendor_ncf, 'B0100000123')

    def test_same_vendor_ncf_twice_is_rejected_at_sql_level(self):
        bills = self._bill(self.vendor_a) + self._bill(self.vendor_a)
        with self.assertRaises(psycopg2.errors.UniqueViolation),                 mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.env.cr.execute(
                "UPDATE account_move SET l10n_do_vendor_ncf = 'B0100000123' WHERE id IN %s",
                (tuple(bills.ids),),
            )

    def test_same_vendor_ncf_for_different_vendors_is_accepted_at_sql_level(self):
        bills = self._bill(self.vendor_a) + self._bill(self.vendor_b)
        self.env.cr.execute(
            "UPDATE account_move SET l10n_do_vendor_ncf = 'B0100000123' WHERE id IN %s",
            (tuple(bills.ids),),
        )

    # ---------------------------------------------------------------
    # Idempotencia de hooks.py
    # ---------------------------------------------------------------
    def test_ensure_indexes_is_idempotent(self):
        hooks.ensure_ncf_indexes(self.env.cr)
        hooks.ensure_ncf_indexes(self.env.cr)
        self.assertIn('unique_ncf_per_company', self._index_names())

    def test_duplicates_stop_index_creation_with_clear_error(self):
        self.env.cr.execute('DROP INDEX unique_ncf_per_company')
        other = self._force_duplicate()

        duplicates = hooks.find_duplicate_ncf(self.env.cr)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]['ncf'], self.invoice.l10n_do_ncf_number)
        self.assertEqual(duplicates[0]['ids'], sorted((self.invoice | other).ids))

        with self.assertRaises(UserError) as error, mute_logger('odoo.addons.l10n_do_ncf.hooks'):
            hooks.ensure_ncf_indexes(self.env.cr)

        message = str(error.exception)
        self.assertIn(self.invoice.l10n_do_ncf_number, message)
        self.assertIn(self.invoice.name, message)
        self.assertIn(self.company.name, message)
        self.assertNotIn('unique_ncf_per_company', self._index_names())

    def test_duplicate_b11_is_listed_and_stops_index_creation(self):
        self.env.cr.execute('DROP INDEX unique_ncf_per_company')
        bills = self._force_duplicate_b11()

        duplicates = hooks.find_duplicate_ncf(self.env.cr)
        self.assertEqual([d['ncf'] for d in duplicates], ['B1100000001'])
        self.assertEqual(duplicates[0]['ids'], sorted(bills.ids))

        with self.assertRaises(UserError) as error, mute_logger('odoo.addons.l10n_do_ncf.hooks'):
            hooks.ensure_ncf_indexes(self.env.cr)

        self.assertIn('B1100000001', str(error.exception))
        self.assertNotIn('unique_ncf_per_company', self._index_names())

    def test_sales_only_index_is_replaced(self):
        """Un índice previo que solo cubría ventas se recrea con compras."""
        self.env.cr.execute('DROP INDEX unique_ncf_per_company')
        self.env.cr.execute("""
            CREATE UNIQUE INDEX unique_ncf_per_company
            ON account_move (company_id, l10n_do_ncf_number)
            WHERE l10n_do_ncf_number IS NOT NULL
              AND move_type IN ('out_invoice', 'out_refund')
        """)

        hooks.ensure_ncf_indexes(self.env.cr)

        self.assertIn(
            'in_invoice', hooks._index_definition(self.env.cr, 'unique_ncf_per_company'),
        )

    # ---------------------------------------------------------------
    # Impuestos
    # ---------------------------------------------------------------
    def _configure_taxes(self):
        # Como superusuario, igual que el hook real: recorre todas las
        # compañías dominicanas, también las que el usuario de prueba no ve.
        hooks.configure_vat_and_taxes(self.env(user=SUPERUSER_ID))

    def _exempt_taxes(self):
        return self.env['account.tax'].with_context(active_test=False).search([
            *self.env['account.tax']._check_company_domain(self.company),
            ('dgii_itbis_zero_type', '=', 'exempt'),
        ])

    def test_exempt_taxes_are_classified(self):
        self._configure_taxes()
        exempt = self._exempt_taxes()
        self.assertEqual(set(exempt.mapped('type_tax_use')), {'sale', 'purchase'})
        self.assertEqual(set(exempt.mapped('amount')), {0.0})

    def test_configure_taxes_is_idempotent(self):
        Tax = self.env['account.tax'].with_context(active_test=False)
        self._configure_taxes()
        count = Tax.search_count([])
        exempt = self._exempt_taxes()

        self._configure_taxes()

        self.assertEqual(Tax.search_count([]), count)
        self.assertEqual(self._exempt_taxes(), exempt)

    def test_manual_zero_rated_classification_is_kept(self):
        self._configure_taxes()
        tax = self._exempt_taxes().filtered(lambda t: t.type_tax_use == 'sale')[:1]
        tax.dgii_itbis_zero_type = 'zero_rated'

        self._configure_taxes()

        self.assertEqual(tax.dgii_itbis_zero_type, 'zero_rated')
