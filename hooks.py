# -*- coding: utf-8 -*-
# Módulo: l10n_do_ncf
# Archivo: hooks.py
# Descripción: Hooks de instalación y desinstalación
# Compatibilidad: Odoo 19
#
# Unico sitio donde se definen los indices de NCF y los impuestos que crea
# el modulo. Lo usan post_init_hook (instalacion nueva) y el script de
# migracion (bases donde el modulo ya estaba instalado). Todo es idempotente:
# se puede ejecutar varias veces sin duplicar ni fallar.

import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Maximo de duplicados que se muestran en el mensaje de error
# (en el log se listan todos).
MAX_DUPLICATES_IN_ERROR = 50

# Condicion del indice unico de NCF emitido. Se usa tambien para buscar
# duplicados, para que ambas cosas no puedan divergir.
# l10n_do_ncf_number es siempre un NCF emitido por la compañia: en ventas
# (B01, B02, B03, B04, B14, B15, B16) y tambien en compras, donde el modulo
# genera los B11 y B13. Por eso es unico por compañia sin importar el
# proveedor ni el tipo de documento.
NCF_UNIQUE_WHERE = """
    l10n_do_ncf_number IS NOT NULL
    AND l10n_do_ncf_number <> ''
    AND move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
"""

# Condicion del indice unico de NCF de proveedor.
VENDOR_NCF_UNIQUE_WHERE = """
    l10n_do_vendor_ncf IS NOT NULL
    AND l10n_do_vendor_ncf <> ''
    AND move_type IN ('in_invoice', 'in_refund')
    AND state != 'cancel'
"""


def post_init_hook(env):
    """
    Hook ejecutado después de instalar el módulo.
    """
    _logger.info('l10n_do_ncf: Ejecutando configuración post-instalación...')

    # 1. Crear índices únicos para NCF
    ensure_ncf_indexes(env.cr)

    # 2. Configurar etiqueta VAT y impuestos
    configure_vat_and_taxes(env)

    _logger.info('l10n_do_ncf: Configuración post-instalación completada')


# =====================================================================
# INDICES
# =====================================================================
def find_duplicate_ncf(cr):
    """NCF emitidos repetidos dentro de una misma compañía, tanto en ventas
    como los B11/B13 generados en compras.

    Devuelve una lista de dicts: company, ncf, moves (nombres) e ids.
    """
    cr.execute("""
        SELECT c.name,
               m.l10n_do_ncf_number,
               array_agg(m.id ORDER BY m.id),
               array_agg(COALESCE(m.name, '/') ORDER BY m.id)
        FROM account_move m
        JOIN res_company c ON c.id = m.company_id
        WHERE %s
        GROUP BY c.name, m.company_id, m.l10n_do_ncf_number
        HAVING COUNT(*) > 1
        ORDER BY c.name, m.l10n_do_ncf_number
    """ % NCF_UNIQUE_WHERE)
    return [
        {'company': row[0], 'ncf': row[1], 'ids': row[2], 'moves': row[3]}
        for row in cr.fetchall()
    ]


def find_duplicate_vendor_ncf(cr):
    """NCF de proveedor repetidos para el mismo proveedor y compañía."""
    cr.execute("""
        SELECT c.name,
               m.l10n_do_vendor_ncf,
               array_agg(m.id ORDER BY m.id),
               array_agg(COALESCE(m.name, '/') ORDER BY m.id)
        FROM account_move m
        JOIN res_company c ON c.id = m.company_id
        WHERE %s
        GROUP BY c.name, m.company_id, m.commercial_partner_id, m.l10n_do_vendor_ncf
        HAVING COUNT(*) > 1
        ORDER BY c.name, m.l10n_do_vendor_ncf
    """ % VENDOR_NCF_UNIQUE_WHERE)
    return [
        {'company': row[0], 'ncf': row[1], 'ids': row[2], 'moves': row[3]}
        for row in cr.fetchall()
    ]


def _index_definition(cr, index_name):
    cr.execute("""
        SELECT indexdef FROM pg_indexes
        WHERE tablename = 'account_move' AND indexname = %s
    """, (index_name,))
    row = cr.fetchone()
    return row[0] if row else None


def _index_exists(cr, index_name):
    return bool(_index_definition(cr, index_name))


def _raise_duplicates(index_name, titulo, duplicates):
    """Detener la instalacion/actualizacion listando los duplicados."""
    lines = [
        '  - %s | %s | %s (ids %s)' % (
            dup['company'],
            dup['ncf'],
            ', '.join(dup['moves']),
            ', '.join(str(i) for i in dup['ids']),
        )
        for dup in duplicates
    ]
    for line in lines:
        _logger.error('l10n_do_ncf: %s duplicado:%s', titulo, line)

    shown = lines[:MAX_DUPLICATES_IN_ERROR]
    if len(lines) > MAX_DUPLICATES_IN_ERROR:
        shown.append(
            '  ... y %s más (lista completa en el log del servidor)'
            % (len(lines) - MAX_DUPLICATES_IN_ERROR)
        )

    raise UserError(
        'l10n_do_ncf: no se puede crear el índice único "%s" porque hay %s '
        '%s repetidos en la misma compañía.\n\n'
        'Compañía | NCF | Documentos\n%s\n\n'
        'Corrija los documentos duplicados y vuelva a actualizar el módulo. '
        'No se aplicó ningún cambio.'
        % (index_name, len(lines), titulo, '\n'.join(shown))
    )


def ensure_ncf_indexes(cr):
    """
    Crear índices únicos para NCF si no existen.
    - NCF emitido (ventas, y B11/B13 de compras): único por compañía
    - NCF proveedor (compras): único por compañía + proveedor

    Si ya hay duplicados NO se ignora: se listan y se lanza un error, porque
    sin el índice nada impide a nivel de base de datos repetir un NCF.
    """
    # 1. Índice único para NCF emitido (ventas y B11/B13 de compras)
    definition = _index_definition(cr, 'unique_ncf_per_company')
    if definition and 'in_invoice' in definition:
        _logger.info('l10n_do_ncf: Índice único NCF emitido ya existe')
    else:
        duplicates = find_duplicate_ncf(cr)
        if duplicates:
            _raise_duplicates('unique_ncf_per_company', 'NCF emitidos', duplicates)
        if definition:
            # Índice de una versión previa que solo cubría ventas
            cr.execute("DROP INDEX unique_ncf_per_company")
        cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS unique_ncf_per_company
            ON account_move (company_id, l10n_do_ncf_number)
            WHERE %s
        """ % NCF_UNIQUE_WHERE)
        _logger.info('l10n_do_ncf: Índice único NCF emitido creado')

    # 2. Índice único para NCF proveedor (compras)
    if _index_exists(cr, 'unique_vendor_ncf_per_company'):
        _logger.info('l10n_do_ncf: Índice único NCF proveedor ya existe')
    else:
        duplicates = find_duplicate_vendor_ncf(cr)
        if duplicates:
            _raise_duplicates(
                'unique_vendor_ncf_per_company', 'NCF de proveedor', duplicates
            )
        cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS unique_vendor_ncf_per_company
            ON account_move (company_id, commercial_partner_id, l10n_do_vendor_ncf)
            WHERE %s
        """ % VENDOR_NCF_UNIQUE_WHERE)
        _logger.info('l10n_do_ncf: Índice único NCF proveedor creado')

    # 3. Índice para búsquedas rápidas de NCF
    cr.execute("""
        CREATE INDEX IF NOT EXISTS idx_ncf_search
        ON account_move (l10n_do_ncf_number, l10n_do_vendor_ncf, l10n_do_fiscal_type)
        WHERE l10n_do_ncf_number IS NOT NULL
        OR l10n_do_vendor_ncf IS NOT NULL
    """)


# =====================================================================
# IMPUESTOS
# =====================================================================
def configure_vat_and_taxes(env):
    """
    Configurar etiqueta VAT e impuestos del módulo (ITBIS, exentos y
    clasificación DGII de las retenciones).
    """
    country_do = env.ref('base.do', raise_if_not_found=False)
    if not country_do:
        _logger.warning('l10n_do_ncf: País DO no encontrado')
        return

    if country_do.vat_label != 'RNC/Cédula':
        country_do.vat_label = 'RNC/Cédula'
        _logger.info('l10n_do_ncf: Etiqueta VAT configurada como RNC/Cédula')

    # filtered() y no un dominio: res.company.country_id no es almacenado y
    # durante la carga del módulo no se puede buscar por él.
    companies = env['res.company'].search([]).filtered(
        lambda c: c.country_id == country_do
    )

    for company in companies:
        _configure_company_taxes(env, company, country_do)

    _configure_retention_taxes(env)


def _get_itbis_group(env, company, country_do):
    TaxGroup = env['account.tax.group']
    itbis_group = TaxGroup.search([
        *TaxGroup._check_company_domain(company),
        ('name', '=', 'ITBIS'),
        ('country_id', '=', country_do.id),
    ], limit=1)

    if not itbis_group:
        itbis_group = TaxGroup.with_company(company).create({
            'name': 'ITBIS',
            'sequence': 10,
            'country_id': country_do.id,
            'company_id': company.id,
        })
        _logger.info('l10n_do_ncf: Grupo ITBIS creado para %s', company.name)

    return itbis_group


def _configure_company_taxes(env, company, country_do):
    """
    Configura impuestos ITBIS para una compañía específica.
    """
    _logger.info('l10n_do_ncf: Configurando impuestos para %s', company.name)
    Tax = env['account.tax'].with_context(active_test=False)
    company_domain = Tax._check_company_domain(company)

    existing_sale_tax = Tax.search([
        *company_domain,
        ('type_tax_use', '=', 'sale'),
        ('amount', '=', 18),
        ('amount_type', '=', 'percent')
    ], limit=1)

    existing_purchase_tax = Tax.search([
        *company_domain,
        ('type_tax_use', '=', 'purchase'),
        ('amount', '=', 18),
        ('amount_type', '=', 'percent')
    ], limit=1)

    itbis_group = (existing_sale_tax or existing_purchase_tax).tax_group_id \
        or _get_itbis_group(env, company, country_do)

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
    _ensure_exempt_taxes(env, company, country_do, itbis_group)


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


def _ensure_exempt_taxes(env, company, country_do, itbis_group):
    """Garantiza un impuesto exento (0%) de ventas y otro de compras.

    Si ya existe uno (del plan contable o de una ejecución anterior) se
    reutiliza y solo se marca como exento si aún no tiene clasificación.
    Si no existe, se crea ya clasificado.
    """
    Tax = env['account.tax'].with_context(active_test=False)

    for tax_use, name in (('sale', 'Exento Ventas'), ('purchase', 'Exento Compras')):
        exempt = Tax.search([
            *Tax._check_company_domain(company),
            ('type_tax_use', '=', tax_use),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 0),
            '|', '|',
            ('dgii_itbis_zero_type', '=', 'exempt'),
            ('name', 'ilike', 'exento'),
            ('name', 'ilike', 'exempt'),
        ])
        # Impuesto exento del plan contable l10n_do (tax_0_sale / tax_0_purch)
        chart_exempt = env.ref(
            'account.%s_tax_0_%s' % (company.id, 'sale' if tax_use == 'sale' else 'purch'),
            raise_if_not_found=False,
        )
        if chart_exempt and chart_exempt.amount == 0:
            exempt |= chart_exempt

        if exempt:
            exempt.filtered(lambda t: not t.dgii_itbis_zero_type).write({
                'dgii_itbis_zero_type': 'exempt',
            })
            continue

        env['account.tax'].with_company(company).create({
            'name': name,
            'type_tax_use': tax_use,
            'amount_type': 'percent',
            'amount': 0,
            'tax_group_id': itbis_group.id,
            'country_id': country_do.id,
            'company_id': company.id,
            'sequence': 99,
            'dgii_itbis_zero_type': 'exempt',
        })
        _logger.info('l10n_do_ncf: Impuesto "%s" creado para %s', name, company.name)


def _configure_retention_taxes(env):
    """Clasificar para el 606 los impuestos de retención (monto negativo).

    Solo toca los que aún no tienen columna DGII asignada, para no pisar
    una configuración hecha a mano.
    """
    Tax = env['account.tax'].with_context(active_test=False)

    # ITBIS retenciones (monto negativo + nombre contiene ITBIS)
    itbis_taxes = Tax.search([
        ('amount', '<', 0),
        ('name', 'ilike', 'ITBIS'),
        ('dgii_606_bucket', '=', False)
    ])
    if itbis_taxes:
        itbis_taxes.write({
            'dgii_retention_type': 'itbis',
            'dgii_606_bucket': 'itbis_retenido'
        })

    # ISR retenciones (monto negativo + nombre contiene ISR)
    isr_taxes = Tax.search([
        ('amount', '<', 0),
        ('name', 'ilike', 'ISR'),
        ('dgii_606_bucket', '=', False)
    ])
    if isr_taxes:
        isr_taxes.write({
            'dgii_retention_type': 'isr',
            'dgii_606_bucket': 'isr_retenido'
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
