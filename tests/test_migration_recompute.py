# -*- coding: utf-8 -*-
"""Migracion 19.0.4.2.10: poner al dia los campos guardados de las secuencias.

El numero de una secuencia se escribe por SQL (el bloqueo de concurrencia lo
necesita) y el ORM no se enteraba, asi que en las bases que vienen de antes el
porcentaje de uso, el semaforo y el estado se quedaron con el valor de cuando
se guardaron por ultima vez: el panel ensena 0 % y verde para siempre, el
filtro "Stock Bajo" no encuentra nada y una secuencia agotada sigue figurando
como activa.

El arreglo esta en el codigo (el aviso al ORM al emitir); esto prueba lo que
pone al dia lo que YA estaba guardado.
"""
import importlib.util
import os

from odoo.tools import parse_version
from odoo.tests import tagged

from .common import NcfCommon

VERSION_MIGRACION = '19.0.4.2.10'


@tagged('post_install', '-at_install')
class TestRecomputeSequenceStoredFields(NcfCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.vat = cls.partner_taxpayer.vat

    def _sequence_as_before_the_fix(self):
        """Una secuencia agotada con los campos guardados tal y como los
        dejaba la version anterior: a cero, verde y activa."""
        sequence = self._create_ncf_sequence('01', range_from=1, range_to=2)
        for _ in range(2):
            self._create_invoice(self.partner_taxpayer, post=True)
        self.assertEqual(sequence.current_number, 2)

        self.env.flush_all()
        self.env.cr.execute("""
            UPDATE l10n_do_ncf_sequence
            SET usage_percent = 0, traffic_light = 'green', state = 'active'
            WHERE id = %s
        """, (sequence.id,))
        sequence.invalidate_recordset()
        # Asi se veia: el numero bien, lo calculado mal.
        self.assertEqual(sequence.current_number, 2)
        self.assertEqual(sequence.usage_percent, 0.0)
        self.assertEqual(sequence.traffic_light, 'green')
        self.assertEqual(sequence.state, 'active')
        return sequence

    def test_the_helper_brings_the_stored_fields_up_to_date(self):
        sequence = self._sequence_as_before_the_fix()

        self.env['l10n_do_ncf.sequence']._l10n_do_recompute_current_number_fields()
        sequence.invalidate_recordset()

        self.assertEqual(sequence.state, 'depleted')
        self.assertEqual(sequence.usage_percent, 100.0)
        self.assertEqual(sequence.traffic_light, 'red')
        self.assertEqual(sequence.used_qty, 2)
        self.assertEqual(sequence.available_qty, 0)

    def test_it_takes_every_stored_field_that_depends_on_current_number(self):
        """Si manana se agrega otro campo guardado que dependa del numero,
        entra solo: el ayudante los busca por las dependencias declaradas.

        OJO con donde se leen: field.depends NO existe (ni en 16 ni en la 19);
        las dependencias estan en el metodo de calculo, en su _depends.
        """
        Sequence = self.env['l10n_do_ncf.sequence']
        nombres = Sequence._l10n_do_stored_fields_on_current_number()
        self.assertEqual(nombres, ['state', 'traffic_light', 'usage_percent'])
        # Y los encuentra de verdad, no solo por la lista de respaldo.
        descubiertos = set()
        for campo in Sequence._fields.values():
            if not (campo.store and campo.compute):
                continue
            metodo = (getattr(type(Sequence), campo.compute, None)
                      if isinstance(campo.compute, str) else campo.compute)
            if 'current_number' in (getattr(metodo, '_depends', None) or ()):
                descubiertos.add(campo.name)
        self.assertEqual(descubiertos, set(nombres))
        # Los no guardados no hacen falta: se calculan al leerlos.
        self.assertNotIn('used_qty', nombres)
        self.assertFalse(Sequence._fields['used_qty'].store)

    def test_the_migration_script_does_the_job(self):
        """El guion de la migracion, corrido tal cual."""
        sequence = self._sequence_as_before_the_fix()

        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'migrations', VERSION_MIGRACION, 'post-migrate.py')
        self.assertTrue(os.path.exists(ruta), 'falta %s' % ruta)
        spec = importlib.util.spec_from_file_location('post_migrate_secuencias', ruta)
        guion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guion)

        # Sin version (instalacion nueva) no hace nada.
        guion.migrate(self.env.cr, None)
        sequence.invalidate_recordset()
        self.assertEqual(sequence.state, 'active')

        # Actualizando desde una version anterior, pone al dia.
        guion.migrate(self.env.cr, '19.0.4.2.9')
        sequence.invalidate_recordset()
        self.assertEqual(sequence.state, 'depleted')
        self.assertEqual(sequence.usage_percent, 100.0)

    def test_the_manifest_version_makes_the_migration_run(self):
        """Odoo solo corre la migracion si la version del manifest llega a
        ella: si se olvida subirla, el guion no se ejecuta nunca."""
        modulo = self.env['ir.module.module'].search(
            [('name', '=', 'l10n_do_ncf')], limit=1)
        self.assertTrue(modulo)
        self.assertGreaterEqual(
            parse_version(modulo.latest_version), parse_version(VERSION_MIGRACION),
            'la version del manifest (%s) no llega a la migracion %s'
            % (modulo.latest_version, VERSION_MIGRACION))
