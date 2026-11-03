# -*- coding: utf-8 -*-
from odoo import models, api, _
from datetime import date
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class DgiiReminder(models.AbstractModel):
    _name = 'l10n_do_ncf.dgii.reminder'
    _description = 'DGII Monthly Reminder'

    @api.model
    def send_monthly_reminder(self):
        """Envia recordatorio mensual para reportes DGII via mensaje interno"""
        _logger.info('Iniciando envio de recordatorios DGII...')
        
        companies = self.env['res.company'].search([
            ('vat', '!=', False),
        ])
        
        months = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        
        month_name = months.get(date.today().month, '')
        
        message_body = Markup('''
        <div style="padding: 15px; background: #fff3cd; border-left: 4px solid #ffc107; margin: 10px 0;">
            <h3 style="color: #856404; margin-top: 0;">Recordatorio DGII - %s</h3>
            <p style="color: #856404;">Los reportes DGII deben enviarse <strong>antes del dia 15</strong>:</p>
            <ul style="color: #856404;">
                <li><strong>606</strong> - Compras de Bienes y Servicios</li>
                <li><strong>607</strong> - Ventas de Bienes y Servicios</li>
                <li><strong>608</strong> - Comprobantes Anulados</li>
                <li><strong>609</strong> - Pagos al Exterior</li>
            </ul>
            <p style="color: #856404;">Accede a <strong>Contabilidad - Reportes - Reportes DGII</strong> para generarlos.</p>
        </div>
        ''') % month_name
        
        sent_count = 0
        notified_users = self.env['res.users']

        for company in companies:
            try:
                users = self._get_reminder_users(company) - notified_users
                for user in users:
                    if user.partner_id:
                        user.partner_id.message_post(
                            body=message_body,
                            subject='Recordatorio: Enviar Reportes DGII - %s' % month_name,
                            message_type='notification',
                            subtype_xmlid='mail.mt_note',
                        )
                        sent_count += 1
                        _logger.info('Notificacion DGII enviada a %s', user.name)
                notified_users |= users

            except Exception as e:
                _logger.error('Error enviando notificacion a %s: %s', company.name, e)
                continue

        _logger.info('Notificaciones DGII enviadas: %s' % sent_count)
        return True

    @api.model
    def _get_reminder_users(self, company):
        """Usuarios internos activos con acceso a la compania que son
        contadores (administradores de contabilidad) o administradores."""
        users = self.env['res.users'].search([
            ('company_ids', 'in', company.id),
            ('share', '=', False),
        ])
        return users.filtered(
            lambda u: u.has_group('account.group_account_manager')
            or u.has_group('base.group_system')
        )

    @api.model
    def send_test_reminder(self):
        return self.send_monthly_reminder()
