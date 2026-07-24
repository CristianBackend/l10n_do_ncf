/** @odoo-module */
/**
 * Modulo NCF para Punto de Venta - Odoo 19
 *
 * Portado desde la API antigua (Odoo 16/17):
 *  - El modelo ahora es PosOrder en @point_of_sale/app/models/pos_order
 *    (antes: Order en @point_of_sale/app/models/order, que ya no existe).
 *  - init_from_JSON / export_as_JSON fueron eliminados en Odoo 18+.
 *  - get_partner() -> getPartner()
 *
 * Ademas asigna el cliente por defecto configurado en el POS
 * (l10n_do_pos_default_partner_id en pos.config).
 */
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);

        // Campos NCF (los llena el backend al generar el comprobante)
        this.l10n_do_ncf_number = this.l10n_do_ncf_number || "";
        this.l10n_do_ncf_type = this.l10n_do_ncf_type || "";

        // Cliente por defecto: solo si la orden aun no tiene uno.
        // Nota: setPartner() de Odoo 19 marca automaticamente "Factura"
        // cuando el partner tiene is_company = true.
        try {
            const config = this.config || this.session?.config;
            const defaultPartner = config?.l10n_do_pos_default_partner_id;
            if (defaultPartner && !this.getPartner()) {
                this.setPartner(defaultPartner);
            }
        } catch (e) {
            console.warn("NCF: no se pudo asignar el cliente por defecto", e);
        }
    },

    /**
     * Datos que se pasan a la plantilla del recibo.
     * El template pos_receipt_ncf.xml lee order.l10n_do_ncf_number
     * y order.l10n_do_ncf_type desde aqui.
     */
    export_for_printing() {
        const result = super.export_for_printing(...arguments);
        result.l10n_do_ncf_number = this.l10n_do_ncf_number || "";
        result.l10n_do_ncf_type = this.l10n_do_ncf_type || "";
        const partner = this.getPartner();
        result.l10n_do_partner_vat = partner ? partner.vat || "" : "";
        return result;
    },

    setNcfData(ncfNumber, ncfType) {
        this.l10n_do_ncf_number = ncfNumber || "";
        this.l10n_do_ncf_type = ncfType || "";
    },

    getNcfTypeName() {
        const types = {
            B01: "Credito Fiscal",
            B02: "Consumidor Final",
            B14: "Regimen Especial",
            B15: "Gubernamental",
        };
        return types[this.l10n_do_ncf_type] || this.l10n_do_ncf_type || "";
    },

    hasNcf() {
        return !!this.l10n_do_ncf_number;
    },
});