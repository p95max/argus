(function () {
    "use strict";

    const HEALTH_PATH = "/health/full/";
    const MODAL_ID = "argus-health-modal";

    const CHECK_LABELS = {
        database: "База данных",
        active_mailbox: "Активные почтовые ящики",
        telegram: "Telegram",
        gmail_recent_check: "Последняя Gmail-проверка",
        open_service_errors: "Открытые ошибки сервиса",
        secrets: "Production-секреты",
        debug: "Debug-режим",
        demo_data: "Demo-данные",
    };

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatDate(value) {
        if (!value) {
            return "—";
        }

        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return escapeHtml(value);
        }

        return date.toLocaleString("ru-RU", {
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

    function humanStatus(status, ok) {
        if (ok) {
            return "OK";
        }

        if (status === "warning") {
            return "Требует внимания";
        }

        return "Проблема";
    }

    function ensureModal() {
        let modal = document.getElementById(MODAL_ID);
        if (modal) {
            return modal;
        }

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
                        <h5 class="modal-title">Состояние сервиса Argus</h5>
                        <button
                            type="button"
                            class="close"
                            data-dismiss="modal"
                            data-bs-dismiss="modal"
                            data-argus-health-dismiss="true"
                            aria-label="Закрыть"
                        >
                            <span aria-hidden="true">&times;</span>
                        </button>
                    </div>
                    <div class="modal-body">
                        <div class="text-muted">Загружаю диагностику сервиса…</div>
                    </div>
                    <div class="modal-footer">
                        <a class="btn btn-outline-info argus-health-json-link" href="${HEALTH_PATH}">
                            Открыть JSON
                        </a>
                        <button
                            type="button"
                            class="btn btn-secondary"
                            data-dismiss="modal"
                            data-bs-dismiss="modal"
                            data-argus-health-dismiss="true"
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        return modal;
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

    function renderSummary(summary) {
        if (!summary) {
            return "";
        }

        const mailboxes = summary.mailboxes || {};
        const alerts = summary.alerts || {};
        const openErrors = summary.open_service_errors ?? "—";

        return `
            <div class="row">
                <div class="col-md-4">
                    <div class="info-box bg-gradient-info">
                        <span class="info-box-icon"><i class="fas fa-envelope"></i></span>
                        <div class="info-box-content">
                            <span class="info-box-text">Почтовые ящики</span>
                            <span class="info-box-number">
                                ${escapeHtml(mailboxes.active ?? "—")} активных / ${escapeHtml(mailboxes.total ?? "—")} всего
                            </span>
                            <span class="progress-description">
                                Ошибок подключения: ${escapeHtml(mailboxes.errors ?? "—")}
                            </span>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="info-box bg-gradient-secondary">
                        <span class="info-box-icon"><i class="fas fa-bell"></i></span>
                        <div class="info-box-content">
                            <span class="info-box-text">Обращения</span>
                            <span class="info-box-number">
                                ${escapeHtml(alerts.unread ?? "—")} новых
                            </span>
                            <span class="progress-description">
                                Сегодня: ${escapeHtml(alerts.today ?? "—")}
                            </span>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="info-box bg-gradient-warning">
                        <span class="info-box-icon"><i class="fas fa-exclamation-triangle"></i></span>
                        <div class="info-box-content">
                            <span class="info-box-text">Открытые ошибки</span>
                            <span class="info-box-number">${escapeHtml(openErrors)}</span>
                            <span class="progress-description">ERROR / CRITICAL</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderChecks(checks) {
        if (!checks) {
            return "";
        }

        const rows = Object.entries(checks)
            .map(([key, check]) => {
                const label = CHECK_LABELS[key] || key;
                return `
                    <tr>
                        <td>${escapeHtml(label)}</td>
                        <td>
                            <span class="${badgeClass(check.status, check.ok)}">
                                ${escapeHtml(humanStatus(check.status, check.ok))}
                            </span>
                        </td>
                        <td>${escapeHtml(check.detail || "—")}</td>
                    </tr>
                `;
            })
            .join("");

        return `
            <div class="table-responsive">
                <table class="table table-sm table-hover">
                    <thead>
                        <tr>
                            <th>Компонент</th>
                            <th>Статус</th>
                            <th>Детали</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    function renderReport(report) {
        const overallBadge = `
            <span class="${badgeClass(report.status, report.ok)}">
                ${report.ok ? "Сервис работает" : "Есть проблемы"}
            </span>
        `;

        return `
            <div class="mb-3">
                ${overallBadge}
                <span class="text-muted ml-2">
                    Проверено: ${formatDate(report.generated_at)}
                </span>
            </div>
            ${renderSummary(report.summary)}
            ${renderChecks(report.checks)}
        `;
    }

    function renderError(error) {
        return `
            <div class="alert alert-danger mb-0">
                Не удалось загрузить состояние сервиса.
                <div class="small mt-2">${escapeHtml(error.message || error)}</div>
            </div>
        `;
    }

    async function openHealthModal(url) {
        const modal = ensureModal();
        const body = modal.querySelector(".modal-body");
        const jsonLink = modal.querySelector(".argus-health-json-link");

        jsonLink.href = url;
        body.innerHTML = '<div class="text-muted">Загружаю диагностику сервиса…</div>';
        showModal();

        try {
            const response = await fetch(url, {
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                },
            });
            const payload = await response.json();

            if (!response.ok && !payload.checks) {
                throw new Error(payload.detail || `HTTP ${response.status}`);
            }

            body.innerHTML = renderReport(payload);
        } catch (error) {
            body.innerHTML = renderError(error);
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

        const url = new URL(link.href, window.location.origin);
        if (url.origin !== window.location.origin || url.pathname !== HEALTH_PATH) {
            return;
        }

        event.preventDefault();
        openHealthModal(url.href);
    });
})();
