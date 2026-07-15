# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import UserError


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    def reverse_moves(self, is_modify=False):
        """Validar que exista secuencia B04 antes de crear NC"""
        for move in self.move_ids:
            if move.company_id.country_id.code != 'DO':
                continue
            if not move.l10n_do_ncf_number:
                continue
            
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
            if not ncf_type:
                raise UserError(_('No existe el tipo de comprobante B04 (Nota de Credito) en el sistema.'))
            
            sequence = self.env['l10n_do_ncf.sequence'].search([
                ('ncf_type_id', '=', ncf_type.id),
                ('company_id', '=', move.company_id.id),
                ('state', '=', 'active'),
            ], limit=1)
            
            if not sequence:
                raise UserError(_(
                    'No hay secuencia B04 (Nota de Credito) configurada para %s.\n\n'
                    'Debe solicitar a la DGII la autorizacion de NCF tipo B04 '
                    'y configurar la secuencia en:\n'
                    'Dashboard NCF > Secuencias NCF > Nuevo'
                ) % move.company_id.name)
        
        return super().reverse_moves(is_modify=is_modify)

    def _prepare_default_reversal(self, move):
        """Agregar tipo NCF y NCF afectado a la nota de credito"""
        values = super()._prepare_default_reversal(move)
        
        if move.l10n_do_ncf_number:
            ncf_type = self.env['l10n_do_ncf.type'].search([('code', '=', '04')], limit=1)
            
            values.update({
                'l10n_do_ncf_type_id': ncf_type.id if ncf_type else False,
                'l10n_do_ncf_origin': move.l10n_do_ncf_number,
                'l10n_do_origin_move_id': move.id,
            })
        
        return values