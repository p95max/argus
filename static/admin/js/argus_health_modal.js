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
            ...labels,
            checks: {
                ...FALLBACK_LABELS.checks,
                ...labels?.checks,
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
            return String(value);
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

    function createElement(tagName, { className, text, attributes } = {}) {
        const element = document.createElement(tagName);
        if (className) {
            element.className = className;
        }
        if (text !== undefined) {
            element.textContent = String(text);
        }
        if (attributes) {
            Object.entries(attributes).forEach(([name, value]) => {
                element.setAttribute(name, String(value));
            });
        }
        return element;
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
            return null;
        }

        const mailboxes = summary.mailboxes || {};
        const alerts = summary.alerts || {};
        const openErrors = summary.open_service_errors ?? labels.empty;

        const row = createElement("div", { className: "row" });
        const boxes = [
            {
                background: "bg-gradient-info",
                icon: "fas fa-envelope",
                title: labels.mailboxes,
                value: interpolate(labels.mailbox_active_total, {
                    active: mailboxes.active ?? labels.empty,
                    total: mailboxes.total ?? labels.empty,
                }),
                description: `${labels.connection_errors}: ${mailboxes.errors ?? labels.empty}`,
            },
            {
                background: "bg-gradient-secondary",
                icon: "fas fa-bell",
                title: labels.leads,
                value: interpolate(labels.new_leads, { count: alerts.unread ?? labels.empty }),
                description: `${labels.today}: ${alerts.today ?? labels.empty}`,
            },
            {
                background: "bg-gradient-warning",
                icon: "fas fa-exclamation-triangle",
                title: labels.open_errors,
                value: openErrors,
                description: labels.error_critical,
            },
        ];

        boxes.forEach((box) => {
            const column = createElement("div", { className: "col-md-4" });
            const infoBox = createElement("div", { className: `info-box ${box.background}` });
            const icon = createElement("span", { className: "info-box-icon" });
            icon.append(createElement("i", { className: box.icon }));
            const content = createElement("div", { className: "info-box-content" });
            content.append(
                createElement("span", { className: "info-box-text", text: box.title }),
                createElement("span", { className: "info-box-number", text: box.value }),
                createElement("span", { className: "progress-description", text: box.description })
            );
            infoBox.append(icon, content);
            column.append(infoBox);
            row.append(column);
        });

        return row;
    }

    function renderChecks(checks, labels) {
        if (!checks) {
            return null;
        }

        const wrapper = createElement("div", { className: "table-responsive" });
        const table = createElement("table", { className: "table table-sm table-hover" });
        const headerRow = createElement("tr");
        [labels.component, labels.status, labels.details].forEach((label) => {
            headerRow.append(createElement("th", { text: label }));
        });
        const thead = createElement("thead");
        thead.append(headerRow);
        const tbody = createElement("tbody");

        Object.entries(checks).forEach(([key, check]) => {
            const row = createElement("tr");
            const label = labels.checks[key] || key;
            const statusCell = createElement("td");
            statusCell.append(
                createElement("span", {
                    className: badgeClass(check.status, check.ok),
                    text: humanStatus(check.status, check.ok, labels),
                })
            );
            row.append(
                createElement("td", { text: label }),
                statusCell,
                createElement("td", { text: check.detail || labels.empty })
            );
            tbody.append(row);
        });

        table.append(thead, tbody);
        wrapper.append(table);
        return wrapper;
    }

    function renderReport(report) {
        const labels = mergeLabels(report.labels);
        const fragment = document.createDocumentFragment();
        const overall = createElement("div", { className: "mb-3" });
        overall.append(
            createElement("span", {
                className: badgeClass(report.status, report.ok),
                text: report.ok ? labels.service_ok : labels.service_degraded,
            }),
            createElement("span", {
                className: "text-muted ml-2",
                text: `${labels.checked_at}: ${formatDate(report.generated_at, labels)}`,
            })
        );
        fragment.append(overall);

        const summary = renderSummary(report.summary, labels);
        const checks = renderChecks(report.checks, labels);
        if (summary) {
            fragment.append(summary);
        }
        if (checks) {
            fragment.append(checks);
        }
        return fragment;
    }

    function renderError(error, labels) {
        const alert = createElement("div", { className: "alert alert-danger mb-0" });
        alert.append(
            document.createTextNode(String(labels.load_error)),
            createElement("div", {
                className: "small mt-2",
                text: error.message || error,
            })
        );
        return alert;
    }

    async function openHealthModal(url) {
        const modal = ensureModal();
        const body = modal.querySelector(".modal-body");
        const jsonLink = modal.querySelector(".argus-health-json-link");
        let labels = FALLBACK_LABELS;

        jsonLink.href = url;
        body.replaceChildren(createElement("div", { className: "text-muted", text: labels.loading }));
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

            body.replaceChildren(renderReport(payload));
        } catch (error) {
            body.replaceChildren(renderError(error, labels));
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
