# -*- coding: utf-8 -*-
# Modulo: l10n_do_ncf
# Archivo: hooks.py
# Descripcion: Hooks de instalacion y desinstalacion
# Compatibilidad: Odoo 19

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Hook ejecutado despues de instalar el modulo.
    Configura automaticamente:
    - Impuestos ITBIS por defecto
    - Etiqueta RNC/Cedula para Republica Dominicana
    """
    _logger.info('l10n_do_ncf: Ejecutando configuracion post-instalacion...')
    
    # Obtener pais Republica Dominicana
    country_do = env.ref('base.do', raise_if_not_found=False)
    if not country_do:
        _logger.warning('l10n_do_ncf: Pais DO no encontrado')
        return
    
    # Configurar etiqueta VAT como RNC/Cedula
    if country_do.vat_label != 'RNC/Cedula':
        country_do.vat_label = 'RNC/Cedula'
        _logger.info('l10n_do_ncf: Etiqueta VAT configurada como RNC/Cedula')
    
    # Buscar companias dominicanas
    companies = env['res.company'].search([
        ('country_id', '=', country_do.id)
    ])
    
    if not companies:
        companies = env['res.company'].search([])
    
    for company in companies:
        _configure_company_taxes(env, company, country_do)
    
    _logger.info('l10n_do_ncf: Configuracion post-instalacion completada')


def _configure_company_taxes(env, company, country_do):
    """Configura impuestos ITBIS para una compania especifica."""
    _logger.info('l10n_do_ncf: Configurando impuestos para %s', company.name)
    
    # Verificar si ya tiene impuestos ITBIS configurados
    existing_sale_tax = env['account.tax'].search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'sale'),
        ('amount', '=', 18),
        ('amount_type', '=', 'percent')
    ], limit=1)
    
    existing_purchase_tax = env['account.tax'].search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'purchase'),
        ('amount', '=', 18),
        ('amount_type', '=', 'percent')
    ], limit=1)
    
    # Si ya existen, solo asegurar que esten como default
    if existing_sale_tax and existing_purchase_tax:
        _logger.info('l10n_do_ncf: Impuestos ITBIS ya existen para %s', company.name)
        _set_default_taxes(company, existing_sale_tax, existing_purchase_tax)
        return
    
    # Buscar o crear grupo de impuestos ITBIS
    itbis_group = env['account.tax.group'].search([
        ('name', '=', 'ITBIS'),
        ('country_id', '=', country_do.id)
    ], limit=1)
    
    if not itbis_group:
        itbis_group = env['account.tax.group'].create({
            'name': 'ITBIS',
            'sequence': 10,
            'country_id': country_do.id,
        })
        _logger.info('l10n_do_ncf: Grupo ITBIS creado')
    
    # Crear impuesto ITBIS Ventas si no existe
    if not existing_sale_tax:
        existing_sale_tax = env['account.tax'].with_company(company).create({
            'name': 'ITBIS 18% Ventas',
            'type_tax_use': 'sale',
            'amount_type': 'percent',
            'amount': 18,
            'tax_group_id': itbis_group.id,
            'country_id': country_do.id,
            'company_id': company.id,
            'description': 'ITBIS 18%',
            'sequence': 1,
        })
        _logger.info('l10n_do_ncf: ITBIS 18%% Ventas creado para %s', company.name)
    
    # Crear impuesto ITBIS Compras si no existe
    if not existing_purchase_tax:
        existing_purchase_tax = env['account.tax'].with_company(company).create({
            'name': 'ITBIS 18% Compras',
            'type_tax_use': 'purchase',
            'amount_type': 'percent',
            'amount': 18,
            'tax_group_id': itbis_group.id,
            'country_id': country_do.id,
            'company_id': company.id,
            'description': 'ITBIS 18%',
            'sequence': 1,
        })
        _logger.info('l10n_do_ncf: ITBIS 18%% Compras creado para %s', company.name)
    
    # Configurar impuestos por defecto
    _set_default_taxes(company, existing_sale_tax, existing_purchase_tax)
    
    # Crear impuestos exentos
    _create_exempt_taxes(env, company, country_do, itbis_group)


def _set_default_taxes(company, sale_tax, purchase_tax):
    """Configura los impuestos por defecto de la compania."""
    try:
        vals = {}
        if not company.account_sale_tax_id and sale_tax:
            vals['account_sale_tax_id'] = sale_tax.id
        if not company.account_purchase_tax_id and purchase_tax:
            vals['account_purchase_tax_id'] = purchase_tax.id
        
        if vals:
            company.write(vals)
            _logger.info('l10n_do_ncf: Impuestos por defecto configurados para %s', company.name)
    except Exception as e:
        _logger.warning('l10n_do_ncf: No se pudieron configurar impuestos por defecto: %s', str(e))


def _create_exempt_taxes(env, company, country_do, itbis_group):
    """Crea impuestos exentos (0%) si no existen."""
    exempt_sale = env['account.tax'].search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'sale'),
        ('amount', '=', 0),
        ('name', 'ilike', 'exento')
    ], limit=1)
    
    exempt_purchase = env['account.tax'].search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'purchase'),
        ('amount', '=', 0),
        ('name', 'ilike', 'exento')
    ], limit=1)
    
    if not exempt_sale:
        env['account.tax'].with_company(company).create({
            'name': 'Exento Ventas',
            'type_tax_use': 'sale',
            'amount_type': 'percent',
            'amount': 0,
            'tax_group_id': itbis_group.id,
            'country_id': country_do.id,
            'company_id': company.id,
            'sequence': 99,
        })
        _logger.info('l10n_do_ncf: Exento Ventas creado para %s', company.name)
    
    if not exempt_purchase:
        env['account.tax'].with_company(company).create({
            'name': 'Exento Compras',
            'type_tax_use': 'purchase',
            'amount_type': 'percent',
            'amount': 0,
            'tax_group_id': itbis_group.id,
            'country_id': country_do.id,
            'company_id': company.id,
            'sequence': 99,
        })
        _logger.info('l10n_do_ncf: Exento Compras creado para %s', company.name)


def uninstall_hook(env):
    """Hook ejecutado antes de desinstalar el modulo."""
    _logger.info('l10n_do_ncf: Modulo desinstalado. Los impuestos y cuentas se mantienen.')
