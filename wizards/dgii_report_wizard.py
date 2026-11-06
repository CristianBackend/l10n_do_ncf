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

Versión: 19.0.1.10.0
- Fix: Conversión automática de montos en moneda extranjera (USD, EUR, etc.) a DOP
       usando la tasa de cambio de la fecha de la factura. Aplica a reportes 606, 607, 609 e IR-17.
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
from datetime import date, timedelta

from ..models.dgii_609_codes import PAIS_CODIGO


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
    pending_message = fields.Text(
        string='Pendientes de completar', readonly=True,
        help='Datos que faltan en las facturas del reporte. Se dejaron vacíos (no se '
             'inventan) y la herramienta de la DGII rechazará esos registros hasta '
             'completarlos.')

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

    def _to_dop(self, invoice, amount):
        """
        Convertir un monto de la moneda de la factura a DOP (moneda de la compañía).

        Usa la tasa con la que la factura quedó ASENTADA, no la que esté hoy en
        res.currency.rate. Son dos cosas distintas: la tabla de tasas cambia con
        el tiempo (se cargan tasas nuevas, se corrigen las viejas), y volver a
        consultarla produce un monto que no coincide con la contabilidad.

        La tasa real de la factura está implícita en sus propios montos:
        amount_total_signed (moneda de compañía) / amount_total (moneda factura).

        Solo si la factura no permite deducirla se recurre a la tabla.
        """
        if not amount:
            return 0.0
        company_currency = invoice.company_id.currency_id
        invoice_currency = invoice.currency_id

        # Si ya está en DOP, no convertir
        if invoice_currency == company_currency:
            return amount

        # Tasa con la que la factura quedó registrada en los libros
        rate = 0.0
        if invoice.amount_total:
            rate = abs(invoice.amount_total_signed) / abs(invoice.amount_total)

        if rate:
            return company_currency.round(amount * rate)

        # Respaldo: factura sin montos (raro) -> tasa de la tabla a su fecha
        conversion_date = invoice.invoice_date or invoice.date or fields.Date.today()
        return invoice_currency._convert(
            amount,
            company_currency,
            invoice.company_id,
            conversion_date,
        )

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

    def _pad_ncf(self, ncf, length=None):
        """
        Formatear NCF/e-CF a su longitud según el tipo.

        NCF fiscal  (B01, B02, ...): 11 caracteres  -> B + 2 + 8
        e-CF        (E31, E32, ...): 13 caracteres  -> E + 2 + 10

        Cortar todo a 11 le quitaba los dos últimos dígitos a cada e-CF.
        """
        if not ncf:
            return ''
        ncf = ncf.strip().upper()
        if length is None:
            length = 13 if ncf.startswith('E') else 11
        return ncf[:length]

    def _pad_ncf_modified(self, ncf):
        """
        Formatear NCF modificado (el comprobante que corrige una NC/ND).

        Es un NCF como cualquier otro: 11 para B, 13 para e-CF. No se rellena
        con espacios, que en un archivo separado por pipes quedan dentro del campo.
        """
        if not ncf:
            return ''
        return self._pad_ncf(ncf)

    def _format_date(self, dt):
        """Formatear fecha YYYYMMDD"""
        if not dt:
            return ''
        return dt.strftime('%Y%m%d')

    # Facturas de consumo: desde el período julio 2018 solo se remiten en el
    # 607 las de RD$250,000.00 o más (Norma General 10-18, citada en el
    # instructivo "Llenado del Formato 607", septiembre 2020).
    CONSUMER_607_THRESHOLD = 250000.0

    @staticmethod
    def _is_ecf(ncf):
        """True si el número es un e-CF (E + 12 caracteres)."""
        return bool(ncf) and ncf.strip().upper().startswith('E')

    def _id_type_by_length(self, number):
        """Tipo de identificación del 606 por su longitud: 1 RNC (9), 2 Cédula
        (11). La herramienta oficial 606 (2025, ValidarTipoIdentificacion)
        solo admite esos dos; cualquier otra longitud queda vacía."""
        return {9: '1', 11: '2'}.get(len(number or ''), '')

    @staticmethod
    def _pending(pending, move, message):
        """Anota un dato que falta: va vacío en el archivo (no se inventa) y se
        lista en "Pendientes de completar"."""
        pending.append('%s: %s' % (move.l10n_do_ncf_number or move.l10n_do_vendor_ncf
                                   or move.ref or move.name, message))

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
        Todos los montos se convierten a DOP usando la tasa de la fecha de la factura.
        """
        # Buscar facturas de compra locales (excluir exterior -> van al 609)
        all_invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'in_invoice'),  # Solo facturas, NO notas de credito de proveedor
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            ('l10n_do_fiscal_type', '!=', 'exterior'),  # Exterior va al 609
        ], order='invoice_date')
        
        # Filtrar: solo proveedores dominicanos o sin pais (asume local)
        invoices = all_invoices.filtered(
            lambda i: not i.partner_id.country_id or i.partner_id.country_id.code == 'DO'
        )

        if not invoices:
            raise UserError(_('No hay facturas de compra locales en el periodo seleccionado. Las compras a proveedores extranjeros van en el reporte 609.'))

        lines = []
        pending = []
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
                # B13 usa el RNC o la cédula de la propia empresa
                rnc_supplier = self._clean_rnc(self.company_id.vat)
                tipo_id = self._id_type_by_length(rnc_supplier)
            elif rnc_supplier:
                tipo_id = self._id_type_by_length(rnc_supplier)
            else:
                rnc_supplier = '00000000000'
                tipo_id = '2'
            if not tipo_id:
                # Herramienta 606 (2025): solo 1 (RNC, 9 dígitos) o 2 (Cédula, 11).
                self._pending(pending, inv, _(
                    'la identificación %s no tiene 9 dígitos (RNC) ni 11 (cédula)') % rnc_supplier)

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
            # Nunca la fecha de la factura: si no hay pago, va vacía.
            fecha_pago = ''
            if inv.payment_state in ('paid', 'in_payment'):
                payments = inv._get_reconciled_payments()
                if payments:
                    fecha_pago = self._format_date(max(p.date for p in payments))

            # Columnas 8-9: Monto bienes y servicios (CONVERTIDOS A DOP)
            monto_servicios = abs(self._to_dop(inv, inv.l10n_do_606_monto_servicios or 0.0))
            monto_bienes = abs(self._to_dop(inv, inv.l10n_do_606_monto_bienes or 0.0))
            
            # Si no hay split, todo va a servicios por defecto
            if monto_bienes == 0 and monto_servicios == 0:
                monto_servicios = abs(self._to_dop(inv, inv.amount_untaxed or 0.0))

            # Columna 10: Monto total (base imponible)
            monto_total = monto_bienes + monto_servicios

            # Columna 11: ITBIS Facturado (CONVERTIDO A DOP)
            itbis_facturado = abs(self._to_dop(inv, inv.l10n_do_itbis_facturado or inv.amount_tax or 0.0))

            # Columna 12: ITBIS Retenido (CONVERTIDO A DOP)
            itbis_retenido = abs(self._to_dop(inv, inv.l10n_do_itbis_retenido or inv.l10n_do_total_itbis_retention or 0.0))

            # Columna 13: ITBIS sujeto a proporcionalidad (CONVERTIDO A DOP)
            itbis_proporcionalidad = abs(self._to_dop(inv, inv.l10n_do_itbis_proporcionalidad or 0.0))

            # Columna 14: ITBIS llevado al costo (CONVERTIDO A DOP)
            itbis_costo = abs(self._to_dop(inv, inv.l10n_do_itbis_costo or 0.0))
            
            # Para B13, todo el ITBIS va al costo
            if inv.l10n_do_fiscal_type == 'minor_expense' and itbis_costo == 0:
                itbis_costo = itbis_facturado

            # Columna 15: ITBIS a adelantar (CONVERTIDO A DOP)
            itbis_adelantar = abs(self._to_dop(inv, inv.l10n_do_itbis_adelantar or 0.0))
            if itbis_adelantar == 0 and inv.l10n_do_fiscal_type not in ('informal', 'minor_expense'):
                itbis_adelantar = max(itbis_facturado - itbis_costo - itbis_proporcionalidad, 0)

            # Columna 16: ITBIS percibido en compras (CONVERTIDO A DOP)
            itbis_percibido = abs(self._to_dop(inv, inv.l10n_do_itbis_percibido or 0.0))

            # Columna 17: Tipo de retención en ISR
            tipo_retencion_isr = inv.l10n_do_tipo_retencion_isr or ''
            
            # Columna 18: Monto retención renta (ISR) (CONVERTIDO A DOP)
            isr_retenido = abs(self._to_dop(inv, inv.l10n_do_isr_retenido or inv.l10n_do_total_isr_retention or 0.0))
            if isr_retenido > 0 and not tipo_retencion_isr:
                tipo_retencion_isr = '02'  # Default: Honorarios

            # Columna 19: ISR percibido en compras (CONVERTIDO A DOP)
            isr_percibido = abs(self._to_dop(inv, inv.l10n_do_isr_percibido or 0.0))

            # Columna 20: Impuesto Selectivo al Consumo (CONVERTIDO A DOP)
            isc = abs(self._to_dop(inv, inv.l10n_do_impuesto_selectivo or 0.0))

            # Columna 21: Otros impuestos/tasas (CONVERTIDO A DOP)
            otros_impuestos = abs(self._to_dop(inv, inv.l10n_do_otros_impuestos or 0.0))

            # Columna 22: Monto propina legal (CONVERTIDO A DOP)
            propina_legal = abs(self._to_dop(inv, inv.l10n_do_propina_legal or 0.0))

            # Columna 23: Forma de pago
            forma_pago = inv.l10n_do_forma_pago or ''
            if not forma_pago:
                if inv.payment_state == 'paid':
                    forma_pago = '02'  # Cheque/Transferencia
                elif inv.payment_state == 'not_paid':
                    forma_pago = '04'  # Crédito
                else:
                    forma_pago = '04'

            # Instructivo 606 (julio 2025), casillas 12, 17 y 18: con ITBIS
            # retenido, tipo o monto de retención de ISR, la fecha de pago
            # (casilla 7) es obligatoria.
            if not fecha_pago and (itbis_retenido or tipo_retencion_isr or isr_retenido):
                self._pending(pending, inv, _(
                    'tiene retenciones pero no fecha de pago (casilla 7): registre el pago'))

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
        self.pending_message = '\n'.join(pending) or False

        return self._return_wizard()

    # =========================================
    # REPORTE 607 - VENTAS
    # =========================================

    def _generate_607(self):
        """
        Generar reporte 607 - Ventas de Bienes y Servicios
        23 columnas según especificación DGII
        Todos los montos se convierten a DOP usando la tasa de la fecha de la factura.
        """
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'out_invoice'),  # Solo facturas, NO notas de crédito (B04)
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            ('l10n_do_ncf_number', '!=', False),
        ], order='invoice_date')
        # - Los e-CF no se remiten en el 607 (Preguntas frecuentes e-CF de la
        #   DGII, 1.4.13).
        # - Facturas de consumo (B02): solo desde RD$250,000.00 (NG 10-18).
        invoices = invoices.filtered(lambda i: not self._is_ecf(i.l10n_do_ncf_number) and not (
            i.l10n_do_ncf_type_id.code == '02'
            and abs(self._to_dop(i, i.amount_total)) < self.CONSUMER_607_THRESHOLD))

        if not invoices:
            raise UserError(_(
                'No hay facturas de venta para el 607 en el período seleccionado. Los e-CF '
                'no se remiten en el 607 y las facturas de consumo solo desde RD$250,000.00.'))

        lines = []
        pending = []
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
            fecha_retencion = self._format_date(inv.l10n_do_retention_date)

            # Columna 8: Monto facturado (CONVERTIDO A DOP)
            monto_facturado = abs(self._to_dop(inv, inv.amount_untaxed))

            # Columna 9: ITBIS Facturado (CONVERTIDO A DOP)
            itbis_facturado = abs(self._to_dop(inv, inv.amount_tax))

            # Columnas 10-16: Retenciones por terceros (CONVERTIDAS A DOP)
            itbis_retenido_terceros = abs(self._to_dop(inv, inv.l10n_do_third_party_retention_itbis or 0.0))
            itbis_percibido = 0.0
            retencion_renta_terceros = abs(self._to_dop(inv, inv.l10n_do_third_party_retention_isr or 0.0))
            isr_percibido = 0.0
            isc = 0.0
            otros_impuestos = 0.0
            propina_legal = 0.0

            # Columnas 17-23: Formas de pago (CONVERTIDAS A DOP)
            efectivo = abs(self._to_dop(inv, inv.l10n_do_payment_cash or 0.0))
            cheque = abs(self._to_dop(inv, inv.l10n_do_payment_bank or 0.0))
            tarjeta = abs(self._to_dop(inv, inv.l10n_do_payment_card or 0.0))
            credito = abs(self._to_dop(inv, inv.l10n_do_payment_credit or 0.0))
            bonos = abs(self._to_dop(inv, inv.l10n_do_payment_bond or 0.0))
            permuta = abs(self._to_dop(inv, inv.l10n_do_payment_swap or 0.0))
            otras = abs(self._to_dop(inv, inv.l10n_do_payment_other or 0.0))

            monto_total = abs(self._to_dop(inv, inv.amount_total))

            # Si no hay formas de pago específicas, usar default
            total_formas = efectivo + cheque + tarjeta + credito + bonos + permuta + otras
            if total_formas == 0:
                if inv.payment_state == 'paid':
                    cheque = monto_total
                elif inv.payment_state == 'not_paid':
                    credito = monto_total
                elif inv.payment_state == 'partial':
                    pagado = monto_total - abs(self._to_dop(inv, inv.amount_residual))
                    cheque = pagado
                    credito = abs(self._to_dop(inv, inv.amount_residual))
                else:
                    credito = monto_total

            # Instructivo 607 (septiembre 2020), casillas 10 y 12: con ITBIS o
            # ISR retenido por terceros, la fecha de retención es obligatoria.
            if not fecha_retencion and (itbis_retenido_terceros or retencion_renta_terceros):
                self._pending(pending, inv, _(
                    'tiene retenciones de terceros pero no fecha de retención (casilla 7)'))

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
        self.pending_message = '\n'.join(pending) or False

        return self._return_wizard()

    # =========================================
    # REPORTE 608 - ANULACIONES
    # =========================================

    def _generate_608(self):
        """
        Generar reporte 608 - Comprobantes Anulados
        3 columnas según especificación DGII
        (No requiere conversión de moneda - solo NCF y fechas)
        """
        # Buscar SOLO facturas canceladas (no entregadas)
        # Las facturas revertidas por NC van al 607, no al 608
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'cancel'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
            ('l10n_do_ncf_number', '!=', False),
        ], order='invoice_date')
        # Los e-CF no van en el 608: se anulan con nota de crédito o con el
        # servicio de anulación (Preguntas frecuentes e-CF de la DGII, 1.4.13).
        invoices = invoices.filtered(lambda i: not self._is_ecf(i.l10n_do_ncf_number))
        if not invoices:
            # Herramienta 608 (2018.2.1): de 1 a 5,000 registros. Sin anulados,
            # se presenta en la Oficina Virtual como "Declaración en cero"
            # (instructivo 608, septiembre 2020).
            raise UserError(_(
                'No hay comprobantes en papel anulados en el período. Un 608 sin '
                'registros no se envía como archivo: preséntelo en la Oficina Virtual '
                'de la DGII como "Declaración en cero".'))

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
        """Formato 609 - Pagos por servicios al exterior.

        Norma General 07-2018, Anexo D: encabezado de 4 campos y detalle de 13
        columnas separadas por "|". Los códigos de Tipo y Detalle del servicio
        y del país son los de la herramienta oficial de la DGII (ver
        models/dgii_609_codes.py). Los montos van en DOP con la tasa con la que
        se asentó la factura.

        Nada se inventa: un dato que falta va vacío y el asistente lo lista
        como pendiente en "Pendientes de completar" (la herramienta de la DGII
        rechazaría ese registro hasta que se complete).
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
        pending = []
        total_monto = 0.0
        total_isr = 0.0
        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado
        lines.append(f"609|{rnc}|{period}|{len(invoices)}")

        for inv in invoices:
            partner = inv.commercial_partner_id
            label = inv.ref or inv.name
            missing = []

            # 1. Razón Social (A 50)
            razon_social = (partner.name or '')[:50]
            # 2. Tipo Id Tributaria (A 1): 1 persona física, 2 persona jurídica
            tipo_id = '2' if partner.is_company else '1'
            # 3. Id Tributaria (A 50)
            id_tributaria = self._clean_rnc(partner.vat)[:50]
            if not id_tributaria:
                missing.append(_('identificación tributaria del proveedor'))
            # 4. País destino (A 3): código ISO 3166 numérico de la lista oficial
            country = partner.country_id
            pais = PAIS_CODIGO.get(country.code or '', '')
            if not country:
                missing.append(_('país del proveedor'))
            elif not pais:
                missing.append(_('el país %s no está en la lista del 609 de la DGII', country.name))
            # 5 y 6. Tipo y Detalle del Servicio Adquirido (A 2 cada uno)
            tipo_servicio = inv.l10n_do_609_service_type or ''
            detalle_servicio = inv.l10n_do_609_service_detail or ''
            if not tipo_servicio:
                missing.append(_('Tipo de Servicio Adquirido'))
            if not detalle_servicio:
                missing.append(_('Detalle del Servicio Adquirido'))
            # 7. Parte relacionada (A 1): 0 no relacionado, 1 relacionado.
            parte_relacionada = '0'
            # 8. Número de documento (A 30): el comprobante de la operación (el
            # e-NCF del pago al exterior, el NCF del proveedor) o el número de
            # factura del proveedor. No el nombre interno de Odoo
            # (BILL/2026/11/0003), que no es un documento y lleva "/", que la
            # herramienta de la DGII no admite.
            numero_doc = (inv.l10n_do_ncf_number or inv.l10n_do_vendor_ncf or inv.ref or '').strip()[:30]
            if not numero_doc:
                missing.append(_('número de documento (comprobante o número de factura del proveedor)'))
            # 9. Fecha documento (AAAAMMDD)
            fecha_doc = self._format_date(inv.invoice_date)
            # 10. Monto facturado (DOP)
            monto = abs(self._to_dop(inv, inv.amount_total))

            # 11-13. Retención de ISR: la registrada en la factura. Si no hay,
            # el ISR va en 0 y la Renta Presunta (base del ISR retenido, Art.
            # 305) también; sin renta presunta la herramienta no exige fecha.
            isr_lines = inv.l10n_do_retention_ids.filtered(
                lambda r: r.retention_type_id.retention_type == 'isr'
                and not r.retention_type_id.is_perceived)
            isr_retenido = abs(self._to_dop(inv, inv.l10n_do_total_isr_retention or 0.0))
            renta_presunta = abs(self._to_dop(inv, sum(isr_lines.mapped('base_amount'))))
            if not isr_retenido:
                pending.append(_('%s: no tiene retención de ISR registrada; se reporta ISR 0.00.', label))
            elif not renta_presunta:
                missing.append(_('base (renta presunta) de la retención de ISR'))
            fecha_retencion = fecha_doc if renta_presunta else ''

            if missing:
                pending.append(_('%(doc)s: falta %(what)s.', doc=label, what=', '.join(missing)))

            total_monto += monto
            total_isr += isr_retenido

            campos = [
                razon_social,                                  # 1
                tipo_id,                                       # 2
                id_tributaria,                                 # 3
                pais,                                          # 4
                tipo_servicio,                                 # 5
                detalle_servicio,                              # 6
                parte_relacionada,                             # 7
                numero_doc,                                    # 8
                fecha_doc,                                     # 9
                self._format_amount_required(monto),           # 10
                fecha_retencion,                               # 11
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
        self.pending_message = '\n'.join(pending) or False

        return self._return_wizard()

    # =========================================
    # REPORTE IR-17 - RESUMEN RETENCIONES
    # =========================================

    def _generate_ir17(self):
        """
        Generar resumen IR-17 de Retenciones
        Formato interno para control (no es archivo DGII oficial)
        Todos los montos se convierten a DOP usando la tasa de la fecha de la factura.
        """
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'in_invoice'),  # Solo facturas, NO notas de crédito de proveedor
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
            # CONVERTIR A DOP
            isr = abs(self._to_dop(inv, inv.l10n_do_total_isr_retention or inv.l10n_do_isr_retenido or 0))
            itbis_ret = abs(self._to_dop(inv, inv.l10n_do_total_itbis_retention or inv.l10n_do_itbis_retenido or 0))
            base = abs(self._to_dop(inv, inv.amount_untaxed))
            itbis = abs(self._to_dop(inv, inv.amount_tax))
            total_isr += isr
            total_itbis += itbis_ret

            tipo_ret = inv.l10n_do_tipo_retencion_isr or ''
            rnc_prov = self._clean_rnc(inv.partner_id.vat)
            
            # Para B11 usar cédula
            if inv.l10n_do_fiscal_type == 'informal':
                rnc_prov = self._clean_rnc(inv.l10n_do_informal_provider_cedula) or ''

            ncf = inv.l10n_do_vendor_ncf or inv.l10n_do_ncf_number or ''

            line = f'{rnc_prov:<16} | {inv.partner_id.name[:32]:<32} | {ncf:<13} | {inv.invoice_date} | {base:>10.2f} | {itbis:>9.2f} | {isr:>9.2f} | {itbis_ret:>9.2f} | {tipo_ret}'
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
            'pending_message': False,
        })
        return self._return_wizard()