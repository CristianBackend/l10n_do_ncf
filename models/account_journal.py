# -*- coding: utf-8 -*-
"""Configuración contable que alimenta los formatos 606 y 607.

Los reportes no inventan códigos: los toman de aquí. Sin configurar, el dato
queda vacío y el asistente de reportes lo lista en "Pendientes de completar".
"""
from odoo import fields, models

# Tabla "Tipo de bienes y servicios comprados" del 606 (Norma General 07-2018,
# Anexo A, casilla 3; instructivo 606, julio 2025).
TIPO_BIENES_606 = [
    ('01', '01 - Gastos de personal'),
    ('02', '02 - Gastos por trabajos, suministros y servicios'),
    ('03', '03 - Arrendamientos'),
    ('04', '04 - Gastos de activos fijos'),
    ('05', '05 - Gastos de representación'),
    ('06', '06 - Otras deducciones admitidas'),
    ('07', '07 - Gastos financieros'),
    ('08', '08 - Gastos extraordinarios'),
    ('09', '09 - Compras y gastos que formarán parte del costo de venta'),
    ('10', '10 - Adquisiciones de activos'),
    ('11', '11 - Gastos de seguros'),
]


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    # Instructivo 606 (julio 2025), casilla 23 "Forma de pago". Solo las formas
    # que corresponden a un pago registrado en un diario: 04 (crédito), 06 (nota
    # de crédito) y 07 (mixto) salen de la propia factura.
    l10n_do_payment_form = fields.Selection(
        [
            ('01', '01 - Efectivo'),
            ('02', '02 - Cheques / transferencias / depósito'),
            ('03', '03 - Tarjeta de crédito / débito'),
            ('05', '05 - Permuta'),
        ],
        string='Forma de pago DGII',
        help='Forma de pago con la que los pagos de este diario se reportan en el '
             '606 y el 607. Un diario de tipo Efectivo sin configurar cuenta como '
             '01 - Efectivo; los demás, sin configurar, quedan pendientes.',
    )


class AccountAccount(models.Model):
    _inherit = 'account.account'

    l10n_do_606_expense_type = fields.Selection(
        TIPO_BIENES_606, string='Tipo 606',
        help='Tipo de bienes y servicios comprados con que se reportan en el 606 '
             'las compras registradas en esta cuenta (Norma General 07-2018, '
             'Anexo A, casilla 3).',
    )
