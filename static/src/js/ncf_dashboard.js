/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

// Formato numérico de República Dominicana (1,234.56).
const LOCALE = "es-DO";

export class NcfDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: false,
            alerts: [],
            sequences: [],
            invoices_month: 0,
            purchases_month: 0,
            cancelled_month: 0,
            license: {},
            current_month: "",
            // Modo e-CF (proveedor activo): datos de la plataforma.
            ecf_active: false,
            api_available: true,
            api_message: "",
            provider_label: "",
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
        if (this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            await this.loadDashboardData();
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------------
    // Ayudas de presentación (usadas por la plantilla)
    // ------------------------------------------------------------------

    fmtInt(value) {
        return Number(value || 0).toLocaleString(LOCALE, { maximumFractionDigits: 0 });
    }

    fmtMoney(value) {
        return Number(value || 0).toLocaleString(LOCALE, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // Porcentaje acotado a [0, 100] para anchos de barra.
    pct(value) {
        const n = Number(value) || 0;
        return Math.max(0, Math.min(100, Math.round(n * 10) / 10));
    }

    // Números usados de un rango. La plataforma manda `used`; las secuencias
    // locales (papel) solo traen total y disponibles.
    usedCount(seq) {
        if (seq.used !== undefined && seq.used !== null) {
            return seq.used;
        }
        return Math.max(0, (seq.total || 0) - (seq.available || 0));
    }

    usedPct(seq) {
        return seq.total ? this.pct((this.usedCount(seq) / seq.total) * 100) : 0;
    }

    availPct(seq) {
        return seq.total ? ((seq.available || 0) / seq.total) * 100 : 0;
    }

    // Un rango que no está emitiendo (en cola, agotado, vencido, desactivado)
    // se muestra atenuado; el activo, a color completo.
    isDimmed(seq) {
        return Boolean(seq.status) && seq.status !== "ACTIVE";
    }

    // Color de la barra de uso según lo que QUEDA del rango.
    stockTone(seq) {
        if (this.isDimmed(seq)) {
            return "is-muted";
        }
        const left = this.availPct(seq);
        if (left <= 10) {
            return "is-danger";
        }
        if (left <= 25) {
            return "is-warning";
        }
        return "is-accent";
    }

    availClass(seq) {
        if (this.isDimmed(seq)) {
            return "is-muted-text";
        }
        const left = this.availPct(seq);
        if (left <= 10) {
            return "is-danger-text";
        }
        if (left <= 25) {
            return "is-warning-text";
        }
        return "";
    }

    // Cuota del plan: verde hasta 75 %, ámbar hasta 90 %, rojo después.
    quotaTone(percentage) {
        const p = Number(percentage) || 0;
        if (p >= 90) {
            return "is-danger";
        }
        if (p >= 75) {
            return "is-warning";
        }
        return "is-success";
    }

    seqStatusClass(status) {
        switch (status) {
            case "ACTIVE":
                return "is-success";
            case "QUEUED":
                return "is-info";
            case "EXHAUSTED":
            case "EXPIRED":
                return "is-danger";
            default:
                return "is-neutral";
        }
    }

    invoiceStatusClass(status) {
        switch (String(status || "").toUpperCase()) {
            case "ACCEPTED":
            case "CONDITIONAL":
                return "is-success";
            case "REJECTED":
            case "ERROR":
                return "is-danger";
            case "CONTINGENCY":
                return "is-warning";
            case "VOIDED":
            case "DRAFT":
                return "is-neutral";
            default:
                return "is-info";
        }
    }

    envClass(env) {
        switch (String(env || "").toLowerCase()) {
            case "prod":
            case "production":
                return "is-success";
            case "cert":
            case "certification":
                return "is-warning";
            default:
                return "is-neutral";
        }
    }

    // Avisos agrupados por tipo y título: "Pocas secuencias e-CF" aparece una
    // sola vez con todos los tipos afectados, en vez de una línea por tipo.
    alertGroups() {
        const groups = [];
        const byKey = {};
        for (const alert of this.state.alerts || []) {
            const type = alert.type || "info";
            const key = type + "|" + (alert.title || "");
            if (!byKey[key]) {
                byKey[key] = { key, type, title: alert.title || "", messages: [] };
                groups.push(byKey[key]);
            }
            byKey[key].messages.push(alert.message || "");
        }
        // Primero lo más grave.
        const order = { danger: 0, warning: 1, info: 2, success: 3 };
        return groups.sort((a, b) => (order[a.type] ?? 9) - (order[b.type] ?? 9));
    }

    // Ancho de la barra de "por tipo", relativo al tipo con más comprobantes.
    typeShare(item) {
        const rows = this.state.ncf_by_type || [];
        const max = rows.reduce((m, r) => Math.max(m, r.count || 0), 0);
        return max ? this.pct(((item.count || 0) / max) * 100) : 0;
    }

    // ------------------------------------------------------------------
    // Acciones
    // ------------------------------------------------------------------

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
        const esPos = ncf && (ncf.type === "pos" || ncf.move_type === "pos_order");
        if (!ncf || !ncf.id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: esPos ? "Orden de Punto de Venta" : "Factura",
            res_model: esPos ? "pos.order" : "account.move",
            res_id: ncf.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

NcfDashboard.template = "l10n_do_ncf.Dashboard";
registry.category("actions").add("l10n_do_ncf.dashboard", NcfDashboard);
