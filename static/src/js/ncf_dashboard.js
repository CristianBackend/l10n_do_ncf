/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class NcfDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            alerts: [],
            sequences: [],
            invoices_month: 0,
            purchases_month: 0,
            cancelled_month: 0,
            license: {},
            current_month: '',
            // Modo e-CF (proveedor activo): datos de la plataforma.
            ecf_active: false,
            api_available: true,
            api_message: '',
            provider_label: '',
            plan: {},
            can_load_sequence: false,
            accepted_month: 0,
            rejected_month: 0,
            pending_month: 0,
        });
        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        const data = await this.orm.call(
            "l10n_do_ncf.dashboard",
            "get_dashboard_data",
            []
        );
        Object.assign(this.state, data);
    }

    async refresh() {
        await this.loadDashboardData();
    }

    // Abre el asistente "Cargar secuencia e-CF" (solo si el usuario es
    // Administrador e-CF) y recarga el panel al cerrarlo.
    async openLoadSequence() {
        await this.action.doAction(
            "l10n_do_ecf_newplain.action_l10n_do_ecf_load_sequence",
            { onClose: () => this.refresh() }
        );
    }

    // Abre el asistente "Desactivar rango e-CF" (PATCH isActive=false) para una
    // secuencia de la plataforma. Solo Administrador e-CF ve el botón. Recarga
    // el panel al cerrarlo.
    async deactivateSequence(seq) {
        await this.action.doAction(
            "l10n_do_ecf_newplain.action_l10n_do_ecf_deactivate_sequence",
            {
                additionalContext: {
                    default_sequence_id: seq.id,
                    default_range_label: seq.prefix + ": " + seq.name,
                    default_available: seq.available,
                },
                onClose: () => this.refresh(),
            }
        );
    }

    openSequences() {
        this.action.doAction("l10n_do_ncf.action_ncf_sequence");
    }

    openInvoices() {
        this.action.doAction("account.action_move_out_invoice_type");
    }

    openPurchases() {
        this.action.doAction("account.action_move_in_invoice_type");
    }

    openReports() {
        this.action.doAction("l10n_do_ncf.action_dgii_report_wizard");
    }

    openLicense() {
        this.action.doAction("l10n_do_ncf.action_ncf_license_config_server");
    }

    openTypes() {
        this.action.doAction("l10n_do_ncf.action_ncf_type");
    }

    openDocument(ncf) {
        // El listado "Ultimos NCF Generados" mezcla facturas (account.move)
        // y ordenes del POS (pos.order). El backend marca el origen en
        // ncf.type ('invoice' o 'pos').
        //
        // Antes se abria SIEMPRE account.move con ese id: para un NCF que
        // venia del POS eso llevaba a una factura distinta y sin relacion,
        // o a un error si el id no existia en account.move.
        const esPos = ncf && (ncf.type === 'pos' || ncf.move_type === 'pos_order');

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: esPos ? 'Orden de Punto de Venta' : 'Factura',
            res_model: esPos ? 'pos.order' : 'account.move',
            res_id: ncf.id,
            views: [[false, 'form']],
            target: 'current',
        });
    }
}

NcfDashboard.template = "l10n_do_ncf.Dashboard";
registry.category("actions").add("l10n_do_ncf.dashboard", NcfDashboard);