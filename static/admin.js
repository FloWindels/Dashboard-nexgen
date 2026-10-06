/* =========================================================
   Services
========================================================= */

const SERVICES_REFRESH_MS = 15000;

const ACTION_LABELS = {
    start: "▶ Démarrer",
    stop: "■ Arrêter",
    restart: "↻ Redémarrer",
};

// Ces redemarrages coupent la connexion au dashboard quelques secondes.
const SELF_RESTARTS = new Set(["hyperflo", "cloudflared"]);

let serverHostname = "";
let serviceActionPending = false;

const STATE_BADGES = {
    ONLINE: "badge ok",
    OFFLINE: "badge",
    ERROR: "badge bad",
};

async function loadServices() {
    const grid = document.getElementById("servicesGrid");
    const checked = document.getElementById("servicesChecked");

    try {
        // Rafraichissement automatique: ne prolonge pas la session.
        const data = await Hyperflo.apiJson("/api/admin/services", {
            headers: { "X-Hyperflo-Poll": "1" },
        });

        grid.replaceChildren();
        for (const service of data.services) {
            const tile = Hyperflo.element("div", `service service-${service.state.toLowerCase()}`);

            const header = Hyperflo.element("div", "service-header");
            header.appendChild(Hyperflo.element("strong", "", service.name));
            header.appendChild(Hyperflo.element("span", STATE_BADGES[service.state] || "badge", service.state));
            tile.appendChild(header);

            tile.appendChild(Hyperflo.element("div", "small", service.detail || ""));

            const source = service.kind === "docker" ? `conteneur ${service.unit}` : service.unit;
            const since = service.since
                ? ` · depuis ${Hyperflo.formatDuration(data.checked_at - service.since)}`
                : "";
            tile.appendChild(Hyperflo.element("div", "small service-unit", source + since));

            if (service.actions && service.actions.length) {
                const actions = Hyperflo.element("div", "service-actions");
                for (const action of service.actions) {
                    const button = Hyperflo.element(
                        "button",
                        action === "stop" ? "btn danger" : "btn",
                        ACTION_LABELS[action] || action
                    );
                    button.type = "button";
                    button.disabled = serviceActionPending;
                    button.addEventListener("click", () => serviceAction(service, action));
                    actions.appendChild(button);
                }
                tile.appendChild(actions);
            }

            grid.appendChild(tile);
        }

        serverHostname = data.hostname || "";
        checked.textContent = `Vérifié à ${new Date(data.checked_at * 1000).toLocaleTimeString("fr-FR")}`;
    } catch (error) {
        checked.textContent = "Erreur : " + error.message;
    }
}

async function serviceAction(service, action) {
    const label = (ACTION_LABELS[action] || action).replace(/^\S+\s/, "").toLowerCase();
    const warning = SELF_RESTARTS.has(service.id)
        ? "\n\nLe dashboard sera coupé quelques secondes."
        : "";
    if (!confirm(`${label} ${service.name} ?${warning}`)) {
        return;
    }

    const checked = document.getElementById("servicesChecked");
    const url = service.kind === "docker"
        ? `/api/docker/${encodeURIComponent(service.unit)}/${action}`
        : `/api/admin/services/${encodeURIComponent(service.id)}/${action}`;

    serviceActionPending = true;
    checked.textContent = `${service.name} : ${label} en cours...`;
    try {
        await Hyperflo.apiJson(url, { method: "POST", headers: { "X-Hyperflo-Action": "1" } });
        checked.textContent = `✓ ${service.name} : ${label} effectué`;
    } catch (error) {
        checked.textContent = SELF_RESTARTS.has(service.id)
            ? `${service.name} redémarre, la page se reconnectera...`
            : `✗ ${service.name} : ${error.message}`;
    } finally {
        serviceActionPending = false;
        setTimeout(loadServices, SELF_RESTARTS.has(service.id) ? 5000 : 500);
    }
}

async function servicesLoop() {
    await loadServices();
    setTimeout(servicesLoop, SERVICES_REFRESH_MS);
}

servicesLoop();


/* =========================================================
   Sessions
========================================================= */

const EVENT_LABELS = {
    login_success: "Connexion réussie",
    login_failure: "Échec de connexion",
    login_blocked: "Connexion bloquée",
    logout: "Déconnexion",
    session_revoked: "Session révoquée",
    sessions_revoked: "Sessions révoquées",
    login_guard_reset: "Blocages levés",
    csrf_rejected: "Jeton CSRF refusé",
    cross_site_blocked: "Requête inter-site refusée",
    docker_action: "Action Docker",
    docker_logs: "Lecture de logs Docker",
    terminal_open: "Terminal ouvert",
    terminal_close: "Terminal fermé",
    terminal_login_failure: "Échec de connexion SSH (terminal)",
    websocket_origin_rejected: "WebSocket d'une autre origine refusé",
    service_action: "Action sur un service",
    service_logs: "Lecture de logs",
    power: "Alimentation du serveur",
    power_denied: "Alimentation refusée",
};

const ALERT_EVENTS = new Set([
    "login_failure",
    "login_blocked",
    "csrf_rejected",
    "cross_site_blocked",
    "terminal_login_failure",
    "websocket_origin_rejected",
    "power",
    "power_denied",
]);


function cell(text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) {
        td.className = className;
    }
    return td;
}


async function loadSessions() {
    const body = document.getElementById("sessionsBody");
    const message = document.getElementById("sessionsMessage");

    try {
        const data = await Hyperflo.apiJson("/api/auth/sessions");
        body.replaceChildren();

        for (const session of data.sessions) {
            const row = document.createElement("tr");

            const idCell = cell(session.id);
            if (session.current) {
                const badge = document.createElement("span");
                badge.className = "badge";
                badge.textContent = "cette session";
                idCell.append(" ", badge);
            }
            row.appendChild(idCell);

            row.appendChild(cell(session.ip));
            const ua = cell(session.user_agent || "-", "ua");
            ua.title = session.user_agent || "";
            row.appendChild(ua);
            row.appendChild(cell(Hyperflo.formatDate(session.created)));
            row.appendChild(cell(Hyperflo.formatDate(session.last_seen)));
            row.appendChild(cell(Hyperflo.formatDate(session.expires)));

            const actions = document.createElement("td");
            const revoke = document.createElement("button");
            revoke.type = "button";
            revoke.className = "btn danger";
            revoke.textContent = session.current ? "Me déconnecter" : "Révoquer";
            revoke.addEventListener("click", () => revokeSession(session.id));
            actions.appendChild(revoke);
            row.appendChild(actions);

            body.appendChild(row);
        }

        message.textContent = `${data.sessions.length} session(s) active(s).`;
    } catch (error) {
        message.textContent = "Erreur : " + error.message;
    }
}

async function revokeSession(id) {
    try {
        const data = await Hyperflo.apiJson(
            `/api/auth/sessions/${encodeURIComponent(id)}/revoke`,
            { method: "POST" }
        );
        if (data.current) {
            window.location.replace("/login");
            return;
        }
    } catch (error) {
        document.getElementById("sessionsMessage").textContent = "Erreur : " + error.message;
    }
    loadSessions();
    loadSecurity();
}

async function revokeOtherSessions() {
    try {
        const data = await Hyperflo.apiJson("/api/auth/sessions/revoke-others", { method: "POST" });
        document.getElementById("sessionsMessage").textContent =
            `${data.revoked} session(s) déconnectée(s).`;
    } catch (error) {
        document.getElementById("sessionsMessage").textContent = "Erreur : " + error.message;
    }
    loadSessions();
    loadSecurity();
}


/* =========================================================
   Securite
========================================================= */

function eventDetails(event) {
    return Object.entries(event)
        .filter(([key]) => !["time", "event", "ip"].includes(key))
        .map(([key, value]) => `${key}=${value}`)
        .join("  ");
}

async function loadSecurity() {
    const summary = document.getElementById("guardSummary");
    const blockedList = document.getElementById("blockedIps");
    const eventsBody = document.getElementById("eventsBody");

    try {
        const data = await Hyperflo.apiJson("/api/security/overview?limit=100");
        const guard = data.login_guard;
        const minutes = Math.round(guard.window / 60);

        summary.replaceChildren();
        const status = document.createElement("span");
        status.className = guard.global_locked ? "badge bad" : "badge";
        status.textContent = guard.global_locked
            ? "Connexions bloquées pour tous"
            : "Connexions autorisées";
        summary.append(
            status,
            ` ${guard.global_failures}/${guard.global_limit} échecs au total sur ${minutes} min,`
            + ` ${guard.per_ip_limit} échecs max par IP.`
        );

        blockedList.replaceChildren();
        for (const blocked of guard.blocked_ips) {
            const item = document.createElement("li");
            item.textContent = `${blocked.ip} bloquée jusqu'à ${Hyperflo.formatDate(blocked.until)}`;
            blockedList.appendChild(item);
        }

        eventsBody.replaceChildren();
        for (const event of data.events) {
            const row = document.createElement("tr");
            row.appendChild(cell(Hyperflo.formatDate(event.time)));

            const label = cell("");
            const badge = document.createElement("span");
            badge.className = ALERT_EVENTS.has(event.event) ? "badge bad" : "badge";
            badge.textContent = EVENT_LABELS[event.event] || event.event;
            label.appendChild(badge);
            row.appendChild(label);

            row.appendChild(cell(event.ip || "-"));
            row.appendChild(cell(eventDetails(event)));
            eventsBody.appendChild(row);
        }
    } catch (error) {
        summary.textContent = "Erreur : " + error.message;
    }
}

async function unblockLogins() {
    try {
        await Hyperflo.apiJson("/api/security/unblock", { method: "POST" });
    } catch (error) {
        document.getElementById("guardSummary").textContent = "Erreur : " + error.message;
        return;
    }
    loadSecurity();
}

document.getElementById("revokeOthersButton").addEventListener("click", revokeOtherSessions);
document.getElementById("unblockButton").addEventListener("click", unblockLogins);
document.getElementById("refreshEventsButton").addEventListener("click", loadSecurity);

loadSessions();
loadSecurity();



/* =========================================================
   Logs
========================================================= */

async function loadLogs() {
    const source = document.getElementById("logSource").value;
    const lines = document.getElementById("logLines").value;
    const output = document.getElementById("serviceLogs");
    output.textContent = "Chargement...";

    let url;
    if (source.startsWith("container:")) {
        const name = source.slice("container:".length);
        url = `/api/docker/${encodeURIComponent(name)}/logs?lines=${lines}`;
    } else if (source === "hyperflo-audit") {
        url = `/api/admin/logs?source=hyperflo&lines=1000&audit_only=true`;
    } else {
        url = `/api/admin/logs?source=${encodeURIComponent(source)}&lines=${lines}`;
    }

    try {
        const data = await Hyperflo.apiJson(url);
        output.textContent = data.logs || "Aucun log.";
        output.scrollTop = output.scrollHeight;
    } catch (error) {
        output.textContent = "Erreur : " + error.message;
    }
}

document.getElementById("loadLogsButton").addEventListener("click", loadLogs);


/* =========================================================
   Alimentation (nom du serveur + code TOTP)
========================================================= */

const POWER_QUESTIONS = {
    reboot: "Redémarrer le serveur ?",
    poweroff: "Éteindre le serveur ? Il faudra le rallumer physiquement.",
};

let powerAction = null;

const powerForm = document.getElementById("powerForm");
const powerMessage = document.getElementById("powerMessage");

function openPowerForm(action) {
    powerAction = action;
    document.getElementById("powerQuestion").textContent = POWER_QUESTIONS[action];
    document.getElementById("powerHostname").textContent = serverHostname || "?";
    document.getElementById("powerConfirm").value = "";
    document.getElementById("powerTotp").value = "";
    powerMessage.textContent = "";
    powerForm.classList.remove("hidden");
    document.getElementById("powerConfirm").focus();
}

function closePowerForm() {
    powerAction = null;
    powerForm.classList.add("hidden");
}

for (const button of document.querySelectorAll("[data-power]")) {
    button.addEventListener("click", () => openPowerForm(button.dataset.power));
}

document.getElementById("powerCancel").addEventListener("click", closePowerForm);

powerForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!powerAction) {
        return;
    }

    const totpInput = document.getElementById("powerTotp");
    const submit = document.getElementById("powerSubmit");
    submit.disabled = true;
    powerMessage.textContent = "Arrêt propre de Minecraft puis "
        + (powerAction === "reboot" ? "redémarrage" : "extinction") + "...";

    try {
        await Hyperflo.apiJson("/api/admin/power", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Hyperflo-Action": "1" },
            body: JSON.stringify({
                action: powerAction,
                confirm: document.getElementById("powerConfirm").value,
                totp: totpInput.value.replace(/\D/g, ""),
            }),
        });
        powerMessage.textContent = powerAction === "reboot"
            ? "✓ Redémarrage lancé. Le dashboard reviendra dans une à deux minutes."
            : "✓ Extinction lancée.";
        closePowerForm();
    } catch (error) {
        powerMessage.textContent = "✗ " + error.message;
        totpInput.value = "";
    } finally {
        submit.disabled = false;
    }
});
