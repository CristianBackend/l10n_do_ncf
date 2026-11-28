odoo.define('l10n_do_ncf.pos_order', function (require) {
'use strict';

/**
 * Módulo NCF para Punto de Venta - Odoo 16
 *
 * DIFERENCIA CON LA 19: el POS de Odoo 16 todavía usa el cargador antiguo
 * (odoo.define + require) y se extiende con Registries.Model.extend sobre la
 * clase Order de point_of_sale.models, no con patch() sobre PosOrder. Ver
 * addons/l10n_fr_pos_cert/static/src/js/pos.js, que hace lo mismo.
 *
 * También vuelven init_from_JSON / export_as_JSON, que en la 19 ya no
 * existían: en 16 son el camino por el que los campos propios de la orden
 * viajan entre el navegador y el servidor.
 *
 * Qué hace:
 *  - guarda el NCF que devuelve el servidor y lo pone en el ticket;
 *  - genera el identificador de la orden (l10n_do_pos_uuid), que el conector
 *    e-CF usa como clave de idempotencia (en la 19 es el uuid propio de
 *    pos.order, que Odoo 16 no tiene);
 *  - asigna el cliente por defecto configurado en la caja.
 */

const { Order, PosGlobalState } = require('point_of_sale.models');
const Registries = require('point_of_sale.Registries');

/** Identificador único de la orden (v4). */
function l10nDoUuid() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

const NCF_TYPE_NAMES = {
    B01: 'Crédito Fiscal',
    B02: 'Consumidor Final',
    B14: 'Régimen Especial',
    B15: 'Gubernamental',
};

const L10nDoNcfOrder = (Order) => class L10nDoNcfOrder extends Order {
    constructor() {
        super(...arguments);
        // Los rellena el servidor al generar el comprobante; si la orden se
        // restauró del navegador, init_from_JSON ya los dejó puestos.
        this.l10n_do_ncf_number = this.l10n_do_ncf_number || '';
        this.l10n_do_ncf_type = this.l10n_do_ncf_type || '';
        this.l10n_do_pos_uuid = this.l10n_do_pos_uuid || l10nDoUuid();
        this._l10nDoSetDefaultPartner();
    }

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.l10n_do_ncf_number = json.l10n_do_ncf_number || '';
        this.l10n_do_ncf_type = json.l10n_do_ncf_type || '';
        // El identificador se conserva: es lo que evita que un reintento
        // gaste otro e-NCF.
        this.l10n_do_pos_uuid = json.l10n_do_pos_uuid || this.l10n_do_pos_uuid || l10nDoUuid();
    }

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.l10n_do_ncf_number = this.l10n_do_ncf_number || '';
        json.l10n_do_ncf_type = this.l10n_do_ncf_type || '';
        json.l10n_do_pos_uuid = this.l10n_do_pos_uuid || '';
        return json;
    }

    /** Datos que lee la plantilla del ticket (pos_receipt_ncf.xml). */
    export_for_printing() {
        const receipt = super.export_for_printing(...arguments);
        const partner = this.get_partner();
        const company = this.pos.company;
        receipt.l10n_do_ncf_number = this.l10n_do_ncf_number || '';
        receipt.l10n_do_ncf_type = this.l10n_do_ncf_type || '';
        receipt.l10n_do_ncf_type_name = this.getNcfTypeName();
        receipt.l10n_do_partner_vat = (partner && partner.vat) || '';
        receipt.l10n_do_is_do = this.l10nDoIsDo();
        receipt.l10n_do_company_locality = this.l10nDoCompanyLocality();
        receipt.l10n_do_issue_date = this.l10nDoIssueDate();
        receipt.l10n_do_ticket_ref = this.uid || '';
        receipt.l10n_do_company_street = (company && company.street) || '';
        return receipt;
    }

    setNcfData(ncfNumber, ncfType) {
        this.l10n_do_ncf_number = ncfNumber || '';
        this.l10n_do_ncf_type = ncfType || '';
    }

    getNcfTypeName() {
        return NCF_TYPE_NAMES[this.l10n_do_ncf_type] || this.l10n_do_ncf_type || '';
    }

    hasNcf() {
        return !!this.l10n_do_ncf_number;
    }

    /** Ticket con el diseño de República Dominicana. */
    l10nDoIsDo() {
        const company = this.pos.company;
        return !!(company && company.country && company.country.code === 'DO');
    }

    /** Municipio y provincia del emisor en una línea. */
    l10nDoCompanyLocality() {
        const company = this.pos.company;
        if (!company) {
            return '';
        }
        const state = Array.isArray(company.state_id) ? company.state_id[1] : '';
        return [company.city, state].filter((part) => part).join(', ');
    }

    /** Fecha de emisión dd-MM-aaaa, como en el e-CF. */
    l10nDoIssueDate() {
        const date = this.validation_date || this.creation_date || new Date();
        const value = date instanceof Date ? date : new Date(date);
        if (isNaN(value.getTime())) {
            return '';
        }
        const pad = (n) => String(n).padStart(2, '0');
        return `${pad(value.getDate())}-${pad(value.getMonth() + 1)}-${value.getFullYear()}`;
    }

    /** Cliente por defecto de la caja, si la orden todavía no tiene uno. */
    _l10nDoSetDefaultPartner() {
        try {
            const config = this.pos && this.pos.config;
            const value = config && config.l10n_do_pos_default_partner_id;
            const partnerId = Array.isArray(value) ? value[0] : value;
            if (!partnerId || this.get_partner()) {
                return;
            }
            const partner = this.pos.db.get_partner_by_id(partnerId);
            if (partner) {
                this.set_partner(partner);
                // En Odoo 16 elegir un contacto no marca "Factura" solo (en la
                // 19 sí cuando es una empresa): se marca aquí.
                this.set_to_invoice(true);
            }
        } catch (error) {
            console.warn('NCF: no se pudo asignar el cliente por defecto', error);
        }
    }
};

Registries.Model.extend(Order, L10nDoNcfOrder);

/**
 * El comprobante que asignó el servidor vuelve en el resultado de la
 * sincronización y se copia en la orden que está en memoria, que es la que
 * imprime el ticket.
 *
 * DIFERENCIA CON LA 19: allí la orden vuelve completa del servidor y sus
 * campos ya están en el modelo del POS. En Odoo 16 la respuesta de
 * create_from_ui trae solo lo que pida el backend (ver
 * models/pos_order.py, _l10n_do_pos_sync_fields), y hay que copiarlo a mano.
 */
const L10nDoNcfPosGlobalState = (PosGlobalState) => class L10nDoNcfPosGlobalState extends PosGlobalState {
    async _save_to_server(orders, options) {
        const result = await super._save_to_server(...arguments);
        try {
            this._l10nDoApplySyncResult(result);
        } catch (error) {
            console.warn('NCF: no se pudo leer el comprobante de la respuesta', error);
        }
        return result;
    }

    /** Copia los campos l10n_do_* de la respuesta a cada orden en memoria. */
    _l10nDoApplySyncResult(result) {
        if (!Array.isArray(result) || !result.length) {
            return;
        }
        const byName = {};
        for (const order of this.get_order_list()) {
            byName[order.name] = order;
        }
        for (const row of result) {
            const order = byName[row.pos_reference];
            if (!order) {
                continue;
            }
            for (const key of Object.keys(row)) {
                if (key.startsWith('l10n_do_')) {
                    order[key] = row[key];
                }
            }
        }
    }
};

Registries.Model.extend(PosGlobalState, L10nDoNcfPosGlobalState);

return { L10nDoNcfOrder, L10nDoNcfPosGlobalState };

});
