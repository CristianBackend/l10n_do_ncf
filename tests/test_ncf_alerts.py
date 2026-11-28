# -*- coding: utf-8 -*-
"""Avisos del Panel NCF sobre las secuencias, y que pasa al agotarse una.

Lo que se prueba:

- el aviso de "pocas secuencias disponibles" salta cuando quedan tantas o
  menos que el umbral de la secuencia (Umbral de Alerta, 50 por defecto), y
  no antes;
- al emitir el ultimo NCF del rango, la secuencia queda agotada, SIGUE
  saliendo en el panel y avisa de que hay que pedir un rango nuevo;
- la siguiente secuencia en cola se usa sola SI esta activa; si esta en
  borrador no se usa y la factura no se confirma. Activarla es manual.
"""
from odoo.exceptions import RedirectWarning, UserError
from odoo.tests import tagged

from .common import NcfCommon


@tagged('post_install', '-at_install')
class TestNcfAlerts(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = cls.partner_taxpayer.vat

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
    def _panel(self):
        return self.env['l10n_do_ncf.dashboard'].get_dashboard_data()

    def _alerts(self, title):
        return [a for a in self._panel()['alerts'] if a['title'] == title]

    def _issue(self, how_many):
        for _ in range(how_many):
            self._create_invoice(self.partner_taxpayer, post=True)

    # ---------------------------------------------------------------
    # Umbral
    # ---------------------------------------------------------------
    def test_warning_fires_when_the_threshold_is_reached(self):
        """Umbral de 3 en un rango de 10: avisa al quedar 3, no antes."""
        sequence = self._create_ncf_sequence('01', range_from=1, range_to=10)
        sequence.warning_threshold = 3

        self._issue(6)
        self.assertEqual(sequence.available_qty, 4)
        self.assertFalse(self._alerts('Pocas secuencias disponibles'),
                         'avisa antes de llegar al umbral')

        self._issue(1)
        self.assertEqual(sequence.available_qty, 3)
        avisos = self._alerts('Pocas secuencias disponibles')
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]['type'], 'warning')
        self.assertIn('Solo quedan 3 NCF', avisos[0]['message'])
        self.assertEqual(avisos[0]['id'], sequence.id)

    def test_threshold_follows_the_sequence_and_not_a_fixed_number(self):
        """El umbral es de cada secuencia: por defecto 50."""
        sequence = self._create_ncf_sequence('01', range_from=1, range_to=60)
        self.assertEqual(sequence.warning_threshold, 50)
        self.assertFalse(self._alerts('Pocas secuencias disponibles'))
        self._issue(10)
        self.assertEqual(sequence.available_qty, 50)
        self.assertTrue(self._alerts('Pocas secuencias disponibles'))

    # ---------------------------------------------------------------
    # Agotada
    # ---------------------------------------------------------------
    def test_exhausted_sequence_stays_in_the_panel_and_warns(self):
        """Al emitir el ultimo NCF: agotada, visible y con su aviso."""
        sequence = self._create_ncf_sequence('01', range_from=1, range_to=3)
        self._issue(3)

        self.assertEqual(sequence.current_number, 3)
        self.assertEqual(sequence.state, 'depleted')
        self.assertEqual(sequence.available_qty, 0)

        panel = self._panel()
        listadas = {row['id'] for row in panel['sequences']}
        self.assertIn(sequence.id, listadas,
                      'una secuencia agotada no puede desaparecer del panel')
        fila = next(row for row in panel['sequences'] if row['id'] == sequence.id)
        self.assertEqual(fila['used'], 3)
        self.assertEqual(fila['available'], 0)

        avisos = [a for a in panel['alerts'] if a['title'] == 'Secuencia agotada']
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]['type'], 'danger')
        self.assertIn('rango 1-3', avisos[0]['message'])
        self.assertIn('Solicite un rango nuevo', avisos[0]['message'])
        # Y no se duplica con el de "pocas disponibles".
        self.assertFalse([a for a in panel['alerts']
                          if a['title'] == 'Pocas secuencias disponibles'])

    # ---------------------------------------------------------------
    # La siguiente en cola
    # ---------------------------------------------------------------
    def test_the_next_active_sequence_is_used_on_its_own(self):
        """Con dos secuencias ACTIVAS no hay que hacer nada a mano."""
        first = self._create_ncf_sequence('01', range_from=1, range_to=2)
        second = self._create_ncf_sequence('01', range_from=101, range_to=200)
        self.assertEqual(second.state, 'active')

        invoice = self._create_invoice(self.partner_taxpayer, post=True)
        # El generador coge la secuencia ACTIVA de id mas alto con numeros
        # libres: la ultima registrada, no la mas antigua.
        self.assertEqual(invoice.l10n_do_ncf_number, 'B0100000101')
        self.assertEqual(invoice.l10n_do_ncf_seq_id, second)
        self.assertEqual(first.current_number, 0)

    def test_a_draft_sequence_is_not_used_and_posting_stops(self):
        """La siguiente en cola hay que ACTIVARLA: en borrador no se usa."""
        first = self._create_ncf_sequence('01', range_from=1, range_to=2)
        queued = self.env['l10n_do_ncf.sequence'].create({
            'ncf_type_id': self._ncf_type('01').id,
            'company_id': self.company.id,
            'range_from': 101, 'range_to': 200,
        })
        self.assertEqual(queued.state, 'draft')

        self._issue(2)
        self.assertEqual(first.state, 'depleted')

        invoice = self._create_invoice(self.partner_taxpayer)
        with self.assertRaises(UserError) as error:
            invoice.action_post()
        self.assertIn('No hay secuencias disponibles', str(error.exception))
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(queued.current_number, 0)

        # Activada, la misma factura se confirma y numera sin tocar nada mas.
        queued.action_activate()
        invoice.action_post()
        self.assertEqual(invoice.l10n_do_ncf_number, 'B0100000101')

    def test_without_any_sequence_the_panel_sends_you_to_register_one(self):
        """Sin ninguna secuencia del tipo: aviso con boton, no "agotada"."""
        invoice = self._create_invoice(self.partner_taxpayer)
        with self.assertRaises(RedirectWarning) as error:
            invoice.action_post()
        self.assertEqual(error.exception.args[1]['res_model'], 'l10n_do_ncf.sequence')
