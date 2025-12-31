{
    'name': 'Republica Dominicana - Comprobantes Fiscales (NCF)',
    'version': '19.0.3.0.0',
    'summary': 'Gestion completa de NCF para Republica Dominicana segun normativa DGII',
    'description': """
Modulo de Comprobantes Fiscales para Republica Dominicana
=========================================================

Funcionalidades:
----------------
- Generacion automatica de NCF (B01, B02, B03, B04, B11, B12, B13, B14, B15, B17)
- Validacion de RNC/Cedula contra DGII
- Reportes DGII (606, 607, 608, 609)
- Retenciones ISR e ITBIS con buckets 606
- B11 Compra Informal con ISR 2%/10%
- B12 Registro Unico de Ingresos (POS/Retail)
- B13 Gastos Menores
- B17 Pagos al Exterior
- Notas de Debito (B03) en ventas y compras
- Notas de Credito (B04) parciales y totales
- Split automatico bienes/servicios para 606
- Forma de pago mixta (607)
- Tasa de cambio Banco Central
- Pre-validador TXT 606/607
- Conciliacion fiscal 606 vs contabilidad
- Auditoria fiscal NCF
- Bloqueo post-reporte DGII
- Wizards de correccion guiados
- Dashboard de control NCF
- Integracion con Punto de Venta
- Integracion con Ventas y CRM
- Sistema de licencias

Configuracion Automatica:
-------------------------
Al instalar el modulo se configura automaticamente:
- Impuestos ITBIS 18% (Ventas y Compras)
- Impuestos Exentos (0%)
- Tipos de retencion ISR e ITBIS
- Indices unicos para NCF (PostgreSQL)

Configuracion Manual Requerida:
-------------------------------
1. Licencia NCF: Configuracion > NCF > Licencia
2. Secuencias NCF: Configuracion > NCF > Secuencias
3. POS: Configurar secuencias NCF en cada punto de venta

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
        # Vistas principales
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
        # Vistas nuevas v3
        'views/registro_unico_views.xml',
        'views/dgii_validation_views.xml',
        # Reportes
        'report/invoice_report.xml',
        # Wizards
        'wizards/dgii_report_wizard_views.xml',
        'wizards/setup_wizard_views.xml',
        'wizards/ncf_correction_wizard_views.xml',
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
    # Hooks de instalacion
    # 'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
}
