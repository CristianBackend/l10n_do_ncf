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

    # Longitudes de un comprobante en los formatos 606/607/608: 11 (serie B),
    # 13 (e-CF, Aviso 24 de abril 2019) y 19 (NCF anterior a mayo 2018).
    # Instructivo 606 (julio 2025), casillas 4 y 5; instructivo 607, casillas 3 y 4.
    NCF_LENGTHS = (11, 13, 19)

    def _ncf_checked(self, pending, move, ncf, what):
        """El comprobante tal cual, o '' y un error en "Pendientes de
        completar" si su longitud no es válida. Nunca se corta."""
        ncf = (ncf or '').strip().upper()
        if ncf and len(ncf) not in self.NCF_LENGTHS:
            self._pending(pending, move, _(
                'ERROR: %(what)s %(ncf)s tiene %(n)s caracteres (deben ser 11, 13 o 19)',
                what=what, ncf=ncf, n=len(ncf)))
            return ''
        return ncf

    def _tax_amounts(self, move, pending):
        """ITBIS, ISC, otros impuestos y propina del asiento, en DOP.

        Salen de las líneas de impuesto (las retenciones, negativas, no
        cuentan). Cada impuesto dice su clase en "Clase DGII"; uno sin clase
        cuyo porcentaje es 18 o 16 es ITBIS (las dos tasas del ITBIS), y uno
        de tasa 0 marcado como ITBIS 0 %/Exento también. Cualquier otro sin
        clase queda pendiente: no se adivina en qué casilla va.
        Los importes escritos a mano en la factura (ISC, otros, propina)
        mandan sobre los calculados.
        """
        totals = {'itbis': 0.0, 'isc': 0.0, 'other': 0.0, 'tip': 0.0}
        unknown = set()
        for line in move.line_ids.filtered(lambda l: l.tax_line_id and l.tax_line_id.amount > 0):
            tax = line.tax_line_id
            kind = tax.dgii_tax_kind
            if not kind and tax.amount_type == 'percent' and tax.amount in (18.0, 16.0):
                kind = 'itbis'
            if not kind:
                unknown.add(tax.name)
                continue
            totals[kind] += abs(line.balance)
        for name in sorted(unknown):
            self._pending(pending, move, _(
                'el impuesto "%s" no tiene "Clase DGII" (ITBIS, ISC, propina u otros)', name))
        manual = {
            'isc': move.l10n_do_impuesto_selectivo,
            'other': move.l10n_do_otros_impuestos,
            'tip': move.l10n_do_propina_legal,
        }
        for kind, amount in manual.items():
            if amount:
                totals[kind] = abs(self._to_dop(move, amount))
        return totals

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

    def _write_file(self, report, lines, rnc, period, extension='txt'):
        """Guarda el archivo como lo genera la herramienta oficial de la DGII.

        Las cuatro herramientas (606 versión 2025, 607 2023.1.1, 608 2018.2.1 y
        609 2018.5.0) escriben cada línea con "Print #1", que termina en CRLF,
        y la última con "Print #1, ...;", sin salto final. El nombre es
        DGII_F_<formato>_<RNC>_<período>, con extensión .TXT en el 606 y .txt
        en los demás. La codificación es Windows-1252, la de "Print #" en
        Windows; cada registro ya pasó por _cp1252_fields, así que aquí no se
        reemplaza ningún carácter.
        """
        content = '\r\n'.join(lines)
        self.file_data = base64.b64encode(content.encode('cp1252'))
        self.file_name = 'DGII_F_%s_%s_%s.%s' % (report, rnc, period, extension)

    def _cp1252_fields(self, pending, move, campos):
        """Los campos del registro, comprobando que existen en Windows-1252.

        Un campo con un carácter que no existe en esa codificación no se
        reemplaza en silencio: va vacío y el registro queda pendiente, con el
        texto y los caracteres que sobran, para corregirlo en el origen.
        """
        result = []
        for value in campos:
            try:
                value.encode('cp1252')
            except UnicodeEncodeError:
                bad = []
                for char in value:
                    try:
                        char.encode('cp1252')
                    except UnicodeEncodeError:
                        if char not in bad:
                            bad.append(char)
                self._pending(pending, move, _(
                    '"%(text)s" tiene caracteres que no existen en Windows-1252 (%(chars)s): '
                    'corríjalo en el documento o el contacto',
                    text=value, chars=' '.join(bad)))
                value = ''
            result.append(value)
        return result

    @staticmethod
    def _pending(pending, move, message):
        """Anota un dato que falta: va vacío en el archivo (no se inventa) y se
        lista en "Pendientes de completar"."""
        pending.append('%s: %s' % (move.l10n_do_ncf_number or move.l10n_do_vendor_ncf
                                   or move.ref or move.name, message))

    def _606_tipo_bienes(self, inv):
        """Tipo de bienes y servicios del 606 (Anexo A, casilla 3), o '' si no
        se sabe: el de la factura, o el "Tipo 606" de la cuenta de gasto si
        todas las líneas lo tienen y es el mismo. Nunca uno por defecto."""
        tipo = inv.l10n_do_purchase_type or inv.l10n_do_expense_type
        if tipo:
            return tipo
        codes = set(inv.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product').mapped('account_id.l10n_do_606_expense_type'))
        return codes.pop() if len(codes) == 1 and False not in codes else ''

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
        # Facturas, notas de crédito y de débito de proveedores (Anexo A,
        # casilla 4: "incluyendo las notas de crédito o débito"). Los pagos al
        # exterior (B17/E47) también van en el 606 (instructivo 606, julio 2025,
        # "Remisión de NCF especiales"; preguntas frecuentes e-CF 1.2.29); las
        # demás compras a proveedores del exterior van solo en el 609.
        all_invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ], order='invoice_date')
        invoices = all_invoices.filtered(
            lambda i: i.l10n_do_fiscal_type == 'exterior'
            or not i.partner_id.country_id or i.partner_id.country_id.code == 'DO'
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
                rnc_supplier = self._clean_rnc(inv.l10n_do_informal_provider_cedula)
                tipo_id = '2' if rnc_supplier else ''  # Cédula
            elif inv.l10n_do_fiscal_type in ('minor_expense', 'exterior'):
                # B13/E43 y B17/E47 llevan el RNC o la cédula del encabezado,
                # el de la propia empresa (instructivo 606, julio 2025).
                rnc_supplier = self._clean_rnc(self.company_id.vat)
                tipo_id = self._id_type_by_length(rnc_supplier)
            elif rnc_supplier:
                tipo_id = self._id_type_by_length(rnc_supplier)
            else:
                tipo_id = ''
            if not rnc_supplier:
                # Nunca 00000000000: sin RNC/cédula el registro queda pendiente.
                self._pending(pending, inv, _('falta el RNC o la cédula del proveedor'))
            elif not tipo_id:
                # Herramienta 606 (2025): solo 1 (RNC, 9 dígitos) o 2 (Cédula, 11).
                self._pending(pending, inv, _(
                    'la identificación %s no tiene 9 dígitos (RNC) ni 11 (cédula)') % rnc_supplier)

            # Columna 3: Tipo de Bienes/Servicios
            tipo_bienes = self._606_tipo_bienes(inv)
            if not tipo_bienes:
                self._pending(pending, inv, _(
                    'falta el tipo de bienes y servicios: indíquelo en la factura o en el '
                    '"Tipo 606" de la cuenta de gasto'))

            # Columna 4: NCF (el propio en B11/B13/B17 y sus e-CF; el del
            # proveedor en los demás)
            exterior = inv.l10n_do_fiscal_type == 'exterior'
            if inv.l10n_do_fiscal_type in ('informal', 'minor_expense') or exterior:
                ncf = inv.l10n_do_ncf_number or inv.l10n_do_vendor_ncf
            else:
                ncf = inv.l10n_do_vendor_ncf
            ncf = self._ncf_checked(pending, inv, ncf, _('el NCF'))
            if not ncf:
                self._pending(pending, inv, _('falta el NCF'))

            # Columna 5: NCF modificado por una nota de crédito o de débito
            ncf_modificado = ''
            is_note = inv.move_type == 'in_refund' or inv.l10n_do_is_vendor_debit_note
            if inv.move_type == 'in_refund':
                origin = inv.reversed_entry_id
                ncf_modificado = (inv.l10n_do_ncf_origin or origin.l10n_do_ncf_number
                                  or origin.l10n_do_vendor_ncf)
            elif inv.l10n_do_is_vendor_debit_note:
                ncf_modificado = inv.l10n_do_vendor_debit_ncf_origin
            ncf_modificado = self._ncf_checked(pending, inv, ncf_modificado, _('el NCF modificado'))
            if is_note and not ncf_modificado:
                self._pending(pending, inv, _('falta el NCF que modifica la nota'))

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
            # Bienes y servicios salen del tipo de producto de cada línea (o de lo
            # que se escriba a mano). Si no cubren el monto de la factura, una
            # línea no tiene producto y no se supone que sea un servicio.
            base_dop = abs(self._to_dop(inv, inv.amount_untaxed or 0.0))
            if abs(round(monto_bienes + monto_servicios - base_dop, 2)) > 0.01:
                self._pending(pending, inv, _(
                    'hay líneas sin producto: indique los montos de bienes y de servicios'))

            # Columna 10: Monto total (base imponible)
            monto_total = monto_bienes + monto_servicios

            # Columnas 11, 20, 21 y 22: ITBIS, ISC, otros impuestos y propina,
            # cada uno en su casilla (Anexo A: los montos van "sin incluir
            # ITBIS, ISC, propina, otros"). Ya están en DOP (balance).
            taxes = self._tax_amounts(inv, pending)
            itbis_facturado = taxes['itbis']

            # Columna 12: ITBIS Retenido (CONVERTIDO A DOP)
            itbis_retenido = abs(self._to_dop(inv, inv.l10n_do_itbis_retenido or inv.l10n_do_total_itbis_retention or 0.0))

            # Columna 13: ITBIS sujeto a proporcionalidad (CONVERTIDO A DOP)
            itbis_proporcionalidad = abs(self._to_dop(inv, inv.l10n_do_itbis_proporcionalidad or 0.0))

            # Columna 14: ITBIS llevado al costo (CONVERTIDO A DOP)
            itbis_costo = abs(self._to_dop(inv, inv.l10n_do_itbis_costo or 0.0))

            # Para B13, todo el ITBIS va al costo
            if inv.l10n_do_fiscal_type == 'minor_expense' and itbis_costo == 0:
                itbis_costo = itbis_facturado

            # Columna 15: ITBIS por adelantar = facturado - llevado al costo
            # (Anexo A casilla 15; instructivo 606 casilla 15; la herramienta
            # 606 lo recalcula igual: ItbisFacturado - ItbisAgregado).
            itbis_adelantar = max(round(itbis_facturado - itbis_costo, 2), 0.0)

            # Columna 16: ITBIS percibido en compras (CONVERTIDO A DOP)
            itbis_percibido = abs(self._to_dop(inv, inv.l10n_do_itbis_percibido or 0.0))

            # Columna 17: Tipo de retención en ISR
            tipo_retencion_isr = inv._l10n_do_isr_retention_type() or ''

            # Columna 18: Monto retención renta (ISR) (CONVERTIDO A DOP)
            isr_retenido = abs(self._to_dop(inv, inv.l10n_do_isr_retenido or inv.l10n_do_total_isr_retention or 0.0))
            if isr_retenido > 0 and not tipo_retencion_isr:
                self._pending(pending, inv, _(
                    'falta el tipo de retención de ISR: indíquelo en el impuesto de retención '
                    '("Tipo de retención ISR (606)")'))

            # Columna 19: ISR percibido en compras (CONVERTIDO A DOP)
            isr_percibido = abs(self._to_dop(inv, inv.l10n_do_isr_percibido or 0.0))

            isc = taxes['isc']
            otros_impuestos = taxes['other']
            propina_legal = taxes['tip']

            # B17/E47: el instructivo 606 (julio 2025) dice que no llevan ITBIS
            # retenido, proporcionalidad, ITBIS al costo, ISR percibido, ISC,
            # otros impuestos ni propina.
            if exterior:
                itbis_retenido = itbis_proporcionalidad = itbis_costo = 0.0
                isr_percibido = isc = otros_impuestos = propina_legal = 0.0

            # Columna 23: Forma de pago
            # Del pago real (diario del pago, nota de crédito aplicada o saldo a
            # crédito); si no se puede saber, pendiente.
            forma_pago = inv._l10n_do_payment_form_code() or ''
            if not forma_pago:
                self._pending(pending, inv, _(
                    'no se puede saber la forma de pago: configure "Forma de pago DGII" '
                    'en el diario del pago'))

            # Instructivo 606 (julio 2025), casillas 12, 17 y 18: con ITBIS
            # retenido, tipo o monto de retención de ISR, la fecha de pago
            # (casilla 7) es obligatoria.
            if not fecha_pago and (itbis_retenido or tipo_retencion_isr or isr_retenido):
                self._pending(pending, inv, _(
                    'tiene retenciones pero no fecha de pago (casilla 7): registre el pago'))

            # Acumuladores: una nota de crédito resta (herramienta 606 2025,
            # CalcularMontoTotal).
            sign = -1 if inv.move_type == 'in_refund' else 1
            total_monto += sign * monto_total
            total_itbis += sign * itbis_facturado
            total_itbis_ret += sign * itbis_retenido
            total_isr_ret += sign * isr_retenido

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
            lines.append('|'.join(self._cp1252_fields(pending, inv, campos)))

        # Generar archivo
        self._write_file('606', lines, rnc, period, extension='TXT')
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
        # Facturas, notas de débito y notas de crédito (Anexo B, casilla 3).
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
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
            # Columna 4: NCF modificado por una nota de crédito o de débito
            is_credit_note = inv.move_type == 'out_refund'
            is_note = is_credit_note or inv.l10n_do_is_debit_note
            origin = self.env['account.move']
            ncf_modificado = ''
            if is_credit_note:
                origin = inv.l10n_do_origin_move_id or inv.reversed_entry_id
                ncf_modificado = inv.l10n_do_ncf_origin or origin.l10n_do_ncf_number
            elif inv.l10n_do_is_debit_note:
                origin = inv.l10n_do_debit_origin_move_id
                ncf_modificado = inv.l10n_do_debit_ncf_origin or origin.l10n_do_ncf_number
            ncf_modificado = self._ncf_checked(pending, inv, ncf_modificado, _('el NCF modificado'))
            if is_note and not ncf_modificado:
                self._pending(pending, inv, _('falta el NCF que modifica la nota'))

            # 1 RNC, 2 Cédula, 3 Pasaporte o ID tributaria (instructivo 607,
            # casilla 2). Una nota sobre una factura de consumo menor de
            # RD$250,000 no necesita identificación (herramienta 607 2023.1.1,
            # ValidarIdentificacion); en los demás casos, sin ella queda pendiente.
            id_optional = (
                is_note and ncf_modificado[-10:-8] == '02' and origin
                and abs(self._to_dop(origin, origin.amount_total)) < self.CONSUMER_607_THRESHOLD)
            if rnc_client:
                tipo_id = self._get_rnc_type(inv.partner_id.vat)
            else:
                tipo_id = ''
                if not id_optional:
                    self._pending(pending, inv, _('falta el RNC, la cédula o el ID del cliente'))

            # Columna 3: NCF
            ncf = self._ncf_checked(pending, inv, inv.l10n_do_ncf_number, _('el NCF'))

            # Columna 5: Tipo de ingreso
            # El mismo dato que el TipoIngresos del e-CF (Anexo B, casilla 5).
            # Una nota lleva el de la factura que modifica (la nota e-CF no lo
            # declara: E33/E34 usan 01).
            income = ((origin.l10n_do_ecf_income_type if is_note else False)
                      or inv.l10n_do_ecf_income_type)
            # La herramienta 607 (2023.1.1) escribe un dígito: Mid(celda, 2, 1)
            # sobre "01 - Ingresos por ...", es decir "1". Lo mismo aquí.
            tipo_ingreso = income or ''
            if not tipo_ingreso:
                self._pending(pending, inv, _('falta el tipo de ingreso'))

            # Columna 6: Fecha del comprobante
            fecha_comprobante = self._format_date(inv.invoice_date)

            # Columna 7: Fecha de retención (solo si aplica)
            fecha_retencion = self._format_date(inv.l10n_do_retention_date)

            # Columna 8: Monto facturado (CONVERTIDO A DOP)
            monto_facturado = abs(self._to_dop(inv, inv.amount_untaxed))

            # Columnas 9, 14, 15 y 16: ITBIS, ISC, otros impuestos y propina,
            # cada uno en su casilla (ya en DOP).
            taxes = self._tax_amounts(inv, pending)
            itbis_facturado = taxes['itbis']

            # Columnas 10-16: Retenciones por terceros (CONVERTIDAS A DOP)
            itbis_retenido_terceros = abs(self._to_dop(inv, inv.l10n_do_third_party_retention_itbis or 0.0))
            itbis_percibido = 0.0
            retencion_renta_terceros = abs(self._to_dop(inv, inv.l10n_do_third_party_retention_isr or 0.0))
            isr_percibido = 0.0
            isc = taxes['isc']
            otros_impuestos = taxes['other']
            propina_legal = taxes['tip']

            # Columnas 17-23: Formas de pago (CONVERTIDAS A DOP)
            efectivo = abs(self._to_dop(inv, inv.l10n_do_payment_cash or 0.0))
            cheque = abs(self._to_dop(inv, inv.l10n_do_payment_bank or 0.0))
            tarjeta = abs(self._to_dop(inv, inv.l10n_do_payment_card or 0.0))
            credito = abs(self._to_dop(inv, inv.l10n_do_payment_credit or 0.0))
            bonos = abs(self._to_dop(inv, inv.l10n_do_payment_bond or 0.0))
            permuta = abs(self._to_dop(inv, inv.l10n_do_payment_swap or 0.0))
            otras = abs(self._to_dop(inv, inv.l10n_do_payment_other or 0.0))

            monto_total = abs(self._to_dop(inv, inv.amount_total))

            # Sin importes por forma de pago en la factura, se toman de los
            # pagos reales; lo que no tiene forma conocida queda pendiente.
            # Una nota de crédito no lleva formas de pago (herramienta 607:
            # la suma de las casillas 17-23 puede ser 0 solo en un B04).
            total_formas = efectivo + cheque + tarjeta + credito + bonos + permuta + otras
            if total_formas == 0 and not is_credit_note:
                amounts, unknown = inv._l10n_do_payment_amounts()
                efectivo = amounts.get('01', 0.0)
                cheque = amounts.get('02', 0.0)
                tarjeta = amounts.get('03', 0.0)
                credito = amounts.get('04', 0.0)
                permuta = amounts.get('05', 0.0)
                if unknown or amounts.get('06'):
                    self._pending(pending, inv, _(
                        'parte del cobro no tiene forma de pago conocida (diario sin "Forma '
                        'de pago DGII" o nota de crédito aplicada): indique los importes por '
                        'forma de pago en la factura'))

            # Instructivo 607 (septiembre 2020), casillas 10 y 12: con ITBIS o
            # ISR retenido por terceros, la fecha de retención es obligatoria.
            if not fecha_retencion and (itbis_retenido_terceros or retencion_renta_terceros):
                self._pending(pending, inv, _(
                    'tiene retenciones de terceros pero no fecha de retención (casilla 7)'))

            # Acumuladores: una nota de crédito resta (herramienta 607).
            sign = -1 if is_credit_note else 1
            total_monto += sign * monto_facturado
            total_itbis += sign * itbis_facturado

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
            lines.append('|'.join(self._cp1252_fields(pending, inv, campos)))

        # Generar archivo
        self._write_file('607', lines, rnc, period)
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
        # Por la fecha en que se anuló (Anexo C, casilla 2). Una anulación
        # anterior a este campo no tiene fecha: entra por la de la factura y
        # queda pendiente.
        invoices = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'cancel'),
            ('l10n_do_ncf_number', '!=', False),
            '|',
            '&', ('l10n_do_annulment_date', '>=', self.date_from),
            ('l10n_do_annulment_date', '<=', self.date_to),
            '&', '&', ('l10n_do_annulment_date', '=', False),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
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
        pending = []
        rnc = self._clean_rnc(self.company_id.vat)
        period = self.date_from.strftime('%Y%m')

        # Encabezado
        lines.append(f"608|{rnc}|{period}|{len(invoices)}")

        for inv in invoices:
            # Columna 1: NCF
            ncf = self._ncf_checked(pending, inv, inv.l10n_do_ncf_number, _('el NCF'))

            # Columna 2: fecha de emisión del comprobante (instructivo 608,
            # septiembre 2020, casilla 2: "la fecha en que fue emitida la
            # factura"; más reciente que el Anexo C, que decía la de anulación).
            # El PERÍODO sí lo decide la fecha de anulación (búsqueda de arriba).
            fecha = self._format_date(inv.invoice_date)
            if not fecha:
                self._pending(pending, inv, _('no tiene fecha de emisión'))
            if not inv.l10n_do_annulment_date:
                self._pending(pending, inv, _(
                    'no tiene fecha de anulación: se incluyó por la fecha de la factura; '
                    'confirme el período en que se anuló'))

            # Columna 3: tipo de anulación (Anexo C, tabla 01-10)
            tipo_anulacion = inv.l10n_do_annulment_type or ''
            if not tipo_anulacion:
                self._pending(pending, inv, _('falta el tipo de anulación'))

            campos = [ncf, fecha, tipo_anulacion]
            lines.append('|'.join(self._cp1252_fields(pending, inv, campos)))

        # Generar archivo
        self._write_file('608', lines, rnc, period)
        self.state = 'generated'
        self.record_count = len(invoices)
        self.pending_message = '\n'.join(pending) or False

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
            # 7. Parte relacionada (A 1): 0 no relacionado, 1 relacionado. Del
            # contacto; la herramienta 609 no admite la casilla en blanco.
            parte_relacionada = partner.l10n_do_609_related_party or ''
            if not parte_relacionada:
                missing.append(_('si el proveedor es parte relacionada (en el contacto)'))
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
            # Antes de las retenciones: con la retención como impuesto de la
            # línea, amount_total ya viene neto.
            monto = abs(self._to_dop(inv, inv._l10n_do_amount_before_retentions()))

            # 11-13. Retención de ISR: la registrada en la factura. Si no hay,
            # el ISR va en 0 y la Renta Presunta (base del ISR retenido, Art.
            # 305) también; sin renta presunta la herramienta no exige fecha.
            isr_retenido = abs(self._to_dop(inv, inv.l10n_do_total_isr_retention or 0.0))
            renta_presunta = abs(self._to_dop(inv, inv._l10n_do_isr_retention_base()))
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
            lines.append('|'.join(self._cp1252_fields(pending, inv, campos)))

        # Generar archivo
        self._write_file('609', lines, rnc, period)
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
            itbis = abs(self._to_dop(inv, inv._l10n_do_billed_tax_amount()))
            total_isr += isr
            total_itbis += itbis_ret

            tipo_ret = inv._l10n_do_isr_retention_type() or ''
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