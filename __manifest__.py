{
    'name': 'Republica Dominicana - Comprobantes Fiscales (NCF)',
    'version': '19.0.1.4.0',
    'summary': 'Gestion de NCF para Republica Dominicana segun normativa DGII',
    'description': """
Modulo de Comprobantes Fiscales para Republica Dominicana
=========================================================

Funcionalidades:
- Generacion automatica de NCF (B01, B02, B03, B04, B14, B15)
- Validacion de RNC contra DGII
- Reportes DGII (606, 607, 608, 609)
- Retenciones ISR e ITBIS
- Dashboard de control NCF
- Integracion con Punto de Venta (NCF en ticket)
- Integracion con Ventas
- Integracion con CRM
- Sistema de licencias

Compatible con Odoo 19.
    """,
    'author': 'NewPlain',
    'website': 'https://www.newplain.com/',
    'category': 'Accounting/Localizations',
    'license': 'LGPL-3',
    'depends': [
        # Base
        'base',
        'web',
        'mail',
        'contacts',
        # Contabilidad
        'account',
        'l10n_do',
        # Ventas
        'sale',
        'sale_management',
        # CRM
        'crm',
        'sale_crm',
        # Punto de Venta
        'point_of_sale',
    ],
    'data': [
        # Seguridad
        'security/ncf_security.xml',
        'security/ir.model.access.csv',
        # Datos
        'data/ncf_type_data.xml',
        'data/ir_sequence_data.xml',
        'data/retention_data.xml',
        'data/mail_template.xml',
        # Vistas
        'views/license_config_views.xml',
        'views/ncf_type_views.xml',
        'views/ncf_sequence_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/res_company_views.xml',
        'views/ncf_dashboard_views.xml',
        'views/ncf_alert_views.xml',
        'views/retention_views.xml',
        'views/pos_config_views.xml',
        'views/pos_order_views.xml',
        # Wizards
        'wizards/dgii_report_wizard_views.xml',
        'wizards/setup_wizard_views.xml',
        # Menus (al final)
        'views/menu_views.xml',
    ],
    'assets': {
        # Assets para el backend (Dashboard)
        'web.assets_backend': [
            'l10n_do_ncf/static/src/css/ncf_styles.css',
            'l10n_do_ncf/static/src/js/ncf_dashboard.js',
            'l10n_do_ncf/static/src/xml/ncf_dashboard.xml',
        ],
        # Assets para el Punto de Venta
        'point_of_sale._assets_pos': [
            'l10n_do_ncf/static/src/js/pos_ncf_order.js',
            'l10n_do_ncf/static/src/xml/pos_receipt_ncf.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}