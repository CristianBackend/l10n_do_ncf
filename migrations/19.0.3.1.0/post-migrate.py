# -*- coding: utf-8 -*-
# Migración 19.0.3.1.0
#
# Hasta esta versión hooks.py nunca se ejecutaba (el manifest resolvía
# post_init_hook en __init__.py), así que las bases ya instaladas no tienen
# los índices únicos de NCF ni los impuestos exentos clasificados. Aquí se
# crea lo que falte, con la misma lógica que usa la instalación nueva.
#
# Si hay NCF duplicados, ensure_ncf_indexes lanza un error que lista los
# documentos y la actualización se detiene sin aplicar cambios.

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.l10n_do_ncf import hooks

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Instalación nueva: lo hace post_init_hook.
        return

    _logger.info('l10n_do_ncf: migración 19.0.3.1.0 (desde %s)', version)

    # Primero los índices: si hay duplicados se detiene antes de tocar nada.
    hooks.ensure_ncf_indexes(cr)

    env = api.Environment(cr, SUPERUSER_ID, {})
    hooks.configure_vat_and_taxes(env)
