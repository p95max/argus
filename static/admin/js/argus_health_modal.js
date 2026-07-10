(function () {
    "use strict";

    const HEALTH_PATH = "/health/full/";
    const MODAL_ID = "argus-health-modal";

    const FALLBACK_LABELS = {
        modal_title: "Argus service status",
        loading: "Loading service diagnostics...",
        open_json: "Open JSON",
        close: "Close",
        service_ok: "Service is running",
        service_degraded: "There are issues",
        checked_at: "Checked",
        mailboxes: "Mailboxes",
        mailbox_active_total: "%(active)s active / %(total)s total",
        connection_errors: "Connection errors",
        leads: "Leads",
        new_leads: "%(count)s new",
        today: "Today",
        open_errors: "Open errors",
        error_critical: "ERROR / CRITICAL",
        component: "Component",
        status: "Status",
        details: "Details",
        status_ok: "OK",
        status_warning: "Needs attention",
        status_error: "Problem",
        load_error: "Could not load service status.",
        empty: "—",
        checks: {
            database: "Database",
            active_mailbox: "Active mailboxes",
            telegram: "Telegram",
            telegram_delivery: "Telegram delivery",
            gmail_recent_check: "Latest Gmail check",
            open_service_errors: "Open service errors",
            secrets: "Production secrets",
            debug: "Debug mode",
            demo_data: "Demo data",
        },
    };

    function mergeLabels(labels) {
        return {
            ...FALLBACK_LABELS,
            ...(labels || {}),
            checks: {
                ...FALLBACK_LABELS.checks,
                ...((labels || {}).checks || {}),
            },
        };
    }

    function interpolate(template, values) {
        return String(template || "").replace(/%\(([^)]+)\)s/g, function (_, key) {
            return values[key] ?? "";
        });
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function localeCode() {
        return document.documentElement.lang || navigator.language || "en";
    }

    function formatDate(value, labels) {
        if (!value) {
            return labels.empty;
        }

        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return escapeHtml(value);
        }

        return date.toLocaleString(localeCode(), {
            dateStyle: "short",
            timeStyle: "medium",
        });
    }

    function badgeClass(status, ok) {
        if (ok) {
            return "badge badge-success";
        }

        if (status === "warning") {
            return "badge badge-warning";
        }

        return "badge badge-danger";
    }

    function humanStatus(status, ok, labels) {
        if (ok) {
            return labels.status_ok;
        }

        if (status === "warning") {
            return labels.status_warning;
        }

        return labels.status_error;
    }

    function ensureModal() {
        let modal = document.getElementById(MODAL_ID);
        if (modal) {
            return modal;
        }

        const labels = FALLBACK_LABELS;
        modal = document.createElement("div");
        modal.id = MODAL_ID;
        modal.className = "modal fade";
        modal.tabIndex = -1;
        modal.setAttribute("role", "dialog");
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = `
            <div class="modal-dialog modal-xl modal-dialog-scrollable" role="document">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${escapeHtml(labels.modal_title)}</h5>
                        <button
                            type="button"
                            class="close"
                            data-dismiss="modal"
                            data-bs-dismiss="modal"
                            data-argus-health-dismiss="true"
                            aria-label="${escapeHtml(labels.close)}"
                        >
                            <span aria-hidden="true">&times;</span>
                        </button>
                    </div>
                    <div class="modal-body">
                        <div class="text-muted">${escapeHtml(labels.loading)}</div>
                    </div>
                    <div class="modal-footer">
                        <a
                            class="btn btn-outline-info argus-health-json-link"
                            href="${HEALTH_PATH}"
                            target="_blank"
                            rel="noopener noreferrer"
                            data-argus-health-json="true"
                        >
                            ${escapeHtml(labels.open_json)}
                        </a>
                        <button
                            type="button"
                            class="btn btn-secondary"
                            data-dismiss="modal"
                            data-bs-dismiss="modal"
                            data-argus-health-dismiss="true"
                        >
                            ${escapeHtml(labels.close)}
                        </button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        return modal;
    }

    function updateModalLabels(modal, labels) {
        modal.querySelector(".modal-title").textContent = labels.modal_title;
        modal.querySelectorAll("[data-argus-health-dismiss]").forEach((button) => {
            button.setAttribute("aria-label", labels.close);
            if (button.classList.contains("btn")) {
                button.textContent = labels.close;
            }
        });
        const jsonLink = modal.querySelector(".argus-health-json-link");
        if (jsonLink) {
            jsonLink.textContent = labels.open_json;
        }
    }

    function showModal() {
        const modal = ensureModal();

        if (window.jQuery && typeof window.jQuery.fn.modal === "function") {
            window.jQuery(modal).modal("show");
            return;
        }

        if (window.bootstrap && typeof window.bootstrap.Modal === "function") {
            const instance = window.bootstrap.Modal.getOrCreateInstance(modal);
            instance.show();
            return;
        }

        window.location.href = HEALTH_PATH;
    }

    function hideModal() {
        const modal = document.getElementById(MODAL_ID);
        if (!modal) {
            return;
        }

        if (window.jQuery && typeof window.jQuery.fn.modal === "function") {
            window.jQuery(modal).modal("hide");
            return;
        }

        if (window.bootstrap && typeof window.bootstrap.Modal === "function") {
            const instance = window.bootstrap.Modal.getOrCreateInstance(modal);
            instance.hide();
            return;
        }

        modal.classList.remove("show");
        modal.style.display = "none";
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
        document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
            backdrop.remove();
        });
    }

    function renderSummary(summary, labels) {
        if (!summary) {
            return "";
        }

        const mailboxes = summary.mailboxes || {};
        const alerts = summary.alerts || {};
        const openErrors = summary.open_service_errors ?? labels.empty;

        return `
            <div class="row">
                <div class="col-md-4">
                    <div class="info-box bg-gradient-info">
                        <span class="info-box-icon"><i class="fas fa-envelope"></i></span>
                        <div class="info-box-content">
                            <span class="info-box-text">${escapeHtml(labels.mailboxes)}</span>
                            <span class="info-box-number">
                                ${escapeHtml(interpolate(labels.mailbox_active_total, {
                                    active: mailboxes.active ?? labels.empty,
                                    total: mailboxes.total ?? labels.empty,
                                }))}
                            </span>
                            <span class="progress-description">
                                ${escapeHtml(labels.connection_errors)}: ${escapeHtml(mailboxes.errors ?? labels.empty)}
                            </span>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="info-box bg-gradient-secondary">
                        <span class="info-box-icon"><i class="fas fa-bell"></i></span>
                        <div class="info-box-content">
                            <span class="info-box-text">${escapeHtml(labels.leads)}</span>
                            <span class="info-box-number">
                                ${escapeHtml(interpolate(labels.new_leads, {
                                    count: alerts.unread ?? labels.empty,
                                }))}
                            </span>
                            <span class="progress-description">
                                ${escapeHtml(labels.today)}: ${escapeHtml(alerts.today ?? labels.empty)}
                            </span>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="info-box bg-gradient-warning">
                        <span class="info-box-icon"><i class="fas fa-exclamation-triangle"></i></span>
                        <div class="info-box-content">
                            <span class="info-box-text">${escapeHtml(labels.open_errors)}</span>
                            <span class="info-box-number">${escapeHtml(openErrors)}</span>
                            <span class="progress-description">${escapeHtml(labels.error_critical)}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderChecks(checks, labels) {
        if (!checks) {
            return "";
        }

        const rows = Object.entries(checks)
            .map(([key, check]) => {
                const label = labels.checks[key] || key;
                return `
                    <tr>
                        <td>${escapeHtml(label)}</td>
                        <td>
                            <span class="${badgeClass(check.status, check.ok)}">
                                ${escapeHtml(humanStatus(check.status, check.ok, labels))}
                            </span>
                        </td>
                        <td>${escapeHtml(check.detail || labels.empty)}</td>
                    </tr>
                `;
            })
            .join("");

        return `
            <div class="table-responsive">
                <table class="table table-sm table-hover">
                    <thead>
                        <tr>
                            <th>${escapeHtml(labels.component)}</th>
                            <th>${escapeHtml(labels.status)}</th>
                            <th>${escapeHtml(labels.details)}</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    function renderReport(report) {
        const labels = mergeLabels(report.labels);
        const overallBadge = `
            <span class="${badgeClass(report.status, report.ok)}">
                ${escapeHtml(report.ok ? labels.service_ok : labels.service_degraded)}
            </span>
        `;

        return `
            <div class="mb-3">
                ${overallBadge}
                <span class="text-muted ml-2">
                    ${escapeHtml(labels.checked_at)}: ${formatDate(report.generated_at, labels)}
                </span>
            </div>
            ${renderSummary(report.summary, labels)}
            ${renderChecks(report.checks, labels)}
        `;
    }

    function renderError(error, labels) {
        return `
            <div class="alert alert-danger mb-0">
                ${escapeHtml(labels.load_error)}
                <div class="small mt-2">${escapeHtml(error.message || error)}</div>
            </div>
        `;
    }

    async function openHealthModal(url) {
        const modal = ensureModal();
        const body = modal.querySelector(".modal-body");
        const jsonLink = modal.querySelector(".argus-health-json-link");
        let labels = FALLBACK_LABELS;

        jsonLink.href = url;
        body.innerHTML = `<div class="text-muted">${escapeHtml(labels.loading)}</div>`;
        showModal();

        try {
            const response = await fetch(url, {
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                },
            });
            const payload = await response.json();
            labels = mergeLabels(payload.labels);
            updateModalLabels(modal, labels);

            if (!response.ok && !payload.checks) {
                throw new Error(payload.detail || `HTTP ${response.status}`);
            }

            body.innerHTML = renderReport(payload);
        } catch (error) {
            body.innerHTML = renderError(error, labels);
        }
    }

    document.addEventListener("click", function (event) {
        const dismissButton = event.target.closest("[data-argus-health-dismiss]");
        if (dismissButton) {
            event.preventDefault();
            hideModal();
            return;
        }

        const link = event.target.closest("a[href]");
        if (!link) {
            return;
        }

        if (link.matches("[data-argus-health-json]")) {
            return;
        }

        const url = new URL(link.href, window.location.origin);
        if (url.origin !== window.location.origin || url.pathname !== HEALTH_PATH) {
            return;
        }

        event.preventDefault();
        openHealthModal(url.href);
    });
})();
