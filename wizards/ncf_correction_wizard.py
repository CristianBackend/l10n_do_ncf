# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: wizards/ncf_correction_wizard.py
# Descripción: Wizards para correcciones fiscales guiadas
# Versión: 19.0.3.0.0

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class NcfRncCorrectionWizard(models.TransientModel):
    """
    Wizard para corregir factura B02 cuando cliente obtiene RNC.
    
    Flujo guiado:
    1. Usuario selecciona factura B02 a corregir
    2. Sistema valida que cliente tenga RNC
    3. Genera NC (B04) automática
    4. Crea nueva factura B01 con mismo contenido
    """
    _name = 'l10n_do_ncf.rnc.correction.wizard'
    _description = 'Corrección RNC - B02 a B01'

    invoice_id = fields.Many2one(
        'account.move',
        string='Factura B02 a Corregir',
        required=True,
        domain="[('l10n_do_ncf_number', '=like', 'B02%'), ('state', '=', 'posted'), ('move_type', '=', 'out_invoice')]"
    )

    partner_id = fields.Many2one(
        related='invoice_id.partner_id',
        string='Cliente'
    )

    partner_vat = fields.Char(
        related='partner_id.vat',
        string='RNC Cliente'
    )

    invoice_amount = fields.Monetary(
        related='invoice_id.amount_total',
        string='Monto Factura'
    )

    currency_id = fields.Many2one(
        related='invoice_id.currency_id'
    )

    credit_note_reason = fields.Selection([
        ('02', '02 - Corrección de errores'),
    ], string='Motivo NC', default='02', required=True)

    notes = fields.Text(
        string='Notas',
        default='Corrección por asignación de RNC al cliente.'
    )

    # Resultado
    credit_note_id = fields.Many2one('account.move', string='NC Generada', readonly=True)
    new_invoice_id = fields.Many2one('account.move', string='Nueva Factura B01', readonly=True)

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            if not self.partner_id.vat:
                return {
                    'warning': {
                        'title': _('⚠️ Cliente sin RNC'),
                        'message': _('El cliente aún no tiene RNC asignado. Asigne el RNC primero.')
                    }
                }

    def action_validate(self):
        """Validar que se puede proceder"""
        self.ensure_one()

        if not self.invoice_id:
            raise UserError(_('Seleccione una factura B02.'))

        if not self.partner_id.vat:
            raise UserError(_(
                'El cliente no tiene RNC asignado.\n\n'
                'Primero asigne el RNC en la ficha del cliente.'
            ))

        ncf = self.invoice_id.l10n_do_ncf_number or ''
        if not ncf.startswith('B02'):
            raise UserError(_('Solo puede corregir facturas B02.'))

        if self.invoice_id.l10n_do_fiscal_status in ('annulled', 'credited'):
            raise UserError(_('Esta factura ya fue anulada o tiene NC.'))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('✓ Validación OK'),
                'message': _('Puede proceder con la corrección.'),
                'type': 'success',
            }
        }

    def action_process(self):
        """
        Ejecutar corrección:
        1. Crear NC a la factura B02
        2. Crear nueva factura B01
        """
        self.ensure_one()

        # Validar
        if not self.partner_id.vat:
            raise UserError(_('Cliente sin RNC. No puede proceder.'))

        invoice = self.invoice_id

        # 1. Crear Nota de Crédito
        credit_note = invoice._reverse_moves(
            default_values_list=[{
                'ref': _('NC por corrección RNC - %s') % invoice.name,
                'l10n_do_credit_note_reason': self.credit_note_reason,
                'l10n_do_ncf_origin': invoice.l10n_do_ncf_number,
                'l10n_do_origin_move_id': invoice.id,
            }],
            cancel=False
        )

        if credit_note:
            # Confirmar NC
            credit_note.action_post()
            self.credit_note_id = credit_note.id

        # 2. Crear nueva factura B01
        new_invoice_vals = {
            'partner_id': invoice.partner_id.id,
            'move_type': 'out_invoice',
            'invoice_date': fields.Date.today(),
            'ref': _('Reemplazo de %s por RNC') % invoice.name,
            'invoice_line_ids': [],
        }

        # Copiar líneas
        for line in invoice.invoice_line_ids.filtered(lambda l: not l.display_type):
            new_invoice_vals['invoice_line_ids'].append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'quantity': line.quantity,
                'price_unit': line.price_unit,
                'tax_ids': [(6, 0, line.tax_ids.ids)],
                'discount': line.discount,
            }))

        new_invoice = self.env['account.move'].create(new_invoice_vals)
        self.new_invoice_id = new_invoice.id

        # Auditoría
        self.env['l10n_do_ncf.fiscal.audit'].log_event(
            'manual_edit',
            move=invoice,
            description='Corrección por RNC: NC %s, Nueva factura %s' % (
                credit_note.l10n_do_ncf_number if credit_note else 'N/A',
                new_invoice.name
            ),
            extra_data={
                'credit_note_id': credit_note.id if credit_note else None,
                'new_invoice_id': new_invoice.id,
                'reason': 'Cliente obtuvo RNC',
            }
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva Factura B01'),
            'res_model': 'account.move',
            'res_id': new_invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }


class NcfRetentionCorrectionWizard(models.TransientModel):
    """
    Wizard para corregir retención mal aplicada.
    """
    _name = 'l10n_do_ncf.retention.correction.wizard'
    _description = 'Corrección de Retención'

    move_id = fields.Many2one(
        'account.move',
        string='Documento',
        required=True,
        domain="[('move_type', 'in', ('in_invoice', 'in_refund')), ('state', '=', 'posted')]"
    )

    original_isr = fields.Monetary(
        string='ISR Original',
        related='move_id.l10n_do_isr_retenido'
    )

    original_itbis = fields.Monetary(
        string='ITBIS Original',
        related='move_id.l10n_do_itbis_retenido'
    )

    currency_id = fields.Many2one(
        related='move_id.currency_id'
    )

    correction_type = fields.Selection([
        ('isr_up', 'Aumentar ISR'),
        ('isr_down', 'Disminuir ISR'),
        ('itbis_up', 'Aumentar ITBIS'),
        ('itbis_down', 'Disminuir ITBIS'),
    ], string='Tipo Corrección', required=True)

    correction_amount = fields.Monetary(
        string='Monto Corrección',
        currency_field='currency_id',
        required=True
    )

    reason = fields.Text(
        string='Motivo',
        required=True
    )

    apply_next_period = fields.Boolean(
        string='Aplicar en Próximo Período',
        default=True,
        help='Si el documento ya fue reportado, la corrección se aplicará en el próximo período fiscal.'
    )

    def action_process(self):
        """Procesar corrección de retención"""
        self.ensure_one()

        move = self.move_id

        if move.l10n_do_reported_606 and not self.apply_next_period:
            raise UserError(_(
                'Este documento ya fue reportado en 606.\n'
                'Debe marcar "Aplicar en Próximo Período".'
            ))

        # Registrar en auditoría
        self.env['l10n_do_ncf.fiscal.audit'].log_event(
            'retention_added' if 'up' in self.correction_type else 'retention_removed',
            move=move,
            old_value='ISR: %s, ITBIS: %s' % (self.original_isr, self.original_itbis),
            new_value='Corrección: %s %s' % (self.correction_type, self.correction_amount),
            description=self.reason,
            extra_data={
                'correction_type': self.correction_type,
                'amount': self.correction_amount,
                'apply_next_period': self.apply_next_period,
            }
        )

        # Crear nota interna
        move.message_post(
            body=_(
                '<strong>⚠️ Corrección de Retención</strong><br/>'
                'Tipo: %s<br/>'
                'Monto: %s<br/>'
                'Motivo: %s<br/>'
                'Aplicar próximo período: %s'
            ) % (
                self.correction_type,
                self.correction_amount,
                self.reason,
                'Sí' if self.apply_next_period else 'No'
            )
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('✓ Corrección Registrada'),
                'message': _('La corrección ha sido registrada. Revise el próximo 606.'),
                'type': 'success',
            }
        }


class Ncf607MultiPeriodWizard(models.TransientModel):
    """
    Wizard para gestionar NC en múltiples períodos (607).
    """
    _name = 'l10n_do_ncf.607.multiperiod.wizard'
    _description = 'NC Multi-período 607'

    credit_note_id = fields.Many2one(
        'account.move',
        string='Nota de Crédito',
        required=True,
        domain="[('move_type', '=', 'out_refund'), ('state', '=', 'posted')]"
    )

    origin_invoice_id = fields.Many2one(
        related='credit_note_id.l10n_do_origin_move_id',
        string='Factura Original'
    )

    origin_period = fields.Char(
        string='Período Factura Original',
        compute='_compute_periods'
    )

    credit_period = fields.Char(
        string='Período NC',
        compute='_compute_periods'
    )

    is_different_period = fields.Boolean(
        string='Períodos Diferentes',
        compute='_compute_periods'
    )

    @api.depends('credit_note_id', 'origin_invoice_id')
    def _compute_periods(self):
        for wizard in self:
            origin_period = ''
            credit_period = ''
            is_different = False

            if wizard.origin_invoice_id and wizard.origin_invoice_id.invoice_date:
                origin_period = wizard.origin_invoice_id.invoice_date.strftime('%Y%m')

            if wizard.credit_note_id and wizard.credit_note_id.invoice_date:
                credit_period = wizard.credit_note_id.invoice_date.strftime('%Y%m')

            if origin_period and credit_period:
                is_different = origin_period != credit_period

            wizard.origin_period = origin_period
            wizard.credit_period = credit_period
            wizard.is_different_period = is_different

    def action_confirm_period(self):
        """Confirmar período correcto para reportar NC"""
        self.ensure_one()

        if self.is_different_period:
            message = _(
                '📋 IMPORTANTE PARA 607:\n\n'
                'La NC se reportará en el período %s (mes de la NC).\n'
                'La factura original es del período %s.\n\n'
                'Esto es correcto según normativa DGII.'
            ) % (self.credit_period, self.origin_period)
        else:
            message = _(
                '✓ La NC y la factura son del mismo período %s.\n'
                'Se reportarán juntas en el 607.'
            ) % self.credit_period

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Información Período 607'),
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }