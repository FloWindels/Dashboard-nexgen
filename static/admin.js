/* =========================================================
   Services
========================================================= */

const SERVICES_REFRESH_MS = 15000;

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

            grid.appendChild(tile);
        }

        checked.textContent = `Vérifié à ${new Date(data.checked_at * 1000).toLocaleTimeString("fr-FR")}`;
    } catch (error) {
        checked.textContent = "Erreur : " + error.message;
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
};

const ALERT_EVENTS = new Set([
    "login_failure",
    "login_blocked",
    "csrf_rejected",
    "cross_site_blocked",
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
