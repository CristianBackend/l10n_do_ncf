# -*- coding: utf-8 -*-
# Migración 19.0.4.2.0
#
# - Usuarios internos de compañías dominicanas sin zona horaria: hora de RD
#   (America/Santo_Domingo). Sin zona, Odoo usa UTC y de 8 p. m. a medianoche
#   una factura nueva toma la fecha de mañana. Una zona ya elegida no se toca.
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_do_ncf.models import l10n_do_autoconfig


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].search([]).filtered(l10n_do_autoconfig.is_dominican)
    l10n_do_autoconfig.autoconfigure_user_tz(env, companies)
