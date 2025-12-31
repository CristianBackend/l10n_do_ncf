# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/fiscal_audit.py
# Descripción: Auditoría fiscal - trazabilidad de cambios NCF
# Versión: 19.0.2.3.0

from odoo import models, fields, api, _
import logging
import json

_logger = logging.getLogger(__name__)


class L10nDoFiscalAudit(models.Model):
    """
    Auditoría Fiscal
    
    Registra todos los cambios relacionados con NCF para trazabilidad DGII.
    Incluye: generación, anulación, modificación, errores.
    """
    _name = 'l10n_do_ncf.fiscal.audit'
    _description = 'Auditoría Fiscal NCF'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company
    )

    # Documento relacionado
    move_id = fields.Many2one(
        'account.move',
        string='Documento',
        ondelete='set null',
        index=True
    )

    registro_unico_id = fields.Many2one(
        'l10n_do_ncf.registro.unico',
        string='Registro Único B12',
        ondelete='set null'
    )

    # Datos NCF
    ncf_number = fields.Char(string='NCF', index=True)
    ncf_type = fields.Char(string='Tipo NCF')
    ncf_origin = fields.Char(string='NCF Afectado')

    # Tipo de evento
    event_type = fields.Selection([
        ('ncf_generated', 'NCF Generado'),
        ('ncf_annulled', 'NCF Anulado'),
        ('ncf_modified', 'NCF Modificado'),
        ('status_change', 'Cambio Estado'),
        ('credit_note', 'Nota Crédito Aplicada'),
        ('debit_note', 'Nota Débito Aplicada'),
        ('retention_added', 'Retención Agregada'),
        ('retention_removed', 'Retención Eliminada'),
        ('validation_error', 'Error Validación'),
        ('dgii_rejection', 'Rechazo DGII'),
        ('dgii_accepted', 'Aceptado DGII'),
        ('manual_edit', 'Edición Manual'),
        ('sequence_consumed', 'Secuencia Consumida'),
        ('b12_generated', 'B12 Generado'),
        ('report_607', 'Reportado 607'),
        ('report_606', 'Reportado 606'),
    ], string='Tipo Evento', required=True, index=True)

    # Detalles
    old_value = fields.Text(string='Valor Anterior')
    new_value = fields.Text(string='Valor Nuevo')
    description = fields.Text(string='Descripción')

    # Datos adicionales (JSON)
    extra_data = fields.Text(string='Datos Adicionales')

    # Usuario y timestamp
    user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        default=lambda self: self.env.user,
        required=True
    )

    # IP y sesión (opcional)
    ip_address = fields.Char(string='IP')
    session_id = fields.Char(string='Sesión')

    @api.depends('ncf_number', 'event_type', 'create_date')
    def _compute_display_name(self):
        for record in self:
            event_label = dict(self._fields['event_type'].selection).get(
                record.event_type, record.event_type)
            record.display_name = '%s - %s (%s)' % (
                record.ncf_number or 'Sin NCF',
                event_label,
                record.create_date.strftime('%Y-%m-%d %H:%M') if record.create_date else ''
            )

    @api.model
    def log_event(self, event_type, move=None, ncf_number=None, **kwargs):
        """
        Método helper para registrar eventos de auditoría.
        
        Uso:
            self.env['l10n_do_ncf.fiscal.audit'].log_event(
                'ncf_generated',
                move=invoice,
                ncf_number='B0100000001',
                description='NCF generado automáticamente'
            )
        """
        vals = {
            'event_type': event_type,
            'ncf_number': ncf_number,
            'company_id': kwargs.get('company_id', self.env.company.id),
        }

        if move:
            vals.update({
                'move_id': move.id,
                'ncf_number': ncf_number or move.l10n_do_ncf_number,
                'ncf_type': move.l10n_do_ncf_type_id.code if move.l10n_do_ncf_type_id else None,
                'company_id': move.company_id.id,
            })

        # Campos opcionales
        for field in ['ncf_origin', 'old_value', 'new_value', 'description', 
                      'extra_data', 'registro_unico_id', 'ip_address']:
            if field in kwargs:
                vals[field] = kwargs[field]

        # Convertir extra_data a JSON si es dict
        if isinstance(vals.get('extra_data'), dict):
            vals['extra_data'] = json.dumps(vals['extra_data'], default=str)

        try:
            record = self.sudo().create(vals)
            _logger.info('Auditoría NCF: %s | %s | %s', 
                        event_type, ncf_number, kwargs.get('description', ''))
            return record
        except Exception as e:
            _logger.error('Error registrando auditoría: %s', str(e))
            return False

    @api.model
    def log_ncf_generated(self, move):
        """Log específico para NCF generado"""
        return self.log_event(
            'ncf_generated',
            move=move,
            description='NCF generado al confirmar documento',
            extra_data={
                'sequence_id': move.l10n_do_ncf_seq_id.id if move.l10n_do_ncf_seq_id else None,
                'partner': move.partner_id.name if move.partner_id else None,
                'amount': move.amount_total,
            }
        )

    @api.model
    def log_status_change(self, move, old_status, new_status):
        """Log específico para cambio de estado fiscal"""
        return self.log_event(
            'status_change',
            move=move,
            old_value=old_status,
            new_value=new_status,
            description='Estado fiscal cambiado de %s a %s' % (old_status, new_status)
        )

    @api.model
    def log_credit_note(self, credit_note, origin_move):
        """Log específico para NC aplicada"""
        return self.log_event(
            'credit_note',
            move=credit_note,
            ncf_origin=origin_move.l10n_do_ncf_number,
            description='Nota Crédito %s aplicada a %s' % (
                credit_note.l10n_do_ncf_number,
                origin_move.l10n_do_ncf_number
            ),
            extra_data={
                'origin_move_id': origin_move.id,
                'origin_ncf': origin_move.l10n_do_ncf_number,
                'amount': credit_note.amount_total,
                'reason': credit_note.l10n_do_credit_note_reason,
            }
        )

    @api.model
    def log_annulment(self, move, reason=None):
        """Log específico para anulación"""
        return self.log_event(
            'ncf_annulled',
            move=move,
            description=reason or 'NCF anulado',
            extra_data={
                'previous_status': move.l10n_do_fiscal_status,
            }
        )


class AccountMoveAudit(models.Model):
    """Extensión de account.move para auditoría automática"""
    _inherit = 'account.move'

    l10n_do_audit_ids = fields.One2many(
        'l10n_do_ncf.fiscal.audit',
        'move_id',
        string='Historial Auditoría'
    )

    def write(self, vals):
        """Override write para auditar cambios en campos fiscales"""
        audit_fields = [
            'l10n_do_ncf_number', 'l10n_do_fiscal_status', 
            'l10n_do_vendor_ncf', 'l10n_do_ncf_origin'
        ]
        
        Audit = self.env['l10n_do_ncf.fiscal.audit']
        
        for move in self:
            for field in audit_fields:
                if field in vals and vals[field] != getattr(move, field, None):
                    old_val = getattr(move, field, None)
                    new_val = vals[field]
                    
                    # Determinar tipo de evento
                    if field == 'l10n_do_ncf_number' and not old_val and new_val:
                        event_type = 'ncf_generated'
                    elif field == 'l10n_do_fiscal_status':
                        event_type = 'status_change'
                    else:
                        event_type = 'manual_edit'
                    
                    Audit.log_event(
                        event_type,
                        move=move,
                        old_value=str(old_val) if old_val else None,
                        new_value=str(new_val) if new_val else None,
                        description='Campo %s modificado' % field
                    )

        return super().write(vals)


class L10nDoRegistroUnicoAudit(models.Model):
    """Extensión B12 para auditoría"""
    _inherit = 'l10n_do_ncf.registro.unico'

    l10n_do_audit_ids = fields.One2many(
        'l10n_do_ncf.fiscal.audit',
        'registro_unico_id',
        string='Historial Auditoría'
    )

    def _generate_b12_ncf(self):
        """Override para auditar generación B12"""
        result = super()._generate_b12_ncf()
        
        self.env['l10n_do_ncf.fiscal.audit'].log_event(
            'b12_generated',
            registro_unico_id=self.id,
            ncf_number=self.l10n_do_ncf_number,
            company_id=self.company_id.id,
            description='B12 generado con %s transacciones' % self.total_transactions,
            extra_data={
                'date': str(self.date),
                'total': self.amount_total,
                'transactions': self.total_transactions,
            }
        )
        
        return result