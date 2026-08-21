# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/ncf_dashboard.py
# Descripción: Dashboard NCF con estadísticas completas
# Compatibilidad: Odoo 19
#
# NOTA SOBRE EL CONTEO DE DOCUMENTOS
# Una venta del POS que genera factura existe en DOS modelos a la vez:
# pos.order y account.move. Al sumar ambos sin filtrar, cada venta
# facturada se contaba dos veces.
#
# Caso real en produccion (agosto 2026):
#     mostraba : 15,261  (7,565 facturas + 7,696 POS)
#     real     :  7,567  (7,565 facturas + 2 ordenes sin facturar)
#
# Por eso todas las consultas a pos.order de este archivo llevan
# ('account_move', '=', False): asi la venta facturada cuenta como
# factura, la no facturada cuenta como orden POS, y ninguna se duplica.
#
# EXCEPCION: el listado "Ultimos NCF Generados" NO lleva ese filtro; ahi
# si deben verse las ordenes facturadas, porque son los ultimos
# comprobantes emitidos.

from odoo import models, api
from datetime import date, datetime
import logging

_logger = logging.getLogger(__name__)


class NcfDashboard(models.AbstractModel):
    _name = 'l10n_do_ncf.dashboard'
    _description = 'Dashboard NCF'

    @api.model
    def get_dashboard_data(self):
        """Obtener datos para el dashboard NCF"""
        company_id = self.env.company.id
        today = date.today()
        first_day_month = today.replace(day=1)

        # =============================================
        # SECUENCIAS NCF ACTIVAS
        # =============================================
        sequences = self.env['l10n_do_ncf.sequence'].search([
            ('company_id', '=', company_id),
            ('state', '=', 'active')
        ])

        # =============================================
        # ALERTAS
        # =============================================
        alerts = []
        for seq in sequences:
            # Alerta por pocas disponibles
            if seq.available_qty <= seq.warning_threshold:
                alerts.append({
                    'type': 'warning',
                    'icon': 'fa-exclamation-triangle',
                    'title': 'Pocas secuencias disponibles',
                    'message': '%s: Solo quedan %s NCF' % (seq.ncf_type_id.name, seq.available_qty),
                    'action': 'sequence',
                    'id': seq.id
                })

            # Alerta por próxima a vencer
            if seq.expiration_date and seq.aplica_vencimiento:
                days_to_expire = (seq.expiration_date - today).days
                if 0 < days_to_expire <= 30:
                    alerts.append({
                        'type': 'danger',
                        'icon': 'fa-calendar-times-o',
                        'title': 'Secuencia por vencer',
                        'message': '%s: Vence en %s dias' % (seq.ncf_type_id.name, days_to_expire),
                        'action': 'sequence',
                        'id': seq.id
                    })
                elif days_to_expire <= 0:
                    alerts.append({
                        'type': 'danger',
                        'icon': 'fa-times-circle',
                        'title': 'Secuencia VENCIDA',
                        'message': '%s: Vencio el %s' % (seq.ncf_type_id.name, seq.expiration_date),
                        'action': 'sequence',
                        'id': seq.id
                    })

        # =============================================
        # ESTADÍSTICAS DE SECUENCIAS
        # =============================================
        sequence_stats = []
        for seq in sequences:
            total = seq.range_to - seq.range_from + 1
            used = seq.current_number - seq.range_from
            available = seq.available_qty
            percentage = (available / total) * 100 if total > 0 else 0
            
            sequence_stats.append({
                'id': seq.id,
                'name': seq.ncf_type_id.name,
                'prefix': seq.prefix,
                'available': available,
                'used': used,
                'total': total,
                'percentage': round(percentage, 1),
                'expiration': seq.expiration_date.strftime('%d/%m/%Y') if seq.expiration_date else 'Sin vencimiento',
                'state': seq.state
            })

        # =============================================
        # FACTURAS DE VENTA DEL MES (con NCF)
        # =============================================
        invoices_month = self.env['account.move'].search_count([
            ('company_id', '=', company_id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('invoice_date', '>=', first_day_month),
            ('state', '=', 'posted'),
            ('l10n_do_ncf_number', '!=', False)
        ])

        # =============================================
        # ÓRDENES POS DEL MES (con NCF)
        # =============================================
        pos_orders_month = 0
        try:
            # Verificar si el modelo pos.order existe y tiene el campo
            if 'pos.order' in self.env:
                pos_model = self.env['pos.order']
                if 'l10n_do_ncf_number' in pos_model._fields:
                    pos_orders_month = pos_model.search_count([
                        ('company_id', '=', company_id),
                        ('date_order', '>=', datetime.combine(first_day_month, datetime.min.time())),
                        ('state', 'in', ('paid', 'done', 'invoiced')),
                        ('l10n_do_ncf_number', '!=', False),
                        # Excluir las que ya generaron factura: esas ya se
                        # cuentan en invoices_month. Sin este filtro cada
                        # venta facturada se contaba DOS veces y el total
                        # del mes salia al doble de lo real.
                        ('account_move', '=', False),
                    ])
        except Exception as e:
            _logger.warning('NCF Dashboard: Error contando POS - %s', str(e))

        # Total facturas del mes = Facturas + POS
        total_sales_month = invoices_month + pos_orders_month

        # =============================================
        # FACTURAS DE COMPRA DEL MES
        # =============================================
        purchases_month = self.env['account.move'].search_count([
            ('company_id', '=', company_id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('invoice_date', '>=', first_day_month),
            ('state', '=', 'posted')
        ])

        # =============================================
        # NCF ANULADOS DEL MES
        # =============================================
        # Facturas anuladas con NCF
        cancelled_invoices = self.env['account.move'].search_count([
            ('company_id', '=', company_id),
            ('state', '=', 'cancel'),
            ('invoice_date', '>=', first_day_month),
            ('l10n_do_ncf_number', '!=', False)
        ])

        # POS anulados con NCF
        cancelled_pos = 0
        try:
            if 'pos.order' in self.env:
                pos_model = self.env['pos.order']
                if 'l10n_do_ncf_number' in pos_model._fields:
                    cancelled_pos = pos_model.search_count([
                        ('company_id', '=', company_id),
                        ('state', '=', 'cancel'),
                        ('date_order', '>=', datetime.combine(first_day_month, datetime.min.time())),
                        ('l10n_do_ncf_number', '!=', False),
                        # Si tiene factura, la anulacion se cuenta del lado
                        # de account.move (cancelled_invoices).
                        ('account_move', '=', False),
                    ])
        except Exception as e:
            _logger.warning('NCF Dashboard: Error contando POS anulados - %s', str(e))

        cancelled_month = cancelled_invoices + cancelled_pos

        # =============================================
        # ESTADO DE LICENCIA
        # =============================================
        license_config = self.env['l10n_do_ncf.license.config'].search([
            ('company_id', '=', company_id)
        ], limit=1)

        license_data = {
            'is_valid': license_config.is_valid if license_config else False,
            'status': license_config.status if license_config else 'not_configured',
            'days_remaining': license_config.days_remaining if license_config else 0,
            'expiration_date': license_config.expiration_date.strftime('%d/%m/%Y') if license_config and license_config.expiration_date else '',
            'company_name': license_config.licensed_company_name if license_config else ''
        }

        # =============================================
        # RESUMEN POR TIPO DE NCF (del mes)
        # =============================================
        ncf_by_type = []
        ncf_types = self.env['l10n_do_ncf.type'].search([])
        
        for ncf_type in ncf_types:
            # Contar facturas de este tipo
            invoice_count = self.env['account.move'].search_count([
                ('company_id', '=', company_id),
                ('l10n_do_ncf_type_id', '=', ncf_type.id),
                ('invoice_date', '>=', first_day_month),
                ('state', '=', 'posted'),
                ('l10n_do_ncf_number', '!=', False)
            ])
            
            # Contar POS de este tipo
            pos_count = 0
            try:
                if 'pos.order' in self.env:
                    pos_model = self.env['pos.order']
                    if 'l10n_do_ncf_type' in pos_model._fields:
                        pos_count = pos_model.search_count([
                            ('company_id', '=', company_id),
                            ('l10n_do_ncf_type', '=', ncf_type.prefix),
                            ('date_order', '>=', datetime.combine(first_day_month, datetime.min.time())),
                            ('state', 'in', ('paid', 'done', 'invoiced')),
                            ('l10n_do_ncf_number', '!=', False),
                            # Evitar contar dos veces las ya facturadas
                            ('account_move', '=', False),
                        ])
            except Exception:
                pass

            total_count = invoice_count + pos_count
            if total_count > 0:
                ncf_by_type.append({
                    'type_id': ncf_type.id,
                    'name': ncf_type.name,
                    'prefix': ncf_type.prefix,
                    'count': total_count,
                    'invoice_count': invoice_count,
                    'pos_count': pos_count
                })

        # =============================================
        # ÚLTIMOS NCF GENERADOS
        # =============================================
        recent_ncf = []
        
        # Últimas facturas con NCF
        recent_invoices = self.env['account.move'].search([
            ('company_id', '=', company_id),
            ('l10n_do_ncf_number', '!=', False),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund'))
        ], order='create_date desc', limit=10)
        
        for inv in recent_invoices:
            recent_ncf.append({
                'ncf': inv.l10n_do_ncf_number,
                'partner': inv.partner_id.name if inv.partner_id else 'Sin cliente',
                'partner_vat': inv.partner_id.vat if inv.partner_id else '',
                'amount': inv.amount_total,
                'currency': inv.currency_id.symbol if inv.currency_id else '$',
                'date': inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else '',
                'datetime': inv.create_date.strftime('%Y-%m-%d %H:%M:%S') if inv.create_date else '',
                'type': 'invoice',
                'move_type': inv.move_type,
                'id': inv.id,
                'name': inv.name
            })

        # Últimas órdenes POS con NCF
        try:
            if 'pos.order' in self.env:
                pos_model = self.env['pos.order']
                if 'l10n_do_ncf_number' in pos_model._fields:
                    recent_pos = pos_model.search([
                        ('company_id', '=', company_id),
                        ('l10n_do_ncf_number', '!=', False),
                        ('state', 'in', ('paid', 'done', 'invoiced'))
                    ], order='date_order desc', limit=10)
                    
                    for pos in recent_pos:
                        recent_ncf.append({
                            'ncf': pos.l10n_do_ncf_number,
                            'partner': pos.partner_id.name if pos.partner_id else 'Consumidor Final',
                            'partner_vat': pos.partner_id.vat if pos.partner_id else '',
                            'amount': pos.amount_total,
                            'currency': pos.currency_id.symbol if pos.currency_id else '$',
                            'date': pos.date_order.strftime('%d/%m/%Y') if pos.date_order else '',
                            'datetime': pos.date_order.strftime('%Y-%m-%d %H:%M:%S') if pos.date_order else '',
                            'type': 'pos',
                            'move_type': 'pos_order',
                            'id': pos.id,
                            'name': pos.name
                        })
        except Exception as e:
            _logger.warning('NCF Dashboard: Error obteniendo POS recientes - %s', str(e))

        # Ordenar por fecha/hora descendente y tomar los 10 más recientes
        recent_ncf = sorted(recent_ncf, key=lambda x: x.get('datetime', ''), reverse=True)[:10]

        # =============================================
        # TOTALES GENERALES (histórico)
        # =============================================
        total_ncf_generated = self.env['account.move'].search_count([
            ('company_id', '=', company_id),
            ('l10n_do_ncf_number', '!=', False),
            ('state', '=', 'posted')
        ])

        total_pos_ncf = 0
        try:
            if 'pos.order' in self.env:
                pos_model = self.env['pos.order']
                if 'l10n_do_ncf_number' in pos_model._fields:
                    total_pos_ncf = pos_model.search_count([
                        ('company_id', '=', company_id),
                        ('l10n_do_ncf_number', '!=', False),
                        ('state', 'in', ('paid', 'done', 'invoiced')),
                        # Evitar contar dos veces las ya facturadas
                        ('account_move', '=', False),
                    ])
        except Exception:
            pass

        # =============================================
        # RETORNO DE DATOS
        # =============================================
        return {
            # Alertas
            'alerts': alerts,
            
            # Secuencias
            'sequences': sequence_stats,
            
            # Contadores del mes
            'invoices_month': total_sales_month,  # Total (Facturas + POS)
            'invoices_only': invoices_month,       # Solo facturas
            'pos_orders_month': pos_orders_month,  # Solo POS
            'purchases_month': purchases_month,
            'cancelled_month': cancelled_month,
            
            # Licencia
            'license': license_data,
            
            # Info del período
            'current_month': today.strftime('%B %Y'),
            'today': today.strftime('%d/%m/%Y'),
            
            # Estadísticas adicionales
            'ncf_by_type': ncf_by_type,
            'recent_ncf': recent_ncf,
            
            # Totales históricos
            'total_ncf_generated': total_ncf_generated + total_pos_ncf,
            'total_invoice_ncf': total_ncf_generated,
            'total_pos_ncf': total_pos_ncf,
        }

    @api.model
    def get_ncf_details(self, ncf_type, date_from=None, date_to=None):
        """Obtener detalle de NCF por tipo para reportes"""
        company_id = self.env.company.id
        
        domain = [
            ('company_id', '=', company_id),
            ('l10n_do_ncf_number', '!=', False),
            ('state', '=', 'posted')
        ]
        
        if ncf_type:
            domain.append(('l10n_do_ncf_type_id.prefix', '=', ncf_type))
        
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        
        invoices = self.env['account.move'].search(domain, order='invoice_date desc')
        
        result = []
        for inv in invoices:
            result.append({
                'id': inv.id,
                'name': inv.name,
                'ncf': inv.l10n_do_ncf_number,
                'partner': inv.partner_id.name if inv.partner_id else '',
                'partner_vat': inv.partner_id.vat if inv.partner_id else '',
                'date': inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else '',
                'amount': inv.amount_total,
                'currency': inv.currency_id.symbol if inv.currency_id else '$',
                'state': inv.state
            })
        
        return result

    @api.model
    def refresh_dashboard(self):
        """Forzar actualización del dashboard"""
        return self.get_dashboard_data()