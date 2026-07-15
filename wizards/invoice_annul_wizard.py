# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class InvoiceAnnulWizard(models.TransientModel):
    _name = 'l10n_do_ncf.invoice.annul.wizard'
    _description = 'Wizard para Anular Factura con NCF'

    move_id = fields.Many2one('account.move', string='Factura', required=True, readonly=True)
    ncf_number = fields.Char(string='NCF', readonly=True)
    partner_name = fields.Char(string='Cliente/Proveedor', readonly=True)
    amount_total = fields.Monetary(string='Total', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    
    annul_reason = fields.Text(string='Motivo de Anulación', required=True,
        help='Indique el motivo por el cual se anula esta factura')
    
    action_type = fields.Selection([
        ('annul', 'Anular Directamente'),
        ('credit_note', 'Crear Nota de Crédito'),
    ], string='Acción', required=True, default='annul',
        help='Anular: Cancela la factura sin generar NC (el NCF queda ocupado).\n'
             'Nota de Crédito: Genera un documento B04 para reversar la factura.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self._context.get('active_id')
        if active_id:
            move = self.env['account.move'].browse(active_id)
            res.update({
                'move_id': move.id,
                'ncf_number': move.l10n_do_ncf_number,
                'partner_name': move.partner_id.name,
                'amount_total': move.amount_total,
                'currency_id': move.currency_id.id,
            })
        return res

    def action_confirm(self):
        """Ejecutar la acción seleccionada"""
        self.ensure_one()
        
        if not self.move_id:
            raise UserError(_('No se encontró la factura a anular.'))
        
        # Verificar que no esté reportada a DGII
        if self.move_id.l10n_do_reported_606 or self.move_id.l10n_do_reported_607:
            raise UserError(_(
                'Esta factura ya fue reportada a DGII en el período %s.\n'
                'No puede ser anulada ni modificada.'
            ) % (self.move_id.l10n_do_report_period or 'anterior'))
        
        if self.action_type == 'annul':
            return self._action_annul_direct()
        else:
            return self._action_create_credit_note()

    def _action_annul_direct(self):
        """Anular la factura directamente sin crear NC"""
        move = self.move_id
        
        # Registrar el motivo en el chatter
        move.message_post(
            body=_('<strong>Factura Anulada</strong><br/>'
                   '<b>NCF:</b> %s<br/>'
                   '<b>Motivo:</b> %s<br/>'
                   '<b>Usuario:</b> %s') % (
                move.l10n_do_ncf_number,
                self.annul_reason,
                self.env.user.name
            ),
            subject=_('Factura Anulada')
        )
        
        # Marcar como anulada fiscalmente
        move.write({
            'l10n_do_fiscal_status': 'annulled',
        })
        
        # Cancelar la factura (cambiar estado a cancel)
        # Usamos SQL para bypass las restricciones
        self.env.cr.execute("""
            UPDATE account_move 
            SET state = 'cancel'
            WHERE id = %s
        """, [move.id])
        
        move.invalidate_recordset()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Factura Anulada'),
                'message': _('La factura %s con NCF %s ha sido anulada.\n'
                            'El NCF permanece ocupado y se reportará como anulado en el 607.') % (
                    move.name, move.l10n_do_ncf_number
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _action_create_credit_note(self):
        """Abrir el wizard estándar de Nota de Crédito"""
        move = self.move_id
        
        # Registrar intención en el chatter
        move.message_post(
            body=_('<strong>Iniciando Nota de Crédito</strong><br/>'
                   '<b>Motivo:</b> %s') % self.annul_reason,
            subject=_('Creación de NC')
        )
        
        # Abrir wizard de reversal (Nota de Crédito)
        return {
            'name': _('Crear Nota de Crédito'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.reversal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': [move.id],
                'active_id': move.id,
                'default_reason': self.annul_reason,
            }
        }