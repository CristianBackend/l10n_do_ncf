# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import re
import unicodedata
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

# URL de la API pública de DGII
DGII_API_PUBLIC = "https://rnc.megaplus.com.do/api/consulta"

# =========================================================================
# CLASIFICACION POR ACTIVIDAD ECONOMICA (DGII)
# =========================================================================
# El prefijo 430 del RNC es AMBIGUO: lo usan ayuntamientos, hospitales
# publicos, fundaciones, condominios y hasta empresas normales. No se puede
# decidir el tipo de contribuyente solo por el numero.
#
# La API de DGII devuelve la ACTIVIDAD ECONOMICA registrada, y esa si
# distingue los casos. Estas listas son los DEFAULTS; se pueden ampliar sin
# tocar codigo desde:
#   Ajustes > Tecnico > Parametros del sistema
#     l10n_do_ncf.activity_governmental
#     l10n_do_ncf.activity_special_regime
#     l10n_do_ncf.activity_final_consumer
# (valores separados por coma, sin acentos, en mayusculas)
#
# Muestras reales que originaron cada lista:
#   ADMINISTRACION PUBLICA EN GENERAL  -> Area VIII de Salud, Ayto. Villa Fundacion
#   ACTIVIDADES DE HOSPITALES          -> 4 hospitales publicos
#   REGULACION DE ACTIVIDADES DE ORGANISMOS -> INTRANT
#   SERVICIOS SOCIALES SIN ALOJAMIENTO -> Fundacion Hilos de Amor, Asoc. Rehabilitacion
#   CONDOMINIOS                        -> Condominio Torre GM V
#   ALQUILER DE INMUEBLES              -> Catalonia Met, Torre Ray Rub VII
#   SERVICIOS DE PUBLICIDAD            -> 1B Advertising (empresa normal con 430)
# =========================================================================

ACTIVITY_GOVERNMENTAL_DEFAULT = [
    'ADMINISTRACION PUBLICA',
    'ACTIVIDADES DE HOSPITALES',
    'REGULACION DE ACTIVIDADES',
    'AYUNTAMIENTO',
    'MINISTERIO',
    'ORGANISMOS',
    'DEFENSA',
    'SEGURIDAD SOCIAL OBLIGATORIA',
    'MEJORAMIENTO DE CONDICIONES AGROPECUARIAS',
]

ACTIVITY_SPECIAL_REGIME_DEFAULT = [
    'SERVICIOS SOCIALES',
    'SIN ALOJAMIENTO',
    'REHABILITACION',
    'ZONA FRANCA',
    'SIN FINES DE LUCRO',
    'ASOCIACIONES',
    'FUNDACION',
    'ORGANIZACIONES RELIGIOSAS',
    'ORGANIZACIONES POLITICAS',
]

ACTIVITY_FINAL_CONSUMER_DEFAULT = [
    'CONDOMINIO',
    'ALQUILER DE INMUEBLES',
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    l10n_do_dgii_tax_payer_type = fields.Selection([
        ('taxpayer', 'Contribuyente'),
        ('non_taxpayer', 'No Contribuyente'),
        ('final_consumer', 'Consumidor Final'),
        ('special_regime', 'Regimen Especial'),
        ('governmental', 'Gubernamental'),
    ], string='Tipo de Contribuyente', default='final_consumer',
       help='Determina el tipo de NCF a generar automaticamente')

    l10n_do_rnc_validated = fields.Boolean(
        string='RNC Validado',
        default=False,
        help='Indica si el RNC fue validado contra DGII'
    )

    l10n_do_rnc_validation_date = fields.Datetime(
        string='Fecha de Validacion',
        readonly=True,
        help='Fecha en que se valido el RNC contra DGII'
    )

    l10n_do_dgii_status = fields.Char(
        string='Estado DGII',
        readonly=True,
        help='Estado del contribuyente en DGII'
    )

    l10n_do_dgii_activity = fields.Char(
        string='Actividad Economica',
        readonly=True,
        help='Actividad economica registrada en DGII. Se usa para clasificar '
             'automaticamente el tipo de contribuyente cuando el RNC tiene '
             'prefijo ambiguo (430).'
    )

    # =========================================
    # CONSULTA A LA API DE DGII
    # =========================================
    def _get_dgii_api_url(self):
        """Obtener URL de la API DGII desde configuración o usar default"""
        api_url = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_ncf.dgii_api_url',
            default=''
        )
        if api_url:
            return api_url

        try:
            test_response = requests.get('http://localhost:5000/api/v1/rnc/101000783', timeout=2)
            if test_response.status_code == 200:
                return 'http://localhost:5000/api/v1/rnc'
        except:
            pass

        return 'https://api.indexa.do/api/rnc'

    def _consultar_dgii(self, rnc):
        """Consultar RNC en DGII - intenta múltiples APIs"""
        rnc_clean = re.sub(r'[^0-9]', '', rnc)

        apis = [
            {
                'url': f'http://localhost:5000/api/v1/rnc/{rnc_clean}',
                'parser': self._parse_local_api,
                'method': 'GET'
            },
            {
                'url': DGII_API_PUBLIC,
                'parser': self._parse_megaplus_api,
                'method': 'POST',
                'data': {'rnc': rnc_clean}
            },
        ]

        for api in apis:
            try:
                _logger.info(f"NCF: Intentando consultar RNC {rnc_clean} en {api['url']}")

                if api.get('method') == 'POST':
                    response = requests.post(
                        api['url'],
                        json=api.get('data', {}),
                        timeout=10,
                        headers={'Content-Type': 'application/json'}
                    )
                else:
                    response = requests.get(api['url'], timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    result = api['parser'](data)
                    if result.get('found'):
                        _logger.info(f"NCF: RNC {rnc_clean} encontrado: {result.get('name')}")
                        return result
            except Exception as e:
                _logger.warning(f"NCF: Error consultando {api['url']}: {str(e)}")
                continue

        return {'found': False}

    def _parse_local_api(self, data):
        """Parser para API local (ncf-api)"""
        if data.get('found'):
            return {
                'found': True,
                'name': data.get('name', ''),
                'status': data.get('status', ''),
                'activity': data.get('activity', ''),
                'regime': data.get('regime', ''),
            }
        return {'found': False}

    def _parse_megaplus_api(self, data):
        """Parser para API de megaplus.com.do"""
        if not data.get('error') and data.get('nombre_razon_social'):
            return {
                'found': True,
                'name': data.get('nombre_razon_social', ''),
                'commercial_name': data.get('nombre_comercial', ''),
                'status': data.get('estado', 'ACTIVO'),
                'activity': data.get('actividad_economica', ''),
                'regime': data.get('regimen_de_pagos', ''),
            }
        return {'found': False}

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'country_id' in fields_list:
            do_country = self.env['res.country'].search([('code', '=', 'DO')], limit=1)
            if do_country:
                res['country_id'] = do_country.id
        return res

    # =========================================
    # CLASIFICACION POR ACTIVIDAD ECONOMICA
    # =========================================
    @api.model
    def _l10n_do_normalize(self, texto):
        """Normalizar texto para comparar: sin acentos, mayusculas, sin espacios extra."""
        if not texto:
            return ''
        texto = unicodedata.normalize('NFKD', str(texto))
        texto = ''.join(c for c in texto if not unicodedata.combining(c))
        return re.sub(r'\s+', ' ', texto).strip().upper()

    @api.model
    def _l10n_do_get_activity_keywords(self, tipo):
        """Palabras clave por tipo de contribuyente.

        Se leen de parametros del sistema para poder ampliarlas SIN tocar
        codigo ni desplegar. Si el parametro no existe, se usan los defaults
        definidos arriba en este archivo.

        Parametro: l10n_do_ncf.activity_<tipo>   (valores separados por coma)
        """
        defaults = {
            'governmental': ACTIVITY_GOVERNMENTAL_DEFAULT,
            'special_regime': ACTIVITY_SPECIAL_REGIME_DEFAULT,
            'final_consumer': ACTIVITY_FINAL_CONSUMER_DEFAULT,
        }
        param = self.env['ir.config_parameter'].sudo().get_param(
            f'l10n_do_ncf.activity_{tipo}', default=''
        )
        if param:
            return [self._l10n_do_normalize(k) for k in param.split(',') if k.strip()]
        return [self._l10n_do_normalize(k) for k in defaults.get(tipo, [])]

    @api.model
    def _l10n_do_classify_by_activity(self, actividad):
        """Deducir el tipo de contribuyente a partir de la actividad economica.

        Devuelve el tipo, o False si la actividad no coincide con ninguna
        lista conocida (en cuyo caso NO se debe clasificar automaticamente).

        El orden importa: gubernamental primero, luego regimen especial,
        luego consumidor final. Asi 'SERVICIOS SOCIALES' de una fundacion no
        se confunde con nada gubernamental.
        """
        act = self._l10n_do_normalize(actividad)
        if not act:
            return False

        for tipo in ('governmental', 'special_regime', 'final_consumer'):
            for palabra in self._l10n_do_get_activity_keywords(tipo):
                if palabra and palabra in act:
                    return tipo

        return False

    def _l10n_do_fetch_activity(self, rnc_clean):
        """Obtener la actividad economica del contacto.

        1. Si ya esta guardada en el contacto, se reutiliza (sin llamada externa).
        2. Si no, se consulta la API y se guarda para futuras clasificaciones.

        Devuelve la actividad o cadena vacia si no se pudo obtener.
        Nunca lanza excepcion: si la API falla, se devuelve '' y el llamador
        decide (que sera: NO clasificar).
        """
        self.ensure_one()

        if self.l10n_do_dgii_activity:
            return self.l10n_do_dgii_activity

        # Permite desactivar la consulta externa si hiciera falta
        # (ej. importaciones masivas, API caida, rate limiting)
        consultar = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_do_ncf.classify_query_api', default='True'
        )
        if consultar not in ('True', 'true', '1'):
            return ''

        try:
            data = self._consultar_dgii(rnc_clean)
            if data.get('found'):
                actividad = data.get('activity') or ''
                vals = {'l10n_do_dgii_activity': actividad}
                if data.get('status'):
                    vals['l10n_do_dgii_status'] = data['status']
                self.with_context(l10n_do_skip_auto_type=True).write(vals)
                return actividad
        except Exception as e:
            _logger.warning(
                'NCF: no se pudo obtener actividad economica de %s: %s',
                rnc_clean, str(e)
            )

        return ''

    # =========================================
    # CLASIFICACION AUTOMATICA AL CREAR / EDITAR
    # =========================================
    def _l10n_do_should_auto_classify(self):
        """La clasificacion automatica solo aplica a contactos dominicanos.

        Si el pais no esta definido se asume RD (es el default del modulo).
        """
        self.ensure_one()
        if not self.vat:
            return False
        if self.country_id and self.country_id.code != 'DO':
            return False
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """Clasificar el tipo de contribuyente al crear el contacto.

        MOTIVO: _auto_set_taxpayer_type solo se invocaba desde el onchange
        del VAT, que no se dispara al crear contactos desde el checkout web,
        el POS o cualquier creacion por codigo. Resultado: todo contacto
        nuevo quedaba como 'final_consumer' aunque tuviera RNC de empresa.

        La clasificacion nunca interrumpe la creacion: si algo falla, se
        registra en el log y el contacto queda con su valor por defecto.
        """
        partners = super().create(vals_list)
        for partner in partners:
            try:
                if partner._l10n_do_should_auto_classify():
                    partner.with_context(
                        l10n_do_skip_auto_type=True
                    )._auto_set_taxpayer_type(partner.vat)
            except Exception as e:
                _logger.warning(
                    'NCF: no se pudo clasificar el contacto %s: %s',
                    partner.display_name, str(e)
                )
        return partners

    def write(self, vals):
        """Reclasificar si cambia el documento fiscal.

        El contexto l10n_do_skip_auto_type evita la recursion, porque
        _auto_set_taxpayer_type escribe sobre el propio registro.
        """
        res = super().write(vals)

        if 'vat' in vals and not self.env.context.get('l10n_do_skip_auto_type'):
            for partner in self:
                try:
                    if partner._l10n_do_should_auto_classify():
                        # El VAT cambio: la actividad guardada ya no sirve
                        partner.with_context(
                            l10n_do_skip_auto_type=True
                        ).l10n_do_dgii_activity = False
                        partner.with_context(
                            l10n_do_skip_auto_type=True
                        )._auto_set_taxpayer_type(partner.vat)
                except Exception as e:
                    _logger.warning(
                        'NCF: no se pudo reclasificar el contacto %s: %s',
                        partner.display_name, str(e)
                    )

        return res

    def _limpiar_datos_dgii(self):
        """Limpiar todos los datos de DGII del partner"""
        self.name = False
        self.l10n_do_dgii_status = False
        self.l10n_do_dgii_activity = False
        self.l10n_do_rnc_validated = False
        self.l10n_do_rnc_validation_date = False
        self.l10n_do_dgii_tax_payer_type = 'final_consumer'

    @api.onchange('vat')
    def _onchange_vat_dgii(self):
        """Auto-consultar DGII cuando se ingresa RNC/Cedula"""
        # Si se borró el VAT, limpiar datos
        if not self.vat:
            self._limpiar_datos_dgii()
            return

        rnc = re.sub(r'[^0-9]', '', self.vat)

        # Validar longitud
        if len(rnc) != 9 and len(rnc) != 11:
            return

        # SIEMPRE limpiar datos anteriores antes de consultar nuevo RNC
        self.l10n_do_dgii_status = False
        self.l10n_do_dgii_activity = False
        self.l10n_do_rnc_validated = False
        self.l10n_do_rnc_validation_date = False

        # Consultar nuevo RNC
        self._consultar_rnc_dgii(rnc)
        self._auto_set_taxpayer_type(rnc)

    def _auto_set_taxpayer_type(self, rnc):
        """Asignar tipo de contribuyente automaticamente.

        CRITERIO (aprobado con el cliente, coherente con la norma DGII):
        - 11 digitos = cedula personal -> 'final_consumer' -> B02 Consumo
        - 9 digitos  = RNC             -> segun prefijo y actividad economica

        La DGII establece que se emite comprobante de consumo salvo que el
        cliente solicite factura con su RNC. Aportar un RNC de 9 digitos ES
        esa solicitud; una cedula solo identifica a la persona.

        DETALLE DE LOS RNC DE 9 DIGITOS:

        a) Prefijos 401 y 402 -> 'governmental' (B15).
           Ministerios e instituciones descentralizadas. Fiable por prefijo.

        b) Prefijo 430 -> AMBIGUO, se resuelve por ACTIVIDAD ECONOMICA.
           Este prefijo lo comparten al menos cuatro tipos de entidad, con
           destinos fiscales distintos (casos reales verificados en DGII):
             ADMINISTRACION PUBLICA EN GENERAL   -> B15  (Ayto. Villa Fundacion)
             ACTIVIDADES DE HOSPITALES           -> B15  (hospitales publicos)
             REGULACION DE ACTIVIDADES ORGANISMOS-> B15  (INTRANT)
             SERVICIOS SOCIALES SIN ALOJAMIENTO  -> B14  (Fundacion Hilos de Amor)
             CONDOMINIOS / ALQUILER DE INMUEBLES -> B02  (Condominio Torre GM V)
             SERVICIOS DE PUBLICIDAD             -> B01  (1B Advertising)
           Si la actividad no se puede obtener o no coincide con ninguna
           lista conocida, NO se clasifica: queda 'final_consumer' (B02), que
           es la opcion conservadora porque no otorga credito fiscal indebido.

        c) Resto de prefijos -> 'taxpayer' (B01). Empresas normales.
           No se consulta la API en este caso: evita latencia y rate limiting.

        EXCEPCIONES: 'special_regime' y 'governmental' puestos a mano se
        respetan siempre; la clasificacion automatica no los pisa.

        AMPLIAR LAS LISTAS SIN TOCAR CODIGO:
        Ajustes > Tecnico > Parametros del sistema
            l10n_do_ncf.activity_governmental
            l10n_do_ncf.activity_special_regime
            l10n_do_ncf.activity_final_consumer
        Para desactivar la consulta a la API:
            l10n_do_ncf.classify_query_api = False
        """
        rnc_clean = re.sub(r'[^0-9]', '', rnc or '')

        # No pisar clasificaciones especiales puestas manualmente
        if self.l10n_do_dgii_tax_payer_type in ('special_regime', 'governmental'):
            return

        # --- Cedula: persona fisica -> consumidor final (B02)
        if len(rnc_clean) == 11:
            self.l10n_do_dgii_tax_payer_type = 'final_consumer'
            return

        if len(rnc_clean) != 9:
            return

        # --- Prefijos gubernamentales fiables
        if rnc_clean.startswith(('401', '402')):
            self.l10n_do_dgii_tax_payer_type = 'governmental'
            _logger.info(
                'NCF: RNC %s clasificado como gubernamental por prefijo', rnc_clean
            )
            return

        # --- Prefijo ambiguo: decidir por actividad economica
        if rnc_clean.startswith('430'):
            actividad = self._l10n_do_fetch_activity(rnc_clean)
            tipo = self._l10n_do_classify_by_activity(actividad)

            if tipo:
                self.l10n_do_dgii_tax_payer_type = tipo
                _logger.info(
                    'NCF: RNC %s (prefijo 430) clasificado como "%s" por '
                    'actividad economica "%s"',
                    rnc_clean, tipo, actividad
                )
            elif actividad:
                # Hay actividad pero no coincide con ninguna lista conocida:
                # se trata como empresa normal (ej. 1B Advertising).
                self.l10n_do_dgii_tax_payer_type = 'taxpayer'
                _logger.info(
                    'NCF: RNC %s (prefijo 430) con actividad "%s" no listada; '
                    'se clasifica como contribuyente. Si no corresponde, '
                    'agregue la actividad al parametro correspondiente.',
                    rnc_clean, actividad
                )
            else:
                # Sin actividad (API caida, RNC no encontrado, consulta
                # desactivada): NO clasificar. Queda el valor por defecto.
                _logger.warning(
                    'NCF: RNC %s (prefijo 430) sin actividad economica '
                    'disponible. No se clasifica automaticamente; verifique '
                    'el tipo de contribuyente manualmente.',
                    rnc_clean
                )
            return

        # --- Resto: empresa normal -> contribuyente (B01)
        self.l10n_do_dgii_tax_payer_type = 'taxpayer'

    def _consultar_rnc_dgii(self, rnc):
        """Consultar RNC en la API de DGII"""
        try:
            data = self._consultar_dgii(rnc)
            if data.get('found'):
                nombre_dgii = data.get('name', '')
                # SIEMPRE actualizar el nombre si se encontró en DGII
                if nombre_dgii:
                    self.name = nombre_dgii
                self.l10n_do_dgii_status = data.get('status', '')
                self.l10n_do_dgii_activity = data.get('activity', '')
                self.l10n_do_rnc_validated = True
                self.l10n_do_rnc_validation_date = datetime.now()
                return True
            else:
                # RNC no encontrado - mantener campos limpios
                self.l10n_do_rnc_validated = False
        except Exception as e:
            _logger.warning(f"NCF: Error en _consultar_rnc_dgii: {str(e)}")
        return False

    def action_validate_rnc(self):
        """Boton para validar RNC manualmente contra DGII.

        Ademas de traer los datos, reclasifica el tipo de contribuyente
        usando la actividad economica recien obtenida.
        """
        self.ensure_one()
        if not self.vat:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Debe ingresar un RNC/Cedula primero'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        rnc = re.sub(r'[^0-9]', '', self.vat)

        try:
            data = self._consultar_dgii(rnc)

            if data.get('found'):
                vals = {
                    'l10n_do_dgii_status': data.get('status', ''),
                    'l10n_do_dgii_activity': data.get('activity', ''),
                    'l10n_do_rnc_validated': True,
                    'l10n_do_rnc_validation_date': datetime.now(),
                }

                nombre_dgii = data.get('name', '')
                if nombre_dgii:
                    vals['name'] = nombre_dgii

                self.with_context(l10n_do_skip_auto_type=True).write(vals)

                # Reclasificar con la actividad recien obtenida
                self.with_context(
                    l10n_do_skip_auto_type=True
                )._auto_set_taxpayer_type(rnc)

                tipo_label = dict(
                    self._fields['l10n_do_dgii_tax_payer_type'].selection
                ).get(self.l10n_do_dgii_tax_payer_type, '')

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('RNC Validado'),
                        'message': _('Nombre: %s\nActividad: %s\nTipo: %s') % (
                            nombre_dgii,
                            data.get('activity', ''),
                            tipo_label,
                        ),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                # Limpiar validación si no se encuentra
                self.with_context(l10n_do_skip_auto_type=True).write({
                    'l10n_do_rnc_validated': False,
                    'l10n_do_dgii_status': '',
                    'l10n_do_dgii_activity': '',
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('RNC No Encontrado'),
                        'message': _('El RNC no fue encontrado en DGII'),
                        'type': 'warning',
                        'sticky': False,
                    }
                }
        except Exception as e:
            _logger.error(f"NCF: Error validando RNC: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Error conectando a DGII: %s') % str(e),
                    'type': 'danger',
                    'sticky': False,
                }
            }

    @api.model
    def create_quick_from_rnc(self, rnc, name=None, email=None):
        """Crear cliente rapido desde RNC - usado en facturacion rapida"""
        rnc_clean = re.sub(r'[^0-9]', '', rnc)

        existing = self.search(['|', ('vat', '=', rnc_clean), ('vat', '=', rnc)], limit=1)
        if existing:
            return existing

        vals = {
            'vat': rnc_clean,
            'name': name or f'Cliente {rnc_clean}',
            'is_company': len(rnc_clean) == 9,
        }

        if email:
            vals['email'] = email

        try:
            data = self._consultar_dgii(rnc_clean)
            if data.get('found'):
                vals['name'] = data.get('name', vals['name'])
                vals['l10n_do_dgii_status'] = data.get('status', '')
                vals['l10n_do_dgii_activity'] = data.get('activity', '')
                vals['l10n_do_rnc_validated'] = True
                vals['l10n_do_rnc_validation_date'] = datetime.now()
        except Exception:
            pass

        if len(rnc_clean) == 9:
            vals['is_company'] = True
        elif len(rnc_clean) == 11:
            vals['is_company'] = False

        # El tipo de contribuyente lo asigna create() via
        # _auto_set_taxpayer_type. Como aqui ya se guarda la actividad
        # economica, la clasificacion del prefijo 430 la reutiliza sin
        # hacer una segunda llamada a la API.
        return self.create(vals)