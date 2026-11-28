# -*- coding: utf-8 -*-
"""B12 - Registro Unico de Ingresos: publicar y numerar.

El B12 es el comprobante del "registro unico de ingresos", con el que se
declaran en un solo documento las ventas del dia que no llevan comprobante
una a una (Norma General 07-2018). Publicarlo le asigna su NCF.

Esta ruta no tenia ninguna prueba y estaba rota: leia un campo que no existe
en la secuencia (final_number), asi que action_post() se caia con
AttributeError, y el numero lo calculaba a mano tratando current_number como
"el siguiente" cuando en el resto del modulo es "el ultimo emitido".
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestRegistroUnicoB12(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = cls.partner_taxpayer.vat

    def _registro(self, amount=1000.0, dias=0):
        # Solo cabe un Registro Unico por fecha y compania, asi que cada uno
        # va en un dia distinto.
        return self.env['l10n_do_ncf.registro.unico'].create({
            'company_id': self.company.id,
            'date': fields.Date.today() - timedelta(days=dias),
            'line_ids': [(0, 0, {
                'reference': 'Ventas del dia',
                'date_time': fields.Datetime.now(),
                'amount_untaxed': amount,
                'amount_tax': amount * 0.18,
                'amount_total': amount * 1.18,
                'payment_method': 'cash',
            })],
        })

    def test_posting_a_b12_numbers_it_from_the_sequence(self):
        sequence = self._create_ncf_sequence('12', range_from=1, range_to=5)
        registro = self._registro()
        registro.action_confirm()
        registro.action_post()

        self.assertEqual(registro.state, 'posted')
        self.assertEqual(registro.l10n_do_ncf_number, 'B1200000001')
        self.assertEqual(registro.l10n_do_ncf_seq_id, sequence)
        # El consumo queda apuntado en la secuencia, como en las facturas.
        self.assertEqual(sequence.current_number, 1)
        self.assertEqual(sequence.used_qty, 1)
        self.assertEqual(sequence.available_qty, 4)

    def test_each_b12_takes_the_next_number(self):
        self._create_ncf_sequence('12', range_from=1, range_to=5)
        numeros = []
        for dias in range(3):
            registro = self._registro(dias=dias)
            registro.action_confirm()
            registro.action_post()
            numeros.append(registro.l10n_do_ncf_number)
        self.assertEqual(numeros, ['B1200000001', 'B1200000002', 'B1200000003'])

    def test_a_posted_b12_keeps_its_number(self):
        self._create_ncf_sequence('12', range_from=1, range_to=5)
        registro = self._registro()
        registro.action_confirm()
        registro.action_post()
        numero = registro.l10n_do_ncf_number
        # Volver a publicar no gasta otro NCF (el metodo sale si ya tiene).
        registro._generate_b12_ncf()
        self.assertEqual(registro.l10n_do_ncf_number, numero)

    def test_an_exhausted_b12_sequence_stops_the_posting(self):
        self._create_ncf_sequence('12', range_from=1, range_to=2)
        for dias in range(2):
            registro = self._registro(dias=dias)
            registro.action_confirm()
            registro.action_post()

        registro = self._registro(dias=5)
        registro.action_confirm()
        with self.assertRaises(UserError) as error:
            registro.action_post()
        self.assertIn('agotada', str(error.exception).lower())
        self.assertFalse(registro.l10n_do_ncf_number)

    def test_without_a_b12_sequence_it_says_so(self):
        registro = self._registro()
        registro.action_confirm()
        with self.assertRaises(UserError) as error:
            registro.action_post()
        self.assertIn('No hay secuencia activa para B12', str(error.exception))
