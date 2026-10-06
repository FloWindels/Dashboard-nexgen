"use strict";

/*
 * Page Docker: liste des conteneurs (rafraichie toutes les 5 s), CPU/RAM,
 * actions start/stop/restart, details et logs.
 */

const { apiJson, element } = Hyperflo;

const REFRESH_MS = 5000;
// Rafraichissement automatique: ne prolonge pas la session.
const POLL = { headers: { "X-Hyperflo-Poll": "1" } };

const ACTION_LABELS = {
    start: "démarrer",
    stop: "arrêter",
    restart: "redémarrer",
};

let containers = [];
// Conteneur pilote avec playit.service (voir docker_api.py).
let minecraft = { container: "minecraft", playit: "unknown" };
let stats = { available: true, stats: {} };
let pendingContainer = null;
let selectedContainer = null;

function setText(id, value) {
    document.getElementById(id).textContent = value;
}

function stateBadge(state) {
    const labels = { running: "en cours", exited: "arrêté", paused: "en pause", restarting: "redémarre", created: "créé" };
    const className = state === "running" ? "badge ok" : state === "restarting" ? "badge" : "badge bad";
    return element("span", className, labels[state] || state || "?");
}

function actionButton(label, className, disabled, onClick) {
    const button = element("button", className, label);
    button.type = "button";
    button.disabled = disabled;
    button.addEventListener("click", onClick);
    return button;
}


/* =========================================================
   Liste
========================================================= */

function renderContainers() {
    const body = document.getElementById("dockerBody");
    body.replaceChildren();

    for (const container of containers) {
        const running = container.state === "running";
        const busy = pendingContainer !== null;
        const containerStats = stats.stats[container.name];
        const row = document.createElement("tr");

        const nameCell = element("td", "container-name", container.name);
        if (container.name === minecraft.container) {
            const active = minecraft.playit === "active";
            nameCell.appendChild(
                element("div", active ? "badge ok playit" : "badge bad playit", `Playit : ${active ? "actif" : minecraft.playit}`)
            );
        }
        row.appendChild(nameCell);

        const image = element("td", "container-image", container.image);
        image.title = container.image;
        row.appendChild(image);

        const state = element("td");
        state.appendChild(stateBadge(container.state));
        row.appendChild(state);

        row.appendChild(element("td", "small", container.status || "-"));

        const ports = element("td", "ports");
        if (container.ports.length) {
            for (const port of container.ports) {
                ports.appendChild(element("div", "", port));
            }
        } else {
            ports.textContent = "-";
        }
        row.appendChild(ports);

        if (running && containerStats) {
            const cpu = containerStats.cpu_percent;
            row.appendChild(element("td", "num", cpu === null ? "-" : `${cpu.toFixed(1)} %`));
            const ram = element("td", "num", containerStats.mem_usage.split("/")[0].trim() || "-");
            ram.title = containerStats.mem_usage;
            row.appendChild(ram);
        } else {
            row.appendChild(element("td", "num small", "—"));
            row.appendChild(element("td", "num small", "—"));
        }

        const actions = element("td");
        const group = element("div", "actions");
        group.append(
            actionButton("📊 Détails", "btn", false, () => openDetails(container.name)),
            actionButton("▶ Start", "btn", busy || running, () => dockerAction(container.name, "start")),
            actionButton("■ Stop", "btn danger", busy || !running, () => dockerAction(container.name, "stop")),
            actionButton("↻ Restart", "btn restart", busy || !running, () => dockerAction(container.name, "restart")),
        );
        actions.appendChild(group);
        row.appendChild(actions);

        body.appendChild(row);
    }

    const runningCount = containers.filter(container => container.state === "running").length;
    setText("dockerSummary", `${runningCount} en cours sur ${containers.length} conteneur(s)`);
    setText(
        "statsNotice",
        stats.available ? "" : "CPU/RAM indisponibles (script hyperflo-docker-stats non autorisé)"
    );
}

async function loadContainers() {
    try {
        const data = await apiJson("/api/docker/containers", POLL);
        containers = data.containers;
        minecraft = data.minecraft || minecraft;
        renderContainers();
    } catch (error) {
        setText("dockerSummary", "Erreur : " + error.message);
    }
}

async function loadStats() {
    try {
        stats = await apiJson("/api/docker/stats", POLL);
        renderContainers();
    } catch {
        stats = { available: false, stats: {} };
    }
}


/* =========================================================
   Actions
========================================================= */

async function dockerAction(name, action) {
    const message = document.getElementById("dockerMessage");

    const isMinecraft = name === minecraft.container;
    const target = isMinecraft ? `${name} et Playit` : `« ${name} »`;

    if (action !== "start" && !confirm(`Voulez-vous vraiment ${ACTION_LABELS[action]} ${target} ?`)) {
        return;
    }

    pendingContainer = name;
    renderContainers();
    message.textContent = isMinecraft && action !== "start"
        ? `${ACTION_LABELS[action]} ${target}... (sauvegarde du monde, jusqu'à 90 s)`
        : `${ACTION_LABELS[action]} ${target}...`;

    try {
        await apiJson(`/api/docker/${encodeURIComponent(name)}/${action}`, {
            method: "POST",
            headers: { "X-Hyperflo-Action": "1" },
        });
        message.textContent = `✓ ${target} : ${ACTION_LABELS[action]} effectué`;
    } catch (error) {
        message.textContent = `✗ ${name} : ${error.message}`;
    } finally {
        pendingContainer = null;
        await loadContainers();
        loadStats();
        if (selectedContainer === name) {
            refreshDetails();
        }
    }
}


/* =========================================================
   Details et logs
========================================================= */

function formatDockerDate(value) {
    // Docker renvoie 0001-01-01T00:00:00Z pour "jamais".
    if (!value || value.startsWith("0001-")) {
        return "-";
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString("fr-FR");
}

function fillList(id, items) {
    const list = document.getElementById(id);
    list.replaceChildren();
    if (!items.length) {
        list.appendChild(element("li", "small", "Aucun"));
        return;
    }
    for (const item of items) {
        list.appendChild(element("li", "", item));
    }
}

async function openDetails(name) {
    selectedContainer = name;
    const panel = document.getElementById("dockerDetails");
    panel.classList.remove("hidden");
    setText("detailsName", name);
    setText("dockerLogs", "Chargement...");
    await refreshDetails();
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeDetails() {
    selectedContainer = null;
    document.getElementById("dockerDetails").classList.add("hidden");
}

async function refreshDetails() {
    if (!selectedContainer) {
        return;
    }
    const name = selectedContainer;
    const encoded = encodeURIComponent(name);
    const lines = document.getElementById("logLines").value;
    const logs = document.getElementById("dockerLogs");

    try {
        const data = await apiJson(`/api/docker/${encoded}/details`);
        const state = data.state || {};
        const containerStats = data.stats || {};

        setText("detailsName", data.name || name);
        setText("detailsImage", data.image || "-");
        setText("detailsState", state.status || "-");
        setText("detailsStarted", formatDockerDate(state.started_at));
        setText("detailsRestartPolicy", data.restart_policy || "aucune");
        setText("detailsRestarts", String(data.restart_count ?? 0));
        setText("detailsCpu", containerStats.CPUPerc || "-");
        setText("detailsRam", containerStats.MemUsage || "-");
        setText("detailsNetwork", containerStats.NetIO || "-");
        setText("detailsPids", containerStats.PIDs || "-");

        fillList(
            "detailsNetworks",
            Object.entries(data.networks || {}).map(([network, info]) => `${network} : ${info.ip || "pas d'IP"}`)
        );
        fillList(
            "detailsMounts",
            (data.mounts || []).map(mount => `${mount.type || "?"} → ${mount.destination || "?"}`)
        );
    } catch (error) {
        setText("detailsState", "Erreur : " + error.message);
    }

    try {
        const data = await apiJson(`/api/docker/${encoded}/logs?lines=${encodeURIComponent(lines)}`);
        if (selectedContainer !== name) {
            return;
        }
        const atBottom = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 40;
        logs.textContent = data.logs || "Aucun log.";
        if (atBottom || logs.dataset.container !== name) {
            logs.scrollTop = logs.scrollHeight;
        }
        logs.dataset.container = name;
    } catch (error) {
        logs.textContent = "Erreur : " + error.message;
    }
}


/* =========================================================
   Demarrage
========================================================= */

document.getElementById("closeDetailsButton").addEventListener("click", closeDetails);
document.getElementById("refreshDetailsButton").addEventListener("click", refreshDetails);
document.getElementById("logLines").addEventListener("change", refreshDetails);

async function refreshLoop() {
    await loadContainers();
    loadStats();
    setTimeout(refreshLoop, REFRESH_MS);
}

refreshLoop();
