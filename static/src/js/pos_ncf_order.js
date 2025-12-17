/** @odoo-module */
/**
 * Módulo NCF para Punto de Venta
 * Extiende el modelo Order para incluir campos NCF
 * y mostrarlos en el recibo
 */

import { Order } from "@point_of_sale/app/models/order";
import { patch } from "@web/core/utils/patch";

// Extender el modelo Order para incluir campos NCF
patch(Order.prototype, {
    
    setup(options) {
        super.setup(...arguments);
        // Inicializar campos NCF
        this.l10n_do_ncf_number = this.l10n_do_ncf_number || "";
        this.l10n_do_ncf_type = this.l10n_do_ncf_type || "";
        this.l10n_do_partner_vat = this.l10n_do_partner_vat || "";
    },

    /**
     * Inicializar desde JSON (cuando se carga una orden guardada)
     */
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.l10n_do_ncf_number = json.l10n_do_ncf_number || "";
        this.l10n_do_ncf_type = json.l10n_do_ncf_type || "";
        this.l10n_do_partner_vat = json.l10n_do_partner_vat || "";
    },

    /**
     * Exportar a JSON (cuando se guarda la orden)
     */
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.l10n_do_ncf_number = this.l10n_do_ncf_number || "";
        json.l10n_do_ncf_type = this.l10n_do_ncf_type || "";
        json.l10n_do_partner_vat = this.l10n_do_partner_vat || "";
        return json;
    },

    /**
     * Exportar para impresión del recibo
     */
    export_for_printing() {
        const result = super.export_for_printing(...arguments);
        
        // Agregar datos NCF para el recibo
        result.l10n_do_ncf_number = this.l10n_do_ncf_number || "";
        result.l10n_do_ncf_type = this.l10n_do_ncf_type || "";
        
        // Obtener VAT del cliente
        const partner = this.get_partner();
        result.l10n_do_partner_vat = partner ? (partner.vat || "") : "";
        
        return result;
    },

    /**
     * Método para establecer el NCF desde el servidor
     * Se llama después de que el servidor genera el NCF
     */
    set_ncf_data(ncf_number, ncf_type) {
        this.l10n_do_ncf_number = ncf_number || "";
        this.l10n_do_ncf_type = ncf_type || "";
    },

    /**
     * Obtener el tipo de NCF en formato legible
     */
    get_ncf_type_name() {
        const types = {
            'B01': 'Crédito Fiscal',
            'B02': 'Consumidor Final',
            'B14': 'Régimen Especial',
            'B15': 'Gubernamental'
        };
        return types[this.l10n_do_ncf_type] || this.l10n_do_ncf_type || '';
    },

    /**
     * Verificar si la orden tiene NCF
     */
    has_ncf() {
        return !!this.l10n_do_ncf_number;
    },
});