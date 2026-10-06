"use strict";

const { formatBytes, formatDuration } = Hyperflo;

function setText(id, value) {
    document.getElementById(id).textContent = value;
}

// Barre de progression; orange au-dela de 75 %, rouge au-dela de 90 %.
function setBar(id, percent) {
    const bar = document.getElementById(id);
    const value = Math.min(100, Math.max(0, Number(percent) || 0));
    bar.style.width = value + "%";
    bar.classList.toggle("warn", value >= 75 && value < 90);
    bar.classList.toggle("crit", value >= 90);
}

function formatRate(bytesPerSecond) {
    return formatBytes(bytesPerSecond) + "/s";
}

function renderCpu(data) {
    const cpu = data.cpu;
    setText("cpu", cpu.usage.toFixed(1) + " %");
    setBar("cpuBar", cpu.usage);
    setText("cpuDetails", `${cpu.cores} cœurs / ${cpu.threads} threads`);
    setText("cpuModel", cpu.model || "");

    setText(
        "cpuTemp",
        cpu.temperature !== null ? cpu.temperature.toFixed(0) + " °C" : "N/A"
    );

    const [load1, load5, load15] = cpu.load;
    setText("load", `${load1.toFixed(2)} · ${load5.toFixed(2)} · ${load15.toFixed(2)}`);
    // 100 % = tous les threads occupes en moyenne sur une minute.
    setBar("loadBar", (load1 / Math.max(1, cpu.threads)) * 100);
    setText("loadDetails", `Moyenne sur 1 / 5 / 15 min · ${cpu.threads} threads`);
}

function renderMemory(data) {
    const memory = data.memory;
    setText("ram", memory.percent.toFixed(1) + " %");
    setBar("ramBar", memory.percent);
    setText("ramDetails", `${formatBytes(memory.used)} utilisés / ${formatBytes(memory.total)}`);
    setText("ramAvailable", `${formatBytes(memory.available)} disponibles`);
    setText(
        "swapDetails",
        memory.swap_total
            ? `Swap : ${formatBytes(memory.swap_used)} / ${formatBytes(memory.swap_total)}`
            : "Pas de swap"
    );
}

function renderGpu(data) {
    const gpu = data.gpu;

    if (!gpu.available) {
        setText("gpu", "N/A");
        setBar("gpuBar", 0);
        setText("gpuDetails", "GPU indisponible");
        setText("gpuName", "");
        setText("vram", "N/A");
        setBar("vramBar", 0);
        setText("vramDetails", "");
        return;
    }

    setText("gpu", gpu.utilization.toFixed(0) + " %");
    setBar("gpuBar", gpu.utilization);
    setText("gpuDetails", `${gpu.temperature.toFixed(0)} °C`);
    setText("gpuName", gpu.name);

    const vramPercent = gpu.memory_total ? (gpu.memory_used / gpu.memory_total) * 100 : 0;
    setText("vram", `${gpu.memory_used.toFixed(0)} / ${gpu.memory_total.toFixed(0)} Mo`);
    setBar("vramBar", vramPercent);
    setText("vramDetails", `${vramPercent.toFixed(1)} % utilisés`);
}

function renderNetwork(data) {
    const network = data.network;
    setText("networkRx", formatRate(network.rx_rate));
    setText("networkTx", formatRate(network.tx_rate));
    setText(
        "networkTotals",
        `Depuis le démarrage : ↓ ${formatBytes(network.received)} · ↑ ${formatBytes(network.sent)}`
    );

    const body = document.getElementById("interfacesBody");
    body.replaceChildren();

    for (const item of network.interfaces) {
        const row = document.createElement("tr");
        row.appendChild(Hyperflo.element("td", "", item.name));

        const state = Hyperflo.element("td");
        state.appendChild(
            Hyperflo.element("span", item.up ? "badge ok" : "badge bad", item.up ? "UP" : "DOWN")
        );
        row.appendChild(state);

        row.appendChild(Hyperflo.element("td", "", item.ipv4.join(", ") || "-"));
        row.appendChild(Hyperflo.element("td", "", item.speed ? `${item.speed} Mb/s` : "-"));
        body.appendChild(row);
    }
}

function renderSystem(data) {
    setText("hostname", data.hostname);
    setText("systemInfo", [data.system.os, data.system.kernel].filter(Boolean).join(" · "));
    setText("uptime", formatDuration(data.uptime));
    setText("osName", data.system.os || "");
    setText("kernel", data.system.kernel ? `Kernel ${data.system.kernel}` : "");
}

function renderDisks(data) {
    const disks = document.getElementById("disks");
    disks.replaceChildren();

    for (const disk of data.disks) {
        const item = Hyperflo.element("div", "disk");
        item.appendChild(Hyperflo.element("strong", "", disk.path));
        item.appendChild(
            Hyperflo.element(
                "div",
                "small",
                `${formatBytes(disk.used)} utilisés / ${formatBytes(disk.total)} · `
                + `${formatBytes(disk.free)} libres · ${disk.percent.toFixed(1)} %`
            )
        );

        const bar = Hyperflo.element("div", "bar");
        const value = document.createElement("div");
        value.id = `disk-${disks.children.length}`;
        bar.appendChild(value);
        item.appendChild(bar);
        disks.appendChild(item);
        setBar(value.id, disk.percent);
    }
}

async function refresh() {
    const connection = document.getElementById("connection");

    try {
        const response = await fetch("/api/status", {
            cache: "no-store",
            credentials: "include",
            headers: {
                Accept: "application/json",
                // Rafraichissement automatique: ne prolonge pas la session.
                "X-Hyperflo-Poll": "1"
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        connection.textContent = "● En ligne";
        connection.className = "online";

        renderSystem(data);
        renderCpu(data);
        renderMemory(data);
        renderGpu(data);
        renderNetwork(data);
        renderDisks(data);

        const body = document.getElementById("dockerBody");
        body.replaceChildren();

        if (data.docker.available) {
            for (const container of data.docker.containers) {
                const row = document.createElement("tr");

                const name = document.createElement("td");
                name.textContent = container.Names || "-";

                const image = document.createElement("td");
                image.textContent = container.Image || "-";

                const state = document.createElement("td");
                state.textContent = container.State || "-";
                state.className =
                    container.State === "running" ? "status-running" : "status-stopped";

                const status = document.createElement("td");
                status.textContent = container.Status || "-";

                const actions = document.createElement("td");
                actions.className = "docker-actions";

                const startButton = document.createElement("button");
                startButton.textContent = "▶ Start";
                startButton.className = "docker-btn";
                startButton.disabled = container.State === "running";
                startButton.onclick = () => {
                    dockerAction(container.Names, "start");
                };

                const stopButton = document.createElement("button");
                stopButton.textContent = "■ Stop";
                stopButton.className = "docker-btn danger";
                stopButton.disabled = container.State !== "running";
                stopButton.onclick = () => {
                    dockerAction(container.Names, "stop");
                };

                const restartButton = document.createElement("button");
                restartButton.textContent = "↻ Restart";
                restartButton.className = "docker-btn restart";
                restartButton.disabled = container.State !== "running";
                restartButton.onclick = () => {
                    dockerAction(container.Names, "restart");
                };

                const detailsButton = document.createElement("button");
                detailsButton.textContent = "📊 Details";
                detailsButton.className = "docker-btn";
                detailsButton.onclick = () => {
                    openDockerDetails(container.Names);
                };

                actions.append(detailsButton, startButton, stopButton, restartButton);
                row.append(name, image, state, status, actions);
                body.appendChild(row);
            }
        }
    } catch (error) {
        console.error("Hyperflo API error:", error);
        connection.textContent = "● Erreur : " + error.message;
        connection.className = "offline";
    }
}

async function dockerAction(container, action) {
    const message = document.getElementById("dockerMessage");
    const labels = {
        start: "démarrer",
        stop: "arrêter",
        restart: "redémarrer"
    };

    const dangerous = action === "stop" || action === "restart";

    if (dangerous) {
        const confirmed = confirm(
            `Voulez-vous vraiment ${labels[action]} le conteneur "${container}" ?`
        );

        if (!confirmed) {
            return;
        }
    }

    message.textContent = `${labels[action]} ${container}...`;

    try {
        const response = await fetch(`/api/docker/${encodeURIComponent(container)}/${action}`, {
            method: "POST",
            headers: {
                "X-Hyperflo-Action": "1"
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Action Docker impossible");
        }

        message.textContent = `✓ ${container} : action ${action} effectuée`;
        await refresh();
    } catch (error) {
        message.textContent = `✗ Erreur : ${error.message}`;
    }
}

let selectedContainer = null;

async function openDockerDetails(container) {
    selectedContainer = container;
    document.getElementById("dockerDetails").classList.remove("hidden");
    await refreshDockerDetails();
}

function closeDockerDetails() {
    selectedContainer = null;
    document.getElementById("dockerDetails").classList.add("hidden");
}

async function refreshDockerDetails() {
    if (!selectedContainer) {
        return;
    }

    const logs = document.getElementById("dockerLogs");

    try {
        const detailsResponse = await fetch(
            `/api/docker/${encodeURIComponent(selectedContainer)}/details`
        );

        if (!detailsResponse.ok) {
            throw new Error("Impossible de charger les détails");
        }

        const data = await detailsResponse.json();

        setText("detailsName", data.name);
        setText("detailsImage", data.image || "-");
        setText("detailsState", data.state.status || "-");
        setText("detailsRestarts", String(data.restart_count ?? 0));

        const stats = data.stats || {};
        setText("detailsCpu", stats.CPUPerc || "0%");
        setText("detailsRam", stats.MemUsage || "-");
        setText("detailsNetwork", stats.NetIO || "-");
        setText("detailsPids", stats.PIDs || "-");

        const logsResponse = await fetch(
            `/api/docker/${encodeURIComponent(selectedContainer)}/logs?lines=200`
        );

        if (!logsResponse.ok) {
            throw new Error("Impossible de charger les logs");
        }

        const logsData = await logsResponse.json();
        logs.textContent = logsData.logs || "Aucun log.";
    } catch (error) {
        logs.textContent = "Erreur : " + error.message;
    }
}

async function refreshLoop() {
    await refresh();
    setTimeout(refreshLoop, 5000);
}

document
    .getElementById("closeDockerDetailsButton")
    .addEventListener("click", closeDockerDetails);

document
    .getElementById("refreshDockerDetailsButton")
    .addEventListener("click", refreshDockerDetails);

refreshLoop();
