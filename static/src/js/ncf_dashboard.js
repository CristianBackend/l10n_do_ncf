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
            current_month: ''
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
        // Abrir el documento (factura) asociado al NCF
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'account.move',
            res_id: ncf.id,
            views: [[false, 'form']],
            target: 'current',
        });
    }
}

NcfDashboard.template = "l10n_do_ncf.Dashboard";
registry.category("actions").add("l10n_do_ncf.dashboard", NcfDashboard);
