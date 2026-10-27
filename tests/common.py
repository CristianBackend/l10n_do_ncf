# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

# RNC con dígito verificador válido (pasa la validación de base_vat).
RNC_EMPRESA = '131793916'


class NcfTestMixin:
    """Datos fiscales mínimos para probar NCF: licencia, contactos y secuencias.

    Es un mixin para poder reutilizarlo sobre la base de pruebas de
    contabilidad y sobre la del POS.
    """

    @classmethod
    def _setup_ncf_data(cls):
        cls.company = cls.company_data['company']
        cls.country_do = cls.env.ref('base.do')

        # No consultar la API externa de RNC durante las pruebas.
        cls.env['ir.config_parameter'].sudo().set_param(
            'l10n_do_ncf.classify_query_api', 'False'
        )

        # Las secuencias exigen licencia válida para crearse y activarse.
        cls.env['l10n_do_ncf.license.config'].create({
            'license_key': 'TEST-LICENSE',
            'company_rnc': RNC_EMPRESA,
            'company_id': cls.company.id,
            'is_valid': True,
            'status': 'active',
        })

        cls.partner_consumer = cls.env['res.partner'].create({
            'name': 'Consumidor Final',
            'country_id': cls.country_do.id,
        })
        cls.partner_taxpayer = cls.env['res.partner'].create({
            'name': 'Empresa Contribuyente SRL',
            'is_company': True,
            'country_id': cls.country_do.id,
            'vat': RNC_EMPRESA,
        })
        cls.partner_foreign = cls.env['res.partner'].create({
            'name': 'Foreign Customer Inc.',
            'country_id': cls.env.ref('base.us').id,
        })

    @classmethod
    def _ncf_type(cls, code):
        return cls.env['l10n_do_ncf.type'].search([('code', '=', code)], limit=1)

    @classmethod
    def _create_ncf_sequence(cls, code, range_from=1, range_to=100):
        sequence = cls.env['l10n_do_ncf.sequence'].create({
            'ncf_type_id': cls._ncf_type(code).id,
            'company_id': cls.company.id,
            'range_from': range_from,
            'range_to': range_to,
        })
        sequence.action_activate()
        sequence.flush_recordset()
        return sequence

    # Tipos de venta en papel (B01-B16) que el onchange de la factura comprueba.
    SALES_NCF_CODES = ('01', '02', '03', '04', '14', '15', '16')

    @classmethod
    def _create_sales_ncf_sequences(cls, range_to=1000):
        """Crea secuencias activas para los tipos de venta en papel.

        Evita el aviso de onchange "Sin secuencia" en los tests que solo prueban
        la clasificación del tipo (no la numeración): al existir una secuencia
        activa para cada tipo, el onchange no tiene nada que advertir. Es
        idempotente, así que se puede llamar aunque la clase ya haya creado
        algunas secuencias: salta los tipos que ya tienen una activa.
        """
        Sequence = cls.env['l10n_do_ncf.sequence']
        for code in cls.SALES_NCF_CODES:
            ncf_type = cls._ncf_type(code)
            if not ncf_type:
                continue
            exists = Sequence.search([
                ('company_id', '=', cls.company.id),
                ('ncf_type_id', '=', ncf_type.id),
                ('state', '=', 'active'),
            ], limit=1)
            if not exists:
                cls._create_ncf_sequence(code, range_to=range_to)

    @classmethod
    def _create_invoice(cls, partner, move_type='out_invoice', post=False, **vals):
        invoice = cls.init_invoice(
            move_type,
            partner=partner,
            invoice_date=fields.Date.today(),
            amounts=[1000.0],
        )
        if vals:
            invoice.write(vals)
        if post:
            invoice.action_post()
        return invoice

    @classmethod
    def _create_refund(cls, partner, **vals):
        """Nota de crédito creada por código (sin pasar por el formulario,
        que exige la factura origen)."""
        return cls.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'name': 'Línea de prueba',
                'quantity': 1,
                'price_unit': 1000.0,
                'tax_ids': [],
            })],
            **vals,
        })


class NcfCommon(NcfTestMixin, AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('do')
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_ncf_data()
