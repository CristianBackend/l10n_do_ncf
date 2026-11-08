# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountTax(models.Model):
    _inherit = 'account.tax'

    dgii_606_bucket = fields.Selection([
        ('itbis_retenido', 'ITBIS Retenido (606 col 12)'),
        ('itbis_percibido', 'ITBIS Percibido (606 col 16)'),
        ('isr_retenido', 'ISR Retenido (606 col 18)'),
        ('isr_percibido', 'ISR Percibido (606 col 19)'),
    ], string='Columna DGII 606')

    dgii_retention_type = fields.Selection([
        ('itbis', 'ITBIS'),
        ('isr', 'ISR'),
    ], string='Tipo Retención DGII')

    is_dgii_retention = fields.Boolean(
        string='Es Retención DGII',
        compute='_compute_is_dgii_retention',
        store=True
    )

    # En qué casilla del 606/607 va este impuesto (Norma General 07-2018,
    # Anexos A y B: ITBIS, ISC, otros impuestos/tasas y propina legal van
    # separados). Un impuesto sin clase cuyo porcentaje es 18 o 16 se toma
    # como ITBIS (las dos tasas del ITBIS); cualquier otro sin clase queda
    # pendiente en el reporte.
    # Casilla 17 del 606 (Norma General 07-2018, Anexo A): tipo de retención
    # en ISR. Lo asigna el contador; la configuración automática solo lo pone
    # donde el impuesto de la plantilla l10n_do es inequívoco.
    dgii_isr_retention_type = fields.Selection([
        ('01', '01 - Alquileres'),
        ('02', '02 - Honorarios por servicios'),
        ('03', '03 - Otras rentas'),
        ('04', '04 - Otras rentas (rentas presuntas)'),
        ('05', '05 - Intereses pagados a personas jurídicas residentes'),
        ('06', '06 - Intereses pagados a personas físicas residentes'),
        ('07', '07 - Retención por proveedores del Estado'),
        ('08', '08 - Juegos telefónicos de pronósticos'),
    ], string='Tipo de retención ISR (606)',
        help='Casilla 17 del 606 para las facturas que llevan este impuesto de retención de ISR.')

    dgii_tax_kind = fields.Selection([
        ('itbis', 'ITBIS'),
        ('isc', 'Impuesto Selectivo al Consumo'),
        ('other', 'Otros impuestos / tasas'),
        ('tip', 'Propina legal'),
    ], string='Clase DGII')

    dgii_itbis_zero_type = fields.Selection([
        ('zero_rated', 'ITBIS 0 % (gravado a tasa cero)'),
        ('exempt', 'Exento de ITBIS'),
    ], string='Tipo ITBIS 0 %',
       help='Solo aplica a impuestos con tasa 0 %. Distingue una operación '
            'gravada a tasa cero de una exenta: en el e-CF son indicadores '
            'de facturación distintos (3 = ITBIS 0 %, 4 = Exento).')

    def _l10n_do_retention_kind(self):
        """'itbis' o 'isr' de un impuesto de retención (o False)."""
        self.ensure_one()
        if self.dgii_retention_type:
            return self.dgii_retention_type
        bucket = self.dgii_606_bucket or ''
        return bucket.split('_')[0] if bucket else False

    def _l10n_do_retention_bucket(self):
        """Columna del 606 de un impuesto de retención (o False si no tiene tipo)."""
        self.ensure_one()
        if self.dgii_606_bucket:
            return self.dgii_606_bucket
        return {'itbis': 'itbis_retenido', 'isr': 'isr_retenido'}.get(self.dgii_retention_type, False)

    @api.depends('amount', 'dgii_606_bucket')
    def _compute_is_dgii_retention(self):
        for tax in self:
            tax.is_dgii_retention = tax.amount < 0 and tax.dgii_606_bucket
