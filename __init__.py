# -*- coding: utf-8 -*-
from . import models
from . import wizards

def _configure_dgii_taxes(env):
    """Configurar automáticamente impuestos de retención DGII"""
    # ITBIS retenciones (monto negativo + nombre contiene ITBIS)
    itbis_taxes = env['account.tax'].search([
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
    isr_taxes = env['account.tax'].search([
        ('amount', '<', 0),
        ('name', 'ilike', 'ISR'),
        ('dgii_606_bucket', '=', False)
    ])
    if isr_taxes:
        isr_taxes.write({
            'dgii_retention_type': 'isr',
            'dgii_606_bucket': 'isr_retenido'
        })

def post_init_hook(env):
    _configure_dgii_taxes(env)
