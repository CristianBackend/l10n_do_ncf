# -*- coding: utf-8 -*-
"""Panel NCF: las estadisticas de consumo de cada secuencia.

El consumo lo calcula la secuencia (used_qty). current_number es el ULTIMO
numero emitido y vale 0 mientras no se emita ninguno, asi que no es
"current_number - range_from": una secuencia recien activada con rango 1-500
mostraba "-1 / 500" consumidos en el panel, y una con un NCF emitido mostraba
uno de menos.
"""
from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestDashboardSequenceStats(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = cls.partner_taxpayer.vat
        cls.sequence = cls._create_ncf_sequence('01', range_from=1, range_to=500)

    def _stats(self):
        """La fila de esta secuencia en los datos del panel."""
        data = self.env['l10n_do_ncf.dashboard'].get_dashboard_data()
        rows = {row['id']: row for row in data['sequences']}
        self.assertIn(self.sequence.id, rows)
        return rows[self.sequence.id]

    def test_a_freshly_activated_sequence_has_nothing_used(self):
        """Lo que se veia como "-1 / 500": sin emitir, el consumo es 0."""
        self.assertEqual(self.sequence.state, 'active')
        self.assertEqual(self.sequence.current_number, 0)
        self.assertEqual(self.sequence.used_qty, 0)
        self.assertEqual(self.sequence.usage_percent, 0.0)
        stats = self._stats()
        self.assertEqual(stats['used'], 0)
        self.assertEqual(stats['available'], 500)
        self.assertEqual(stats['total'], 500)

    def test_each_issued_ncf_counts_as_one_used(self):
        """Con el primer NCF emitido: 1 consumido y 499 disponibles."""
        invoice = self._create_invoice(self.partner_taxpayer, post=True)
        self.assertEqual(invoice.l10n_do_ncf_number, 'B0100000001')
        self.assertEqual(self.sequence.current_number, 1)
        self.assertEqual(self.sequence.used_qty, 1)
        stats = self._stats()
        self.assertEqual(stats['used'], 1)
        self.assertEqual(stats['available'], 499)
        self.assertEqual(stats['used'] + stats['available'], stats['total'])
        # 1 de 500 = 0.2 %. El numero lo escribe el generador por SQL (por el
        # bloqueo de concurrencia), asi que esto comprueba ademas que los
        # campos guardados que dependen de current_number se recalculan: sin
        # eso, el porcentaje y el semaforo del panel se quedan congelados.
        self.assertAlmostEqual(self.sequence.usage_percent, 0.2, places=4)
        self.assertEqual(self.sequence.traffic_light, 'green')

    def test_used_and_available_always_add_up_to_the_range(self):
        """Tres NCF emitidos, y en un rango que no empieza en 1."""
        for _ in range(3):
            self._create_invoice(self.partner_taxpayer, post=True)
        self.assertEqual(self.sequence.used_qty, 3)
        self.assertEqual(self.sequence.available_qty, 497)

        other = self._create_ncf_sequence('02', range_from=101, range_to=200)
        self.assertEqual(other.used_qty, 0)
        self.assertEqual(other.available_qty, 100)
        other.current_number = 105
        self.assertEqual(other.used_qty, 5)
        self.assertEqual(other.used_qty + other.available_qty, 100)
