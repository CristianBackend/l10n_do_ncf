# -*- coding: utf-8 -*-
"""
Generador de Reportes DGII según Norma General 07-2018 y actualizaciones
606 - Compras de Bienes y Servicios (23 columnas)
607 - Ventas de Bienes y Servicios (23 columnas)
608 - Comprobantes Anulados (3 columnas)
609 - Pagos al Exterior (13 columnas)

Validado contra:
- Norma General 07-2018, 05-2019, 01-2020, 04-2022, 06-2023
- Especificaciones técnicas DGII
- Validador oficial DGII

Versión: 19.0.1.9.0
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
from datetime import date, timedelta


class DgiiReportWizard(models.TransientModel):
    _name = 'l10n_do_ncf.dgii.report.wizard'
    _description = 'Wizard para Generar Reportes DGII'

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company
    )
    report_type = fields.Selection([
        ('606', '606 - Compras de Bienes y Servicios'),
        ('607', '607 - Ventas de Bienes y Servicios'),
        ('608', '608 - Comprobantes Anulados'),
        ('609', '609 - Pagos al Exterior'),
        ('ir17', 'IR-17 - Resumen de Retenciones'),
    ], string='Tipo de Reporte', required=True, default='606')

    date_from = fields.Date(
        string='Desde',
        required=True,
        default=lambda self: date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='Hasta',
        required=True,
        default=lambda self: date.today()
    )

    file_data = fields.Binary(string='Archivo', readonly=True)
    file_name = fields.Char(string='Nombre del Archivo', readonly=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('generated', 'Generado'),
    ], default='draft')

    # Resumen
    record_count = fields.Integer(string='Registros', readonly=True)
    total_amount = fields.Monetary(string='Monto Total', readonly=True, currency_field='currency_id')
    total_itbis = fields.Monetary(string='Total ITBIS', readonly=True, currency_field='currency_id')

    # Resumen 606 específico
    total_itbis_retenido = fields.Monetary(string='ITBIS Retenido', readonly=True, currency_field='currency_id')
    total_isr_retenido = fields.Monetary(string='ISR Retenido', readonly=True, currency_field='currency_id')

    # IR-17
    ir17_total_isr = fields.Monetary(string='Total Retención ISR', readonly=True, currency_field='currency_id')
    ir17_total_itbis = fields.Monetary(string='Total Retención ITBIS', readonly=True, currency_field='currency_id')
    ir17_total = fields.Monetary(string='Total a Pagar DGII', readonly=True, currency_field='currency_id')

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.onchange('date_from')
    def _onchange_date_from(self):
        """Auto-completar fecha hasta al fin del mes"""
        if self.date_from:
            if self.date_from.month == 12:
                last_day = self.date_from.replace(day=31)
            else:
                next_month = self.date_from.replace(month=self.date_from.month + 1, day=1)
                last_day = next_month - timedelta(days=1)
            self.date_to = last_day

    # =========================================
    # MÉTODOS AUXILIARES DE FORMATO
    # =========================================

    def _format_amount(self, amount):
        """Formatear monto - DGII requiere vacío si es 0"""
        if not amount or amount == 0:
            return ''
        return '{:.2f}'.format(abs(amount))

    def _format_amount_zero(self, amount):
        """Formatear monto - Muestra 0.00 si es cero (para columnas requeridas)"""
        return '{:.2f}'.format(abs(amount) if amount else 0)

    def _format_amount_required(self, amount):
        """Formatear monto (siempre muestra valor)"""
        return '{:.2f}'.format(abs(amount) if amount else 0)

    def _get_rnc_type(self, vat):
        """Obtener tipo de identificación: 1=RNC, 2=Cédula, 3=Pasaporte"""
        if not vat:
            return '3'
        vat_clean = vat.replace('-', '').replace(' ', '')
        if len(vat_clean) == 9:
            return '1'  # RNC
        elif len(vat_clean) == 11:
            return '2'  # Cédula
        return '3'  # Pasaporte

    def _clean_rnc(self, vat):
        """Limpiar RNC/Cédula"""
        if not vat:
            return ''
        return vat.replace('-', '').replace(' ', '')

    def _pad_ncf(self, ncf, length=11):
        """Formatear NCF a longitud fija"""
        if not ncf:
            return ''
        return (ncf or '')[:length]

    def _pad_ncf_modified(self, ncf):
        """Formatear NCF modificado (19 caracteres para e-CF)"""
        if not ncf:
            return ''
        return ncf.ljust(19)[:19]

    def _format_date(self, dt):
        """Formatear fecha YYYYMMDD"""
        if not dt:
            return ''
        return dt.strftime('%Y%m%d')

    def _validate_tipo_bienes(self, tipo):
        """Validar tipo de bienes/servicios"""
        valid_tipos = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11']
        if tipo in valid_tipos:
            return tipo
        return '02'  # Default: Gastos por trabajos

    # =========================================
    # ACCIÓN PRINCIPAL
    # =========================================

    def action_generate_report(self):
        """Generar el reporte seleccionado"""
        self.ensure_one()

        if self.report_type == '606':
            return self._generate_606()
        elif self.report_type == '607':
            return self._generate_607()
        elif self.report_type == '608':
            return self._generate_608()
        elif self.report_type == '609':
            return self._generate_609()
        elif self.report_type == 'ir17':
            return self._generate_ir17()

    # =========================================
    # REPORTE 606 - COMPRAS (CORREGIDO)
    # =========================================

    def _generate_606(self):
        """
        Generar reporte 606 - Compras de Bienes y Servicios
        23 columnas según especificación DGII
        """
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ], order='invoice_date')

        if not invoices:
            raise UserError(_('No hay facturas de compra en el período seleccionado.'))

        lines = []
        total_monto = 0.0
        total_itbis = 0.0
        total_itbis_ret = 0.0
        total_isr_ret = 0.0

        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado
        lines.append(f"606|{rnc}|{period}|{len(invoices)}")

        for inv in invoices:
            # Columna 1: RNC/Cédula del proveedor
            rnc_supplier = self._clean_rnc(inv.partner_id.vat)

            # Para B11 informal, usar cédula del proveedor informal
            if inv.l10n_do_fiscal_type == 'informal':
                rnc_supplier = self._clean_rnc(inv.l10n_do_informal_provider_cedula) or '00000000000'
                tipo_id = '2'  # Cédula
            elif inv.l10n_do_fiscal_type == 'minor_expense':
                # B13 usa RNC de la propia empresa
                rnc_supplier = self._clean_rnc(self.company_id.vat)
                tipo_id = '1'  # RNC
            elif rnc_supplier:
                tipo_id = self._get_rnc_type(inv.partner_id.vat)
            else:
                rnc_supplier = '00000000000'
                tipo_id = '2'

            # Columna 3: Tipo de Bienes/Servicios
            tipo_bienes = self._validate_tipo_bienes(
                inv.l10n_do_purchase_type or inv.l10n_do_expense_type or '02'
            )

            # Columna 4: NCF
            if inv.l10n_do_fiscal_type in ('informal', 'minor_expense'):
                ncf = self._pad_ncf(inv.l10n_do_ncf_number or '')
            else:
                ncf = self._pad_ncf(inv.l10n_do_vendor_ncf or '')

            # Columna 5: NCF Modificado (para NC)
            ncf_modificado = ''
            if inv.move_type == 'in_refund' and inv.reversed_entry_id:
                ncf_mod = inv.reversed_entry_id.l10n_do_vendor_ncf or ''
                ncf_modificado = self._pad_ncf_modified(ncf_mod)

            # Columna 6: Fecha del comprobante
            fecha_comprobante = self._format_date(inv.invoice_date)

            # Columna 7: Fecha de pago
            fecha_pago = ''
            if inv.payment_state in ('paid', 'in_payment'):
                try:
                    payments = inv._get_reconciled_payments()
                    if payments:
                        pay_date = max(p.date for p in payments)
                        fecha_pago = self._format_date(pay_date)
                except Exception:
                    fecha_pago = fecha_comprobante

            # Columnas 8-9: Monto bienes y servicios
            monto_servicios = abs(inv.l10n_do_606_monto_servicios or 0.0)
            monto_bienes = abs(inv.l10n_do_606_monto_bienes or 0.0)
            
            # Si no hay split, todo va a servicios por defecto
            if monto_bienes == 0 and monto_servicios == 0:
                monto_servicios = abs(inv.amount_untaxed or 0.0)

            # Columna 10: Monto total (base imponible)
            monto_total = monto_bienes + monto_servicios

            # Columna 11: ITBIS Facturado
            itbis_facturado = abs(inv.l10n_do_itbis_facturado or inv.amount_tax or 0.0)

            # Columna 12: ITBIS Retenido
            itbis_retenido = abs(inv.l10n_do_itbis_retenido or inv.l10n_do_total_itbis_retention or 0.0)

            # Columna 13: ITBIS sujeto a proporcionalidad
            itbis_proporcionalidad = abs(inv.l10n_do_itbis_proporcionalidad or 0.0)

            # Columna 14: ITBIS llevado al costo
            itbis_costo = abs(inv.l10n_do_itbis_costo or 0.0)
            
            # Para B13, todo el ITBIS va al costo
            if inv.l10n_do_fiscal_type == 'minor_expense' and itbis_costo == 0:
                itbis_costo = itbis_facturado

            # Columna 15: ITBIS a adelantar
            itbis_adelantar = abs(inv.l10n_do_itbis_adelantar or 0.0)
            if itbis_adelantar == 0 and inv.l10n_do_fiscal_type not in ('informal', 'minor_expense'):
                itbis_adelantar = max(itbis_facturado - itbis_costo - itbis_proporcionalidad, 0)

            # Columna 16: ITBIS percibido en compras
            itbis_percibido = abs(inv.l10n_do_itbis_percibido or 0.0)

            # Columna 17: Tipo de retención en ISR
            tipo_retencion_isr = inv.l10n_do_tipo_retencion_isr or ''
            
            # Columna 18: Monto retención renta (ISR)
            isr_retenido = abs(inv.l10n_do_isr_retenido or inv.l10n_do_total_isr_retention or 0.0)
            if isr_retenido > 0 and not tipo_retencion_isr:
                tipo_retencion_isr = '02'  # Default: Honorarios

            # Columna 19: ISR percibido en compras
            isr_percibido = abs(inv.l10n_do_isr_percibido or 0.0)

            # Columna 20: Impuesto Selectivo al Consumo
            isc = abs(inv.l10n_do_impuesto_selectivo or 0.0)

            # Columna 21: Otros impuestos/tasas
            otros_impuestos = abs(inv.l10n_do_otros_impuestos or 0.0)

            # Columna 22: Monto propina legal
            propina_legal = abs(inv.l10n_do_propina_legal or 0.0)

            # Columna 23: Forma de pago
            forma_pago = inv.l10n_do_forma_pago or ''
            if not forma_pago:
                if inv.payment_state == 'paid':
                    forma_pago = '02'  # Cheque/Transferencia
                elif inv.payment_state == 'not_paid':
                    forma_pago = '04'  # Crédito
                else:
                    forma_pago = '04'

            # Acumuladores
            total_monto += monto_total
            total_itbis += itbis_facturado
            total_itbis_ret += itbis_retenido
            total_isr_ret += isr_retenido

            # Construir línea (23 columnas)
            campos = [
                rnc_supplier,                              # 1 - RNC/Cédula
                tipo_id,                                   # 2 - Tipo ID
                tipo_bienes,                               # 3 - Tipo Bienes/Servicios
                ncf,                                       # 4 - NCF
                ncf_modificado,                            # 5 - NCF Modificado
                fecha_comprobante,                         # 6 - Fecha Comprobante
                fecha_pago,                                # 7 - Fecha Pago
                self._format_amount(monto_servicios),      # 8 - Monto Servicios
                self._format_amount(monto_bienes),         # 9 - Monto Bienes
                self._format_amount_required(monto_total), # 10 - Total
                self._format_amount(itbis_facturado),      # 11 - ITBIS Facturado
                self._format_amount(itbis_retenido),       # 12 - ITBIS Retenido
                self._format_amount(itbis_proporcionalidad), # 13 - ITBIS Proporcionalidad
                self._format_amount(itbis_costo),          # 14 - ITBIS Costo
                self._format_amount(itbis_adelantar),      # 15 - ITBIS Adelantar
                self._format_amount(itbis_percibido),      # 16 - ITBIS Percibido
                tipo_retencion_isr,                        # 17 - Tipo Ret. ISR
                self._format_amount(isr_retenido),         # 18 - ISR Retenido
                self._format_amount(isr_percibido),        # 19 - ISR Percibido
                self._format_amount(isc),                  # 20 - ISC
                self._format_amount(otros_impuestos),      # 21 - Otros Impuestos
                self._format_amount(propina_legal),        # 22 - Propina Legal
                forma_pago,                                # 23 - Forma Pago
            ]
            lines.append('|'.join(campos))

        # Generar archivo
        content = '\n'.join(lines)
        self.file_data = base64.b64encode(content.encode('utf-8'))
        self.file_name = f"DGII_606_{rnc}_{period}.txt"
        self.state = 'generated'
        self.record_count = len(invoices)
        self.total_amount = total_monto
        self.total_itbis = total_itbis
        self.total_itbis_retenido = total_itbis_ret
        self.total_isr_retenido = total_isr_ret

        return self._return_wizard()

    # =========================================
    # REPORTE 607 - VENTAS
    # =========================================

    def _generate_607(self):
        """
        Generar reporte 607 - Ventas de Bienes y Servicios
        23 columnas según especificación DGII
        """
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            ('l10n_do_ncf_number', '!=', False),
        ], order='invoice_date')

        if not invoices:
            raise UserError(_('No hay facturas de venta con NCF en el período seleccionado.'))

        lines = []
        total_monto = 0.0
        total_itbis = 0.0

        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado
        lines.append(f"607|{rnc}|{period}|{len(invoices)}")

        for inv in invoices:
            # Columna 1: RNC/Cédula del cliente
            rnc_client = self._clean_rnc(inv.partner_id.vat)

            # Columna 2: Tipo de identificación
            if rnc_client:
                tipo_id = self._get_rnc_type(inv.partner_id.vat)
            else:
                tipo_id = '3'  # Sin identificación
                rnc_client = ''

            # Columna 3: NCF
            ncf = self._pad_ncf(inv.l10n_do_ncf_number or '')

            # Columna 4: NCF Modificado (para NC)
            ncf_modificado = ''
            if inv.move_type == 'out_refund':
                ncf_origin = inv.l10n_do_ncf_origin or ''
                ncf_modificado = self._pad_ncf_modified(ncf_origin)

            # Columna 5: Tipo de ingreso
            tipo_ingreso = '01'  # Ingresos por operaciones
            ncf_type = inv.l10n_do_ncf_type_id
            if ncf_type and ncf_type.code in ('16',):  # Exportación
                tipo_ingreso = '02'

            # Columna 6: Fecha del comprobante
            fecha_comprobante = self._format_date(inv.invoice_date)

            # Columna 7: Fecha de retención (solo si aplica)
            fecha_retencion = ''
            if inv.l10n_do_is_credit_sale and inv.l10n_do_retention_date:
                fecha_retencion = self._format_date(inv.l10n_do_retention_date)

            # Columna 8: Monto facturado
            monto_facturado = abs(inv.amount_untaxed)

            # Columna 9: ITBIS Facturado
            itbis_facturado = abs(inv.amount_tax)

            # Columnas 10-16: Retenciones por terceros
            itbis_retenido_terceros = abs(inv.l10n_do_third_party_retention_itbis or 0.0)
            itbis_percibido = 0.0
            retencion_renta_terceros = abs(inv.l10n_do_third_party_retention_isr or 0.0)
            isr_percibido = 0.0
            isc = 0.0
            otros_impuestos = 0.0
            propina_legal = 0.0

            # Columnas 17-23: Formas de pago
            efectivo = abs(inv.l10n_do_payment_cash or 0.0)
            cheque = abs(inv.l10n_do_payment_bank or 0.0)
            tarjeta = abs(inv.l10n_do_payment_card or 0.0)
            credito = abs(inv.l10n_do_payment_credit or 0.0)
            bonos = abs(inv.l10n_do_payment_bond or 0.0)
            permuta = abs(inv.l10n_do_payment_swap or 0.0)
            otras = abs(inv.l10n_do_payment_other or 0.0)

            monto_total = abs(inv.amount_total)

            # Si no hay formas de pago específicas, usar default
            total_formas = efectivo + cheque + tarjeta + credito + bonos + permuta + otras
            if total_formas == 0:
                if inv.payment_state == 'paid':
                    cheque = monto_total
                elif inv.payment_state == 'not_paid':
                    credito = monto_total
                elif inv.payment_state == 'partial':
                    pagado = monto_total - abs(inv.amount_residual)
                    cheque = pagado
                    credito = abs(inv.amount_residual)
                else:
                    credito = monto_total

            # Acumuladores
            total_monto += monto_facturado
            total_itbis += itbis_facturado

            # Construir línea (23 columnas)
            campos = [
                rnc_client,                                    # 1
                tipo_id,                                       # 2
                ncf,                                           # 3
                ncf_modificado,                                # 4
                tipo_ingreso,                                  # 5
                fecha_comprobante,                             # 6
                fecha_retencion,                               # 7
                self._format_amount_required(monto_facturado), # 8
                self._format_amount(itbis_facturado),          # 9
                self._format_amount(itbis_retenido_terceros),  # 10
                self._format_amount(itbis_percibido),          # 11
                self._format_amount(retencion_renta_terceros), # 12
                self._format_amount(isr_percibido),            # 13
                self._format_amount(isc),                      # 14
                self._format_amount(otros_impuestos),          # 15
                self._format_amount(propina_legal),            # 16
                self._format_amount(efectivo),                 # 17
                self._format_amount(cheque),                   # 18
                self._format_amount(tarjeta),                  # 19
                self._format_amount(credito),                  # 20
                self._format_amount(bonos),                    # 21
                self._format_amount(permuta),                  # 22
                self._format_amount(otras),                    # 23
            ]
            lines.append('|'.join(campos))

        # Generar archivo
        content = '\n'.join(lines)
        self.file_data = base64.b64encode(content.encode('utf-8'))
        self.file_name = f"DGII_607_{rnc}_{period}.txt"
        self.state = 'generated'
        self.record_count = len(invoices)
        self.total_amount = total_monto
        self.total_itbis = total_itbis

        return self._return_wizard()

    # =========================================
    # REPORTE 608 - ANULACIONES
    # =========================================

    def _generate_608(self):
        """
        Generar reporte 608 - Comprobantes Anulados
        3 columnas según especificación DGII
        """
        # Buscar facturas canceladas o con estado anulado
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            '|',
            ('state', '=', 'cancel'),
            ('l10n_do_fiscal_status', '=', 'annulled'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            ('l10n_do_ncf_number', '!=', False),
        ], order='invoice_date')

        lines = []
        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado
        lines.append(f"608|{rnc}|{period}|{len(invoices)}")

        for inv in invoices:
            # Columna 1: NCF
            ncf = self._pad_ncf(inv.l10n_do_ncf_number or '')

            # Columna 2: Fecha
            fecha = self._format_date(inv.invoice_date)

            # Columna 3: Tipo de anulación
            tipo_anulacion = '05'  # Default: Corrección de información

            campos = [ncf, fecha, tipo_anulacion]
            lines.append('|'.join(campos))

        # Generar archivo
        content = '\n'.join(lines)
        self.file_data = base64.b64encode(content.encode('utf-8'))
        self.file_name = f"DGII_608_{rnc}_{period}.txt"
        self.state = 'generated'
        self.record_count = len(invoices)

        return self._return_wizard()

    # =========================================
    # REPORTE 609 - PAGOS AL EXTERIOR
    # =========================================

    def _generate_609(self):
        """
        Generar reporte 609 - Pagos al Exterior
        13 columnas según especificación DGII
        """
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            '|',
            ('l10n_do_fiscal_type', '=', 'exterior'),
            '&',
            ('partner_id.country_id', '!=', False),
            ('partner_id.country_id.code', '!=', 'DO'),
        ], order='invoice_date')

        if not invoices:
            raise UserError(_('No hay pagos al exterior en el período seleccionado.'))

        lines = []
        total_monto = 0.0
        total_isr = 0.0
        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado
        lines.append(f"609|{rnc}|{period}|{len(invoices)}")

        for inv in invoices:
            # Columna 1: Razón Social
            razon_social = (inv.partner_id.name or '')[:50]

            # Columna 2: Tipo de identificación (1=PF, 2=PJ)
            tipo_id = '2' if inv.partner_id.company_type == 'company' else '1'

            # Columna 3: Identificación tributaria
            id_tributaria = self._clean_rnc(inv.partner_id.vat) or 'N/A'

            # Columna 4: País
            pais = inv.partner_id.country_id.code or 'US'

            # Columna 5: Tipo de servicio
            tipo_servicio = inv.l10n_do_exterior_service_type or '02'

            # Columna 6: Detalle del servicio
            detalle_servicio = tipo_servicio

            # Columna 7: Parte relacionada (0=No, 1=Sí)
            parte_relacionada = '0'

            # Columna 8: Número del documento
            numero_doc = (inv.ref or inv.name or '')[:30]

            # Columna 9: Fecha del documento
            fecha_doc = self._format_date(inv.invoice_date)

            # Columna 10: Monto pagado
            monto = abs(inv.amount_total)

            # Columna 11: Fecha de retención
            fecha_retencion = fecha_doc

            # Columna 12: Renta presunta
            renta_presunta = monto

            # Columna 13: ISR retenido
            isr_retenido = abs(inv.l10n_do_total_isr_retention or 0.0)
            if isr_retenido == 0:
                # Por defecto 27% para exterior
                isr_retenido = monto * 0.27

            total_monto += monto
            total_isr += isr_retenido

            campos = [
                razon_social,                              # 1
                tipo_id,                                   # 2
                id_tributaria,                             # 3
                pais,                                      # 4
                tipo_servicio,                             # 5
                detalle_servicio,                          # 6
                parte_relacionada,                         # 7
                numero_doc,                                # 8
                fecha_doc,                                 # 9
                self._format_amount_required(monto),       # 10
                fecha_retencion,                           # 11
                self._format_amount_required(renta_presunta),  # 12
                self._format_amount_required(isr_retenido),    # 13
            ]
            lines.append('|'.join(campos))

        # Generar archivo
        content = '\n'.join(lines)
        self.file_data = base64.b64encode(content.encode('utf-8'))
        self.file_name = f"DGII_609_{rnc}_{period}.txt"
        self.state = 'generated'
        self.record_count = len(invoices)
        self.total_amount = total_monto
        self.total_isr_retenido = total_isr

        return self._return_wizard()

    # =========================================
    # REPORTE IR-17 - RESUMEN RETENCIONES
    # =========================================

    def _generate_ir17(self):
        """
        Generar resumen IR-17 de Retenciones
        Formato interno para control (no es archivo DGII oficial)
        """
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ], order='invoice_date')

        # Filtrar solo las que tienen retenciones
        invoices_ret = invoices.filtered(
            lambda i: (i.l10n_do_total_isr_retention or 0) > 0 or
                      (i.l10n_do_total_itbis_retention or 0) > 0 or
                      (i.l10n_do_isr_retenido or 0) > 0 or
                      (i.l10n_do_itbis_retenido or 0) > 0
        )

        if not invoices_ret:
            raise UserError(_('No hay facturas con retenciones en el período seleccionado.'))

        lines = []
        total_isr = 0.0
        total_itbis = 0.0
        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado estilo tabla
        lines.append('=' * 120)
        lines.append(f'RESUMEN IR-17 - RETENCIONES DEL PERÍODO {period}')
        lines.append(f'Empresa: {self.company_id.name}')
        lines.append(f'RNC: {rnc}')
        lines.append('=' * 120)
        lines.append('')
        lines.append('RNC Proveedor    | Proveedor                        | NCF           | Fecha      | Base       | ITBIS     | Ret.ISR   | Ret.ITBIS | Tipo')
        lines.append('-' * 120)

        for inv in invoices_ret:
            isr = abs(inv.l10n_do_total_isr_retention or inv.l10n_do_isr_retenido or 0)
            itbis_ret = abs(inv.l10n_do_total_itbis_retention or inv.l10n_do_itbis_retenido or 0)
            total_isr += isr
            total_itbis += itbis_ret

            tipo_ret = inv.l10n_do_tipo_retencion_isr or ''
            rnc_prov = self._clean_rnc(inv.partner_id.vat)
            
            # Para B11 usar cédula
            if inv.l10n_do_fiscal_type == 'informal':
                rnc_prov = self._clean_rnc(inv.l10n_do_informal_provider_cedula) or ''

            ncf = inv.l10n_do_vendor_ncf or inv.l10n_do_ncf_number or ''

            line = f'{rnc_prov:<16} | {inv.partner_id.name[:32]:<32} | {ncf:<13} | {inv.invoice_date} | {inv.amount_untaxed:>10.2f} | {inv.amount_tax:>9.2f} | {isr:>9.2f} | {itbis_ret:>9.2f} | {tipo_ret}'
            lines.append(line)

        # Resumen
        lines.extend([
            '',
            '-' * 120,
            f'TOTALES                                                                                          | {total_isr:>9.2f} | {total_itbis:>9.2f} |',
            '=' * 120,
            '',
            'RESUMEN PARA DECLARACIÓN IR-17:',
            '-' * 40,
            f'  Retención ISR:           RD$ {total_isr:,.2f}',
            f'  Retención ITBIS:         RD$ {total_itbis:,.2f}',
            f'  ----------------------------------------',
            f'  TOTAL A PAGAR DGII:      RD$ {total_isr + total_itbis:,.2f}',
            '',
            f'  Cantidad de Facturas: {len(invoices_ret)}',
            '=' * 120,
        ])

        # Generar archivo
        content = '\n'.join(lines)
        self.file_data = base64.b64encode(content.encode('utf-8'))
        self.file_name = f"IR17_Resumen_{rnc}_{period}.txt"
        self.state = 'generated'
        self.record_count = len(invoices_ret)
        self.ir17_total_isr = total_isr
        self.ir17_total_itbis = total_itbis
        self.ir17_total = total_isr + total_itbis

        return self._return_wizard()

    # =========================================
    # MÉTODOS AUXILIARES
    # =========================================

    def _return_wizard(self):
        """Retornar el wizard actualizado"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_download(self):
        """Descargar el archivo generado"""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('Primero debe generar el reporte.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model={self._name}&id={self.id}&field=file_data&filename_field=file_name&download=true',
            'target': 'self',
        }

    def action_reset(self):
        """Resetear para generar otro reporte"""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'file_data': False,
            'file_name': False,
            'record_count': 0,
            'total_amount': 0,
            'total_itbis': 0,
            'total_itbis_retenido': 0,
            'total_isr_retenido': 0,
            'ir17_total_isr': 0,
            'ir17_total_itbis': 0,
            'ir17_total': 0,
        })
        return self._return_wizard()