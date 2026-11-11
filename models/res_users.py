# -*- coding: utf-8 -*-
from odoo import api, models

# Zona horaria de República Dominicana (UTC-4, sin horario de verano).
DO_TZ = 'America/Santo_Domingo'


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._l10n_do_set_default_tz()
        return users

    def _l10n_do_set_default_tz(self):
        """Hora de RD para los usuarios internos de una compañía dominicana sin
        zona horaria. Sin ella Odoo usa UTC: de 8 p. m. a medianoche en RD una
        factura nueva toma la fecha de mañana. Una zona ya elegida no se toca."""
        users = self.sudo().filtered(lambda u: (
            not u.tz and not u.share and (
                u.company_id.account_fiscal_country_id.code == 'DO'
                or u.company_id.country_id.code == 'DO')))
        if users:
            users.write({'tz': DO_TZ})
        return users
