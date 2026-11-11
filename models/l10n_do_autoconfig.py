# -*- coding: utf-8 -*-
"""Configuración fiscal que se deduce sin ambigüedad del plan contable l10n_do.

Impuestos, diarios y Tipo 606 de las cuentas. Se ejecuta al instalar o
actualizar el módulo (hooks.py y la migración
19.0.3.4.0) y al cargar el plan contable dominicano en una compañía
(chart_template.py). Es idempotente y solo llena lo que está vacío: un valor
puesto por el usuario nunca se sobrescribe.

Los impuestos del plan se identifican por el xmlid que les da Odoo al cargar
la plantilla (account.<id de compañía>_<id de plantilla>), nunca por nombre.
"""
import logging

_logger = logging.getLogger(__name__)

# Plantilla de impuesto de l10n_do (addons/l10n_do/data/template/
# account.tax-do.csv) -> valores DGII. Sale del grupo de impuestos de la
# propia plantilla: ITBIS (tax_group_itbis), ISC (tax_group_isc), propina
# (tax_group_tip), otros (tax_group_other_tax) e ISR (tax_group_isr).
_ITBIS = {'dgii_tax_kind': 'itbis'}
_RET_ITBIS = {'dgii_retention_type': 'itbis', 'dgii_606_bucket': 'itbis_retenido'}
_RET_ISR = {'dgii_retention_type': 'isr', 'dgii_606_bucket': 'isr_retenido'}

TAX_TEMPLATE_VALUES = {
    # Exentos: "ITBIS Exempt" de ventas y de compras.
    'tax_0_sale': {'dgii_itbis_zero_type': 'exempt', 'dgii_tax_kind': 'itbis'},
    'tax_0_purch': {'dgii_itbis_zero_type': 'exempt', 'dgii_tax_kind': 'itbis'},
    # ITBIS (grupo ITBIS, tasa positiva)
    'tax_18_sale': _ITBIS,
    'tax_18_purch': _ITBIS,
    'tax_16_purch': _ITBIS,
    'tax_9_purch': _ITBIS,
    'tax_8_purch': _ITBIS,
    'tax_18_purch_serv': _ITBIS,
    'tax_18_importation': _ITBIS,
    'tax_18_of_10': _ITBIS,
    'tax_18_10_total_mount': _ITBIS,
    'tax_18_property_cost': _ITBIS,
    'tax_18_serv_cost': _ITBIS,
    # Propina legal, ISC y otros impuestos/tasas
    'tax_tip_sale': {'dgii_tax_kind': 'tip'},
    'tax_tip_purch': {'dgii_tax_kind': 'tip'},
    'tax_10_telco': {'dgii_tax_kind': 'isc'},
    'tax_2_telco': {'dgii_tax_kind': 'other'},     # CDT telecomunicaciones
    'tax_0015_bank': {'dgii_tax_kind': 'other'},   # 0.15 % cheques y transferencias
    # Retenciones de ITBIS (grupo ITBIS, tasa negativa) que hace la empresa
    'ret_100_tax_security': _RET_ITBIS,
    'ret_100_tax_nonprofit': _RET_ITBIS,
    'ret_100_tax_person': _RET_ITBIS,
    'ret_30_tax_moral': _RET_ITBIS,
    'ret_30_tax_freelance': _RET_ITBIS,
    'ret_75_tax_nonformal': _RET_ITBIS,
    # Retenciones de ISR (grupo ISR) que hace la empresa
    # Tipo de retención ISR del 606 (casilla 17) solo donde el impuesto de la
    # plantilla lo dice sin ambigüedad: honorarios (02) y alquileres (01).
    # Los demás los confirma el contador (docs/retenciones_tabla.md).
    'ret_15_income_person': dict(_RET_ISR, dgii_isr_retention_type='02'),
    'ret_15_income_rent': dict(_RET_ISR, dgii_isr_retention_type='01'),
    'ret_10_income_dividend': _RET_ISR,
    'ret_3_income_person': _RET_ISR,
    'ret_2_income_transfer': _RET_ISR,
    'ret_3_income_article_70': _RET_ISR,
    'ret_27_income_remittance': _RET_ISR,
    'ret_15_income_foreign_royalties_technology': _RET_ISR,
    # Retención de ISR que le hace el Estado a la empresa (en ventas): no va
    # en el 606, solo se clasifica el impuesto.
    'ret_5_income_gov': {'dgii_retention_type': 'isr'},
}

# Formas de pago del 606/607 (Norma General 07-2018, Anexo A, "Tabla de Forma
# de pagos"; instructivo 606, julio 2025, casilla 23): 1 Efectivo, 2 Cheques/
# Transferencias/Depósito, 3 Tarjeta crédito/débito. El tipo de diario lo dice.
JOURNAL_PAYMENT_FORM = {
    'cash': '01',
    'bank': '02',
    'credit': '03',
}


# Plantilla de cuenta de l10n_do (account.account-do.csv) -> "Tipo 606".
# Norma General 07-2018, Anexo A, "Tabla de clasificación de Costos y Gastos";
# instructivo 606 (julio 2025), casilla 3. Solo las cuentas de categoría clara;
# las demás quedan vacías a propósito (ver docs/mapeo_cuentas_606.md).
ACCOUNT_TEMPLATE_606 = {
    # 01 Gastos de personal (pagos a terceros por beneficios a empleados)
    'l10n_do_61010900': '01',  # Comidas o Dietas al Personal
    'l10n_do_61011000': '01',  # Cursos y Entrenamientos
    'l10n_do_61011400': '01',  # Uniformes
    'l10n_do_61011500': '01',  # Otros Gastos de Personal
    # 02 Gastos por trabajos, suministros y servicios
    'l10n_do_61020100': '02',  # Energía Eléctrica
    'l10n_do_61020200': '02',  # Comunicaciones
    'l10n_do_61020300': '02',  # Suministros de Oficina (Papelería y útiles)
    'l10n_do_61020400': '02',  # Útiles de Aseo y Limpieza
    'l10n_do_61020500': '02',  # Agua y Basura
    'l10n_do_61020700': '02',  # Combustibles y Lubricantes
    'l10n_do_61021200': '02',  # Servicios de Mensajería
    'l10n_do_61021300': '02',  # Flete y Carga
    'l10n_do_61030101': '02',  # Legales (P. Física)
    'l10n_do_61030102': '02',  # Contabilidad y Auditoría (P. Física)
    'l10n_do_61030103': '02',  # Tecnología (P. Física)
    'l10n_do_61030107': '02',  # Asesorías (P. Física)
    'l10n_do_61030108': '02',  # Fumigaciones (P. Física)
    'l10n_do_61030109': '02',  # Copias y Escaneos (P. Física)
    'l10n_do_61030110': '02',  # Servicios de Vigilancia (P. Física)
    'l10n_do_61030111': '02',  # Otros Servicios Profesionales (P. Física)
    'l10n_do_61030201': '02',  # Legales (P. Jurídica)
    'l10n_do_61030202': '02',  # Contabilidad y Auditoría (P. Jurídica)
    'l10n_do_61030203': '02',  # Tecnología (P. Jurídica)
    'l10n_do_61030207': '02',  # Asesorías (P. Jurídica)
    'l10n_do_61030208': '02',  # Fumigaciones (P. Jurídica)
    'l10n_do_61030209': '02',  # Copias y Escaneos (P. Jurídica)
    'l10n_do_61030210': '02',  # Servicios de Vigilancia (P. Jurídica)
    'l10n_do_61030211': '02',  # Otros Servicios Profesionales  (P. Jurídica)
    'l10n_do_61030301': '02',  # Honorarios por Servicios del Exterior - Relacionadas
    'l10n_do_61030302': '02',  # Honorarios por Servicios del Exterior - Terceros
    # 03 Arrendamientos
    'l10n_do_61020800': '03',  # Alquileres / Arrendamientos
    # 04 Gastos de activos fijos (reparación y mantenimiento)
    'l10n_do_61030104': '04',  # Mantenimientos de Planta (P. Física)
    'l10n_do_61030106': '04',  # Mantenimientos Mobiliarios y Equipos (P. Física)
    'l10n_do_61030204': '04',  # Mantenimiento de Planta (P. Jurídica)
    'l10n_do_61030206': '04',  # Mantenimiento Mobiliario y Equipos (P. Jurídica)
    'l10n_do_61050100': '04',  # Gastos por Reparación de Edificios
    'l10n_do_61050200': '04',  # Gastos por Reparación de Equipo de Transporte
    'l10n_do_61050300': '04',  # Gastos por Reparación de Mobiliario y Equipos
    'l10n_do_61050400': '04',  # Gastos por Reparación de Maquinaria
    'l10n_do_61050500': '04',  # Gastos por Reparación de Herramientas
    'l10n_do_61050600': '04',  # Gastos por Reparación de Instalaciones
    # 05 Gastos de representación
    'l10n_do_61060100': '05',  # Relaciones Públicas
    'l10n_do_61060200': '05',  # Publicidad
    'l10n_do_61060600': '05',  # Promociones
    # 07 Gastos financieros
    'l10n_do_61070100': '07',  # Financial Loan Expenses
    'l10n_do_61070300': '07',  # Intereses Bancarios
    'l10n_do_61070400': '07',  # Comisiones Bancarias
    'l10n_do_61070500': '07',  # Comisiones de Tarjeta de Crédito
    'l10n_do_61070600': '07',  # Cargos Bancarios
    'l10n_do_61070900': '07',  # Otro Gastos Financieros
    # 09 Compras y gastos que formarán parte del costo de venta
    'l10n_do_51010100': '09',  # Costos de Bienes
    'l10n_do_51010200': '09',  # Costos de Servicios
    'l10n_do_51020100': '09',  # Costos de Materia Prima
    'l10n_do_51020300': '09',  # Costos Indirectos
    'l10n_do_51020400': '09',  # Costos de Importación
    # 10 Adquisiciones de activos
    'l10n_do_12010101': '10',  # Terrenos
    'l10n_do_12010102': '10',  # Edificaciones
    'l10n_do_12010103': '10',  # Mejoras en Edificaciones
    'l10n_do_12010104': '10',  # Mejoras en Edificaciones y Locales Arrendados
    'l10n_do_12010201': '10',  # Equipos de Transporte Liviano
    'l10n_do_12010202': '10',  # Mobiliarios y Equipos de Oficina
    'l10n_do_12010301': '10',  # Maquinarias
    'l10n_do_12010302': '10',  # Herramientas
    'l10n_do_12010303': '10',  # Instalaciones
    'l10n_do_12010304': '10',  # Sistemas de Cámara y Seguridad
    'l10n_do_12010305': '10',  # Misceláneos u otros activos
    'l10n_do_12040100': '10',  # Marcas y Patentes
    'l10n_do_12040200': '10',  # Licencias y Programas Informáticos
    # 11 Gastos de seguros
    'l10n_do_61020600': '11',  # Seguro de Edificio y Locales
    'l10n_do_61021100': '11',  # Seguros
    'l10n_do_61070700': '11',  # Seguro sobre Préstamos Bancarios
}


def _fill_empty(record, values):
    """Escribe solo los campos que están vacíos. Devuelve True si escribió."""
    vals = {field: value for field, value in values.items() if not record[field]}
    if vals:
        record.write(vals)
    return bool(vals)


def is_dominican(company):
    return (company.account_fiscal_country_id.code == 'DO'
            or company.country_id.code == 'DO')


def autoconfigure_taxes(env, company):
    """Clasificación DGII de los impuestos del plan l10n_do de la compañía."""
    Tax = env['account.tax'].with_context(active_test=False)
    imd = env['ir.model.data'].sudo().search([
        ('module', '=', 'account'),
        ('model', '=', 'account.tax'),
        ('name', 'in', ['%s_%s' % (company.id, tpl) for tpl in TAX_TEMPLATE_VALUES]),
    ])
    changed = 0
    prefix = '%s_' % company.id
    for data in imd:
        tax = Tax.browse(data.res_id).exists()
        template = data.name[len(prefix):]
        if tax and tax.company_id == company and _fill_empty(tax, TAX_TEMPLATE_VALUES[template]):
            changed += 1
    return changed


def ensure_export_tax(env, company):
    """Un ITBIS 0 % de exportación (tasa cero) para las ventas E46/B16.

    La plantilla l10n_do no trae ninguno (solo "ITBIS Exempt", que es exento,
    indicador 4); una exportación va a tasa cero, indicador 3 (Formato e-CF
    v1.0, pág. 36, nota 51). Si la compañía ya tiene un impuesto de ventas al
    0 % marcado como tasa cero, no se crea nada.
    """
    Tax = env['account.tax'].with_context(active_test=False)
    existing = Tax.search([
        *Tax._check_company_domain(company),
        ('type_tax_use', '=', 'sale'),
        ('amount_type', '=', 'percent'),
        ('amount', '=', 0),
        ('dgii_itbis_zero_type', '=', 'zero_rated'),
    ], limit=1)
    if existing:
        return existing
    group = env.ref('account.%s_tax_group_itbis' % company.id, raise_if_not_found=False)
    if not group:
        return Tax
    tax = Tax.with_company(company).create({
        'name': 'ITBIS 0% Exportación',
        'description': 'ITBIS 0% Exportación',
        'type_tax_use': 'sale',
        'amount_type': 'percent',
        'amount': 0,
        'tax_group_id': group.id,
        'country_id': env.ref('base.do').id,
        'company_id': company.id,
        'dgii_itbis_zero_type': 'zero_rated',
        'dgii_tax_kind': 'itbis',
    })
    _logger.info('l10n_do_ncf: impuesto "ITBIS 0%% Exportación" creado para %s', company.name)
    return tax


def autoconfigure_journals(env, company):
    """Forma de pago DGII de los diarios de efectivo, banco y tarjeta."""
    journals = env['account.journal'].with_context(active_test=False).search([
        ('company_id', '=', company.id),
        ('type', 'in', list(JOURNAL_PAYMENT_FORM)),
        ('l10n_do_payment_form', '=', False),
    ])
    for journal in journals:
        journal.l10n_do_payment_form = JOURNAL_PAYMENT_FORM[journal.type]
    return len(journals)


def autoconfigure_accounts(env, company):
    """Tipo 606 de las cuentas del plan l10n_do cuya categoría es clara."""
    imd = env['ir.model.data'].sudo().search([
        ('module', '=', 'account'),
        ('model', '=', 'account.account'),
        ('name', 'in', ['%s_%s' % (company.id, tpl) for tpl in ACCOUNT_TEMPLATE_606]),
    ])
    Account = env['account.account'].with_context(active_test=False)
    prefix = '%s_' % company.id
    changed = 0
    for data in imd:
        account = Account.browse(data.res_id).exists()
        code = ACCOUNT_TEMPLATE_606[data.name[len(prefix):]]
        if account and _fill_empty(account, {'l10n_do_606_expense_type': code}):
            changed += 1
    return changed


def autoconfigure_exterior_retention(env, company):
    """Retención sugerida en el pago al exterior: el ISR del 27 % de la
    plantilla l10n_do ("-27% ISR (L253-12)"), si la compañía no indicó otra.

    DGII, Guía del Contribuyente No. 5, pág. 5: el comprobante para pagos al
    exterior (B17/E47) lleva la retención del 27 % de ISR "según lo establecido
    en los artículos 297 y 305 del Código Tributario". Es una sugerencia: se
    puede cambiar en la línea (un convenio de doble tributación puede fijar
    otra tasa). No se crea ningún impuesto.
    """
    if company.l10n_do_exterior_retention_tax_ids:
        return False
    tax = env.ref('account.%s_ret_27_income_remittance' % company.id, raise_if_not_found=False)
    if not tax or tax.company_id != company or tax.amount != -27.0:
        return False
    company.l10n_do_exterior_retention_tax_ids = tax
    return True


def autoconfigure_user_tz(env, companies):
    """Hora de RD (America/Santo_Domingo) para los usuarios internos de las
    compañías dominicanas que no tienen zona horaria; ver res_users.py."""
    users = env['res.users'].sudo().search([
        ('tz', '=', False), ('share', '=', False), ('company_id', 'in', companies.ids)])
    return len(users._l10n_do_set_default_tz())


def autoconfigure(env, companies=None):
    """Todo lo deducible para las compañías dominicanas (o las indicadas)."""
    companies = companies if companies is not None else env['res.company'].sudo().search([])
    env = env(su=True)
    for company in companies.sudo().filtered(is_dominican):
        taxes = autoconfigure_taxes(env, company)
        export = ensure_export_tax(env, company) if company.chart_template else None
        journals = autoconfigure_journals(env, company)
        accounts = autoconfigure_accounts(env, company)
        # Contacto genérico de las facturas de gastos menores (E43/B13).
        company._l10n_do_minor_expense_partner()
        autoconfigure_exterior_retention(env, company)
        _logger.info(
            'l10n_do_ncf: configuración DGII de %s: %s impuestos, %s diarios y %s cuentas '
            'completados%s', company.name, taxes, journals, accounts,
            ', ITBIS 0 % de exportación listo' if export else '')
    users = autoconfigure_user_tz(env, companies.sudo().filtered(is_dominican))
    if users:
        _logger.info('l10n_do_ncf: zona horaria America/Santo_Domingo en %s usuarios sin zona', users)
