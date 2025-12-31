# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: models/dgii_txt_validator.py
# Descripción: Pre-validador de archivos TXT 606/607 antes de envío DGII
# Versión: 19.0.2.3.0

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import date
import re
import logging

_logger = logging.getLogger(__name__)


class L10nDoDGIITxtValidator(models.TransientModel):
    """
    Pre-validador de archivos 606/607 DGII
    
    Valida estructura, formatos y datos antes de generar archivo TXT
    para evitar rechazos de DGII.
    """
    _name = 'l10n_do_ncf.dgii.txt.validator'
    _description = 'Validador TXT 606/607'

    # =========================================
    # REGLAS 606 (Compras)
    # =========================================

    # Columnas 606
    COLS_606 = {
        1: {'name': 'RNC/Cédula', 'length': 11, 'required': True, 'type': 'rnc'},
        2: {'name': 'Tipo ID', 'length': 1, 'required': True, 'type': 'selection', 'values': ['1', '2']},
        3: {'name': 'Tipo Bienes/Servicios', 'length': 2, 'required': True, 'type': 'code_02'},
        4: {'name': 'NCF', 'length': 11, 'required': True, 'type': 'ncf'},
        5: {'name': 'NCF Modificado', 'length': 11, 'required': False, 'type': 'ncf'},
        6: {'name': 'Fecha Comprobante', 'length': 8, 'required': True, 'type': 'date'},
        7: {'name': 'Fecha Pago', 'length': 8, 'required': False, 'type': 'date'},
        8: {'name': 'Monto Servicios', 'length': 12, 'required': True, 'type': 'amount'},
        9: {'name': 'Monto Bienes', 'length': 12, 'required': True, 'type': 'amount'},
        10: {'name': 'Total Facturado', 'length': 12, 'required': True, 'type': 'amount'},
        11: {'name': 'ITBIS Facturado', 'length': 12, 'required': True, 'type': 'amount'},
        12: {'name': 'ITBIS Retenido', 'length': 12, 'required': True, 'type': 'amount'},
        13: {'name': 'ITBIS Proporcionalidad', 'length': 12, 'required': True, 'type': 'amount'},
        14: {'name': 'ITBIS Costo', 'length': 12, 'required': True, 'type': 'amount'},
        15: {'name': 'ITBIS Adelantar', 'length': 12, 'required': True, 'type': 'amount'},
        16: {'name': 'ITBIS Percibido', 'length': 12, 'required': True, 'type': 'amount'},
        17: {'name': 'Tipo Retención ISR', 'length': 2, 'required': False, 'type': 'code_02'},
        18: {'name': 'ISR Retenido', 'length': 12, 'required': True, 'type': 'amount'},
        19: {'name': 'ISR Percibido', 'length': 12, 'required': True, 'type': 'amount'},
        20: {'name': 'Impuesto Selectivo', 'length': 12, 'required': True, 'type': 'amount'},
        21: {'name': 'Otros Impuestos', 'length': 12, 'required': True, 'type': 'amount'},
        22: {'name': 'Propina Legal', 'length': 12, 'required': True, 'type': 'amount'},
        23: {'name': 'Forma Pago', 'length': 2, 'required': True, 'type': 'code_02'},
    }

    # =========================================
    # REGLAS 607 (Ventas)
    # =========================================

    COLS_607 = {
        1: {'name': 'RNC/Cédula', 'length': 11, 'required': False, 'type': 'rnc'},
        2: {'name': 'Tipo ID', 'length': 1, 'required': False, 'type': 'selection', 'values': ['1', '2', '']},
        3: {'name': 'NCF', 'length': 11, 'required': True, 'type': 'ncf'},
        4: {'name': 'NCF Modificado', 'length': 11, 'required': False, 'type': 'ncf'},
        5: {'name': 'Tipo Ingreso', 'length': 2, 'required': True, 'type': 'code_02'},
        6: {'name': 'Fecha Comprobante', 'length': 8, 'required': True, 'type': 'date'},
        7: {'name': 'Fecha Retención', 'length': 8, 'required': False, 'type': 'date'},
        8: {'name': 'Monto Facturado', 'length': 12, 'required': True, 'type': 'amount'},
        9: {'name': 'ITBIS Facturado', 'length': 12, 'required': True, 'type': 'amount'},
        10: {'name': 'ITBIS Retenido Terceros', 'length': 12, 'required': True, 'type': 'amount'},
        11: {'name': 'ITBIS Percibido', 'length': 12, 'required': True, 'type': 'amount'},
        12: {'name': 'ISR Retenido Terceros', 'length': 12, 'required': True, 'type': 'amount'},
        13: {'name': 'ISR Percibido', 'length': 12, 'required': True, 'type': 'amount'},
        14: {'name': 'Impuesto Selectivo', 'length': 12, 'required': True, 'type': 'amount'},
        15: {'name': 'Otros Impuestos', 'length': 12, 'required': True, 'type': 'amount'},
        16: {'name': 'Propina Legal', 'length': 12, 'required': True, 'type': 'amount'},
        17: {'name': 'Efectivo', 'length': 12, 'required': True, 'type': 'amount'},
        18: {'name': 'Cheque/Transfer', 'length': 12, 'required': True, 'type': 'amount'},
        19: {'name': 'Tarjeta', 'length': 12, 'required': True, 'type': 'amount'},
        20: {'name': 'Crédito', 'length': 12, 'required': True, 'type': 'amount'},
        21: {'name': 'Bonos', 'length': 12, 'required': True, 'type': 'amount'},
        22: {'name': 'Permuta', 'length': 12, 'required': True, 'type': 'amount'},
        23: {'name': 'Otras Formas', 'length': 12, 'required': True, 'type': 'amount'},
    }

    # Patrones NCF
    NCF_PATTERNS = {
        'B01': r'^B01\d{8}$',
        'B02': r'^B02\d{8}$',
        'B03': r'^B03\d{8}$',
        'B04': r'^B04\d{8}$',
        'B11': r'^B11\d{8}$',
        'B12': r'^B12\d{8}$',
        'B13': r'^B13\d{8}$',
        'B14': r'^B14\d{8}$',
        'B15': r'^B15\d{8}$',
        'B16': r'^B16\d{8}$',
        'B17': r'^B17\d{8}$',
        'E31': r'^E31\d{10}$',
        'E32': r'^E32\d{10}$',
        'E33': r'^E33\d{10}$',
        'E34': r'^E34\d{10}$',
        'E41': r'^E41\d{10}$',
        'E43': r'^E43\d{10}$',
        'E44': r'^E44\d{10}$',
        'E45': r'^E45\d{10}$',
        'E47': r'^E47\d{10}$',
    }

    @api.model
    def validate_606_data(self, data_lines):
        """
        Validar datos para archivo 606.
        
        Args:
            data_lines: Lista de dicts con datos de cada línea
            
        Returns:
            dict con:
            - valid: bool
            - errors: lista de errores
            - warnings: lista de advertencias
            - summary: resumen de validación
        """
        errors = []
        warnings = []
        
        for idx, line in enumerate(data_lines, start=1):
            line_errors = self._validate_606_line(line, idx)
            errors.extend(line_errors['errors'])
            warnings.extend(line_errors['warnings'])

        # Validaciones globales
        global_errors = self._validate_606_global(data_lines)
        errors.extend(global_errors)

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'summary': {
                'total_lines': len(data_lines),
                'errors_count': len(errors),
                'warnings_count': len(warnings),
            }
        }

    def _validate_606_line(self, line, line_num):
        """Validar una línea del 606"""
        errors = []
        warnings = []
        
        # RNC/Cédula
        rnc = line.get('rnc', '')
        if not rnc:
            errors.append(_('Línea %s: RNC/Cédula es obligatorio') % line_num)
        elif not self._validate_rnc_format(rnc):
            errors.append(_('Línea %s: RNC/Cédula inválido: %s') % (line_num, rnc))

        # Tipo ID
        tipo_id = line.get('tipo_id', '')
        if tipo_id not in ('1', '2'):
            errors.append(_('Línea %s: Tipo ID debe ser 1 (RNC) o 2 (Cédula)') % line_num)
        else:
            # Validar coherencia
            if tipo_id == '1' and len(str(rnc).replace('-', '')) != 9:
                warnings.append(_('Línea %s: Tipo ID=1 (RNC) pero longitud no es 9') % line_num)
            if tipo_id == '2' and len(str(rnc).replace('-', '')) != 11:
                warnings.append(_('Línea %s: Tipo ID=2 (Cédula) pero longitud no es 11') % line_num)

        # NCF
        ncf = line.get('ncf', '')
        if not ncf:
            errors.append(_('Línea %s: NCF es obligatorio') % line_num)
        elif not self._validate_ncf_format(ncf):
            errors.append(_('Línea %s: NCF inválido: %s') % (line_num, ncf))

        # NCF Modificado (si existe)
        ncf_mod = line.get('ncf_modificado', '')
        if ncf_mod and not self._validate_ncf_format(ncf_mod):
            errors.append(_('Línea %s: NCF Modificado inválido: %s') % (line_num, ncf_mod))

        # Fecha
        fecha = line.get('fecha')
        if not fecha:
            errors.append(_('Línea %s: Fecha es obligatoria') % line_num)

        # Montos
        montos = ['monto_servicios', 'monto_bienes', 'itbis_facturado', 
                  'itbis_retenido', 'isr_retenido']
        for monto_field in montos:
            monto = line.get(monto_field, 0)
            if monto and monto < 0:
                errors.append(_('Línea %s: %s no puede ser negativo') % (line_num, monto_field))

        # Total vs suma de partes
        total = float(line.get('total_facturado', 0) or 0)
        servicios = float(line.get('monto_servicios', 0) or 0)
        bienes = float(line.get('monto_bienes', 0) or 0)
        itbis = float(line.get('itbis_facturado', 0) or 0)
        
        suma = servicios + bienes + itbis
        if total > 0 and abs(total - suma) > 0.01:
            warnings.append(_(
                'Línea %s: Total (%.2f) no coincide con suma servicios+bienes+itbis (%.2f)'
            ) % (line_num, total, suma))

        # Forma de pago
        forma_pago = line.get('forma_pago', '')
        if forma_pago and forma_pago not in ('01', '02', '03', '04', '05', '06', '07'):
            errors.append(_('Línea %s: Forma de pago inválida: %s') % (line_num, forma_pago))

        # Tipo bienes/servicios
        tipo_bs = line.get('tipo_bienes_servicios', '')
        if tipo_bs and tipo_bs not in [str(i).zfill(2) for i in range(1, 12)]:
            warnings.append(_('Línea %s: Tipo bienes/servicios no estándar: %s') % (line_num, tipo_bs))

        return {'errors': errors, 'warnings': warnings}

    def _validate_606_global(self, data_lines):
        """Validaciones globales del 606"""
        errors = []
        
        # Verificar NCF duplicados
        ncfs = [line.get('ncf', '') for line in data_lines if line.get('ncf')]
        duplicados = [ncf for ncf in set(ncfs) if ncfs.count(ncf) > 1]
        
        for dup in duplicados:
            errors.append(_('NCF duplicado en 606: %s') % dup)

        return errors

    @api.model
    def validate_607_data(self, data_lines):
        """
        Validar datos para archivo 607.
        
        Args:
            data_lines: Lista de dicts con datos de cada línea
            
        Returns:
            dict con resultados de validación
        """
        errors = []
        warnings = []
        
        for idx, line in enumerate(data_lines, start=1):
            line_errors = self._validate_607_line(line, idx)
            errors.extend(line_errors['errors'])
            warnings.extend(line_errors['warnings'])

        # Validaciones globales
        global_errors = self._validate_607_global(data_lines)
        errors.extend(global_errors)

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'summary': {
                'total_lines': len(data_lines),
                'errors_count': len(errors),
                'warnings_count': len(warnings),
            }
        }

    def _validate_607_line(self, line, line_num):
        """Validar una línea del 607"""
        errors = []
        warnings = []

        # NCF (obligatorio)
        ncf = line.get('ncf', '')
        if not ncf:
            errors.append(_('Línea %s: NCF es obligatorio') % line_num)
        elif not self._validate_ncf_format(ncf):
            errors.append(_('Línea %s: NCF inválido: %s') % (line_num, ncf))

        # RNC (opcional para B02)
        rnc = line.get('rnc_cedula', '')
        tipo_ncf = ncf[:3] if ncf else ''
        
        if tipo_ncf in ('B01', 'E31') and not rnc:
            errors.append(_('Línea %s: %s requiere RNC del cliente') % (line_num, tipo_ncf))
        elif rnc and not self._validate_rnc_format(rnc):
            errors.append(_('Línea %s: RNC/Cédula inválido: %s') % (line_num, rnc))

        # Fecha
        fecha = line.get('fecha_comprobante')
        if not fecha:
            errors.append(_('Línea %s: Fecha es obligatoria') % line_num)

        # Monto
        monto = float(line.get('monto_facturado', 0) or 0)
        if monto <= 0:
            warnings.append(_('Línea %s: Monto facturado es 0 o negativo') % line_num)

        # Tipo ingreso
        tipo_ingreso = line.get('tipo_ingreso', '')
        if tipo_ingreso and tipo_ingreso not in ('01', '02', '03', '04'):
            errors.append(_('Línea %s: Tipo ingreso inválido: %s') % (line_num, tipo_ingreso))

        # Formas de pago (deben sumar el total)
        efectivo = float(line.get('efectivo', 0) or 0)
        cheque = float(line.get('cheque_transfer', 0) or 0)
        tarjeta = float(line.get('tarjeta', 0) or 0)
        credito = float(line.get('credito', 0) or 0)
        otros = float(line.get('otras_formas', 0) or 0)
        
        suma_pagos = efectivo + cheque + tarjeta + credito + otros
        if monto > 0 and abs(monto - suma_pagos) > 0.01:
            warnings.append(_(
                'Línea %s: Suma formas pago (%.2f) no coincide con monto (%.2f)'
            ) % (line_num, suma_pagos, monto))

        return {'errors': errors, 'warnings': warnings}

    def _validate_607_global(self, data_lines):
        """Validaciones globales del 607"""
        errors = []
        
        # Verificar NCF duplicados (excepto retenciones posteriores)
        ncf_counts = {}
        for line in data_lines:
            ncf = line.get('ncf', '')
            fecha_ret = line.get('fecha_retencion')
            if ncf:
                key = (ncf, bool(fecha_ret))
                ncf_counts[key] = ncf_counts.get(key, 0) + 1
        
        for (ncf, es_retencion), count in ncf_counts.items():
            if count > 1 and not es_retencion:
                errors.append(_('NCF duplicado en 607: %s') % ncf)

        return errors

    def _validate_rnc_format(self, rnc):
        """Validar formato RNC/Cédula"""
        if not rnc:
            return False
        clean = re.sub(r'[^0-9]', '', str(rnc))
        return len(clean) in (9, 11)

    def _validate_ncf_format(self, ncf):
        """Validar formato NCF"""
        if not ncf:
            return False
        ncf = ncf.strip().upper()
        
        for pattern in self.NCF_PATTERNS.values():
            if re.match(pattern, ncf):
                return True
        return False

    @api.model
    def format_606_line(self, data):
        """
        Formatear línea para archivo TXT 606.
        
        Args:
            data: dict con datos de la línea
            
        Returns:
            string formateado para TXT
        """
        fields = [
            self._format_rnc(data.get('rnc', '')),
            data.get('tipo_id', '1'),
            data.get('tipo_bienes_servicios', '02').zfill(2),
            self._format_ncf(data.get('ncf', '')),
            self._format_ncf(data.get('ncf_modificado', '')),
            self._format_date(data.get('fecha')),
            self._format_date(data.get('fecha_pago')),
            self._format_amount(data.get('monto_servicios', 0)),
            self._format_amount(data.get('monto_bienes', 0)),
            self._format_amount(data.get('total_facturado', 0)),
            self._format_amount(data.get('itbis_facturado', 0)),
            self._format_amount(data.get('itbis_retenido', 0)),
            self._format_amount(data.get('itbis_proporcionalidad', 0)),
            self._format_amount(data.get('itbis_costo', 0)),
            self._format_amount(data.get('itbis_adelantar', 0)),
            self._format_amount(data.get('itbis_percibido', 0)),
            (data.get('tipo_retencion_isr', '') or '').zfill(2),
            self._format_amount(data.get('isr_retenido', 0)),
            self._format_amount(data.get('isr_percibido', 0)),
            self._format_amount(data.get('impuesto_selectivo', 0)),
            self._format_amount(data.get('otros_impuestos', 0)),
            self._format_amount(data.get('propina_legal', 0)),
            (data.get('forma_pago', '04') or '04').zfill(2),
        ]
        
        return '|'.join(fields)

    @api.model
    def format_607_line(self, data):
        """
        Formatear línea para archivo TXT 607.
        """
        fields = [
            self._format_rnc(data.get('rnc_cedula', '')),
            data.get('tipo_id', '') or '',
            self._format_ncf(data.get('ncf', '')),
            self._format_ncf(data.get('ncf_modificado', '')),
            (data.get('tipo_ingreso', '01') or '01').zfill(2),
            self._format_date(data.get('fecha_comprobante')),
            self._format_date(data.get('fecha_retencion')),
            self._format_amount(data.get('monto_facturado', 0)),
            self._format_amount(data.get('itbis_facturado', 0)),
            self._format_amount(data.get('itbis_retenido_terceros', 0)),
            self._format_amount(data.get('itbis_percibido', 0)),
            self._format_amount(data.get('isr_retenido_terceros', 0)),
            self._format_amount(data.get('isr_percibido', 0)),
            self._format_amount(data.get('impuesto_selectivo', 0)),
            self._format_amount(data.get('otros_impuestos', 0)),
            self._format_amount(data.get('propina_legal', 0)),
            self._format_amount(data.get('efectivo', 0)),
            self._format_amount(data.get('cheque_transfer', 0)),
            self._format_amount(data.get('tarjeta', 0)),
            self._format_amount(data.get('credito', 0)),
            self._format_amount(data.get('bonos', 0)),
            self._format_amount(data.get('permuta', 0)),
            self._format_amount(data.get('otras_formas', 0)),
        ]
        
        return '|'.join(fields)

    def _format_rnc(self, rnc):
        """Formatear RNC (sin guiones)"""
        if not rnc:
            return ''
        return re.sub(r'[^0-9]', '', str(rnc))

    def _format_ncf(self, ncf):
        """Formatear NCF"""
        if not ncf:
            return ''
        return ncf.strip().upper()

    def _format_date(self, dt):
        """Formatear fecha como YYYYMMDD"""
        if not dt:
            return ''
        if isinstance(dt, str):
            return dt.replace('-', '')
        return dt.strftime('%Y%m%d')

    def _format_amount(self, amount):
        """Formatear monto (2 decimales, sin separadores)"""
        try:
            return '%.2f' % float(amount or 0)
        except:
            return '0.00'