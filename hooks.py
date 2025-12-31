# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: hooks.py
# Descripción: Hooks de instalación y desinstalación
# Compatibilidad: Odoo 19
# Versión: 19.0.2.2.0

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Hook ejecutado después de instalar el módulo.
    """
    _logger.info('l10n_do_ncf: Ejecutando configuración post-instalación...')

    # 1. Crear índices únicos para NCF
    _create_ncf_unique_indexes(env)

    # 2. Configurar etiqueta VAT y impuestos
    _configure_vat_and_taxes(env)

    _logger.info('l10n_do_ncf: Configuración post-instalación completada')


def _create_ncf_unique_indexes(env):
    """
    Crear índices únicos para NCF.
    - NCF emitido (ventas): único por compañía
    - NCF proveedor (compras): único por compañía + proveedor
    """
    
    # 1. Índice único para NCF emitido (ventas)
    try:
        env.cr.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'account_move' 
            AND indexname = 'unique_ncf_per_company'
        """)
        
        if not env.cr.fetchone():
            env.cr.execute("""
                CREATE UNIQUE INDEX unique_ncf_per_company
                ON account_move (company_id, l10n_do_ncf_number)
                WHERE l10n_do_ncf_number IS NOT NULL
                AND move_type IN ('out_invoice', 'out_refund')
            """)
            _logger.info('l10n_do_ncf: Índice único NCF emitido creado')
        else:
            _logger.info('l10n_do_ncf: Índice único NCF emitido ya existe')
            
    except Exception as e:
        _logger.warning('l10n_do_ncf: Error creando índice NCF emitido: %s', str(e))

    # 2. Índice único para NCF proveedor (compras) - NUEVO
    try:
        env.cr.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'account_move' 
            AND indexname = 'unique_vendor_ncf_per_company'
        """)
        
        if not env.cr.fetchone():
            env.cr.execute("""
                CREATE UNIQUE INDEX unique_vendor_ncf_per_company
                ON account_move (company_id, l10n_do_vendor_ncf)
                WHERE l10n_do_vendor_ncf IS NOT NULL
                AND move_type IN ('in_invoice', 'in_refund')
                AND state != 'cancel'
            """)
            _logger.info('l10n_do_ncf: Índice único NCF proveedor creado')
        else:
            _logger.info('l10n_do_ncf: Índice único NCF proveedor ya existe')
            
    except Exception as e:
        _logger.warning('l10n_do_ncf: Error creando índice NCF proveedor: %s', str(e))

    # 3. Índice para búsquedas rápidas de NCF
    try:
        env.cr.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'account_move' 
            AND indexname = 'idx_ncf_search'
        """)
        
        if not env.cr.fetchone():
            env.cr.execute("""
                CREATE INDEX idx_ncf_search
                ON account_move (l10n_do_ncf_number, l10n_do_vendor_ncf, l10n_do_fiscal_type)
                WHERE l10n_do_ncf_number IS NOT NULL 
                OR l10n_do_vendor_ncf IS NOT NULL
            """)
            _logger.info('l10n_do_ncf: Índice de búsqueda NCF creado')
            
    except Exception as e:
        _logger.warning('l10n_do_ncf: Error creando índice búsqueda: %s', str(e))


def _configure_vat_and_taxes(env):
    """
    Configurar etiqueta VAT e impuestos ITBIS
    """
    country_do = env.ref('base.do', raise_if_not_found=False)
    if not country_do:
        _logger.warning('l10n_do_ncf: País DO no encontrado')
        return

    if country_do.vat_label != 'RNC/Cédula':
        country_do.vat_label = 'RNC/Cédula'
        _logger.info('l10n_do_ncf: Etiqueta VAT configurada como RNC/Cédula')

    companies = env['res.company'].search([
        ('country_id', '=', country_do.id)
    ])

    if not companies:
        companies = env['res.company'].search([])

    for company in companies:
        _configure_company_taxes(env, company, country_do)


def _configure_company_taxes(env, company, country_do):
    """
    Configura impuestos ITBIS para una compañía específica.
    """
    _logger.info('l10n_do_ncf: Configurando impuestos para %s', company.name)

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

    if existing_sale_tax and existing_purchase_tax:
        _logger.info('l10n_do_ncf: Impuestos ITBIS ya existen para %s', company.name)
        _set_default_taxes(company, existing_sale_tax, existing_purchase_tax)
        return

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

    _set_default_taxes(company, existing_sale_tax, existing_purchase_tax)
    _create_exempt_taxes(env, company, country_do, itbis_group)


def _set_default_taxes(company, sale_tax, purchase_tax):
    try:
        vals = {}
        if not company.account_sale_tax_id and sale_tax:
            vals['account_sale_tax_id'] = sale_tax.id
        if not company.account_purchase_tax_id and purchase_tax:
            vals['account_purchase_tax_id'] = purchase_tax.id
        if vals:
            company.write(vals)
    except Exception as e:
        _logger.warning('l10n_do_ncf: Error configurando impuestos default: %s', str(e))


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


def uninstall_hook(env):
    """Hook ejecutado antes de desinstalar el módulo."""
    _logger.info('l10n_do_ncf: Ejecutando limpieza pre-desinstalación...')
    
    try:
        env.cr.execute("DROP INDEX IF EXISTS unique_ncf_per_company")
        env.cr.execute("DROP INDEX IF EXISTS unique_vendor_ncf_per_company")
        env.cr.execute("DROP INDEX IF EXISTS idx_ncf_search")
        _logger.info('l10n_do_ncf: Índices NCF eliminados')
    except Exception as e:
        _logger.warning('l10n_do_ncf: Error eliminando índices: %s', str(e))