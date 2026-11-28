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
    """Base de pruebas con el plan dominicano cargado.

    DIFERENCIA CON LA 19: allí la base de contabilidad trae el decorador
    AccountTestInvoicingCommon.setup_country('do'), que elige el plan por el
    código de país y deja la compañía con ese país. En Odoo 16 no existe: el
    plan se pasa por su xmlid a setUpClass (chart_template_ref,
    account/tests/common.py:29) y cargarlo solo pone el país FISCAL de la
    compañía (account/models/chart_template.py:577). El país de la compañía hay
    que ponerlo aquí, porque la mayor parte del módulo pregunta por
    company_id.country_id (p. ej. account_move.py).
    """

    @classmethod
    def setUpClass(cls, chart_template_ref='l10n_do.do_chart_template'):
        super().setUpClass(chart_template_ref=chart_template_ref)
        country_do = cls.env.ref('base.do')
        for company in cls.company_data['company'] + cls.company_data_2['company']:
            company.country_id = country_do
            # Sin impuesto de compra por defecto, como en la 19. En Odoo 16
            # account.move.line._get_computed_taxes todavia cae en
            # company.account_purchase_tax_id cuando el producto no trae
            # impuestos de proveedor (account/models/account_move_line.py:
            # 891-908) y cargar el plan l10n_do deja ahi un ITBIS
            # (chart_template.py:647 coge el primer impuesto de compras). La 19
            # quito ese respaldo: una linea de un producto sin impuestos nace
            # sin impuestos. Las pruebas describen una compania asi, para que
            # un pago al exterior (B17/E47, que no lleva ITBIS) se reconozca
            # igual en las dos versiones. Al usuario de 16 que SI tenga
            # impuesto por defecto le toca quitar el ITBIS de la linea, y
            # entonces la factura pasa a "Pago al exterior" porque
            # _compute_l10n_do_fiscal_type depende de invoice_line_ids.tax_ids.
            company.account_purchase_tax_id = False
        cls._setup_ncf_data()


class NcfPosTestMixin(NcfTestMixin):
    """Base de pruebas del Punto de Venta con NCF, sobre TestPoSCommon.

    DIFERENCIA CON LA 19: allí la base del POS es CommonPosTest, con
    setup_country('do') y create_backend_pos_order. Odoo 16 no tiene ninguna
    de las dos: la base es TestPoSCommon (point_of_sale/tests/common.py:134),
    el plan contable se pasa por xmlid y las órdenes se crean como las manda
    el POS, con create_ui_order_data + pos.order.create_from_ui. Aquí está esa
    plomería, compartida por las pruebas del POS de los dos módulos.

    La clase que lo use tiene que heredar también de TestPoSCommon.
    """

    @classmethod
    def _setup_ncf_pos(cls, config=None):
        """Secuencias NCF, producto de prueba y caja configurada."""
        # Odoo 16 guarda los pedidos que fallan al sincronizar, y para eso hace
        # cr.rollback() + cr.commit() (point_of_sale/models/pos_session.py:2124),
        # que dentro de una prueba se lleva por delante la transacción y deja
        # el cursor roto para el resto de la clase. Las pruebas que esperan un
        # fallo de sincronización (una venta e-CF que la plataforma rechaza)
        # necesitan esa captura apagada. En la 19 no hacía falta.
        cls.env['ir.config_parameter'].sudo().set_param(
            'point_of_sale.capture_unprocessed_order', 'False')
        cls.seq_b02 = cls._create_ncf_sequence('02')
        cls.seq_b01 = cls._create_ncf_sequence('01')
        cls.seq_b04 = cls._create_ncf_sequence('04')
        cls.ten_no_tax = cls.env['product.product'].create({
            'name': 'Producto de 10 sin impuesto',
            'type': 'consu',
            'available_in_pos': True,
            'list_price': 10.0,
            'taxes_id': False,
        })
        cls.pos_config_ncf = config or cls.basic_config
        cls.pos_config_ncf.write({
            'l10n_do_ncf_enabled': True,
            'l10n_do_ncf_sequence_id': cls.seq_b02.id,
            'l10n_do_ncf_fiscal_sequence_id': cls.seq_b01.id,
        })
        return cls.pos_config_ncf

    def _open_ncf_session(self):
        """TestPoSCommon toma la caja de self.config y necesita la sesión
        abierta para poder crear órdenes como las manda el POS."""
        self.config = self.pos_config_ncf
        self.config.write({'payment_method_ids': [(6, 0, self.bank_pm1.ids)]})
        return self.open_new_session()

    def _pos_order(self, partner=False, to_invoice=False, refund=False, product=None):
        """Venta del POS (y su devolución, si se pide)."""
        order_data = self.create_ui_order_data(
            [(product or self.ten_no_tax, 1)],
            customer=partner or False,
            is_invoiced=to_invoice,
            payments=[(self.bank_pm1, 10.0)],
        )
        rows = self.env['pos.order'].create_from_ui([order_data])
        order = self.env['pos.order'].browse([row['id'] for row in rows])
        refund_order = self.env['pos.order']
        if refund:
            action = order.refund()
            refund_order = self.env['pos.order'].browse(action['res_id'])
            # Cobrar la devolución: en Odoo 16 el POS la paga con el mismo
            # asistente que el backend (wizard/pos_payment.py).
            self.env['pos.make.payment'].with_context(
                active_id=refund_order.id,
            ).create({
                'amount': refund_order.amount_total,
                'payment_method_id': self.bank_pm1.id,
            }).check()
            if to_invoice:
                # La copia de la devolución no hereda "facturar", y en Odoo 16
                # una orden pagada desde el backend se factura a mano
                # (point_of_sale/models/pos_order.py:841); desde el POS lo hace
                # create_from_ui al sincronizarla.
                refund_order.to_invoice = True
                refund_order.action_pos_order_invoice()
        return order, refund_order

    def _current(self, sequence):
        sequence.invalidate_recordset()
        return sequence.current_number
