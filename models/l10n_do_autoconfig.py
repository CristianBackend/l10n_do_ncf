# -*- coding: utf-8 -*-
"""Configuración fiscal que se deduce sin ambigüedad del plan contable l10n_do.

Se ejecuta al instalar o actualizar el módulo (hooks.py y la migración
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
    'ret_15_income_person': _RET_ISR,
    'ret_15_income_rent': _RET_ISR,
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


def autoconfigure(env, companies=None):
    """Todo lo deducible para las compañías dominicanas (o las indicadas)."""
    companies = companies if companies is not None else env['res.company'].sudo().search([])
    env = env(su=True)
    for company in companies.sudo().filtered(is_dominican):
        taxes = autoconfigure_taxes(env, company)
        export = ensure_export_tax(env, company) if company.chart_template else None
        journals = autoconfigure_journals(env, company)
        _logger.info(
            'l10n_do_ncf: configuración DGII de %s: %s impuestos y %s diarios completados%s',
            company.name, taxes, journals, ', ITBIS 0 % de exportación listo' if export else '')
