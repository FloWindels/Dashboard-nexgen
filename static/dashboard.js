function bytes(value) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let index = 0;

    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index++;
    }

    return value.toFixed(index > 1 ? 1 : 0) + " " + units[index];
}

function uptime(seconds) {
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (days > 0) {
        return `${days}j ${hours}h`;
    }

    return `${hours}h ${minutes}m`;
}

function setText(id, value) {
    document.getElementById(id).textContent = value;
}

function setBar(id, value) {
    document.getElementById(id).style.width =
        Math.min(100, Math.max(0, value)) + "%";
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

        const contentType = response.headers.get("content-type") || "";

        if (!contentType.includes("application/json")) {
            throw new Error("La réponse n'est pas du JSON : " + contentType);
        }

        const data = await response.json();

        connection.textContent = "● En ligne";
        connection.className = "online";

        setText("hostname", data.hostname);
        setText("cpu", data.cpu.usage.toFixed(1) + "%");
        setBar("cpuBar", data.cpu.usage);
        setText("cpuDetails", `${data.cpu.cores} cœurs / ${data.cpu.threads} threads`);

        setText("ram", data.memory.percent.toFixed(1) + "%");
        setBar("ramBar", data.memory.percent);
        setText("ramDetails", `${bytes(data.memory.used)} / ${bytes(data.memory.total)}`);

        setText(
            "cpuTemp",
            data.cpu.temperature !== null
                ? data.cpu.temperature + " °C"
                : "N/A"
        );

        setText("uptime", uptime(data.uptime));
        setText("networkRx", bytes(data.network.received));
        setText("networkTx", bytes(data.network.sent));

        if (data.gpu.available) {
            setText("gpu", data.gpu.utilization.toFixed(0) + "%");
            setText("gpuDetails", data.gpu.temperature + " °C");

            const vramPercent = (data.gpu.memory_used / data.gpu.memory_total) * 100;

            setText(
                "vram",
                data.gpu.memory_used.toFixed(0) +
                    " / " +
                    data.gpu.memory_total.toFixed(0) +
                    " MB"
            );

            setBar("vramBar", vramPercent);
            setText("gpuName", data.gpu.name);
        } else {
            setText("gpu", "N/A");
            setText("gpuDetails", "GPU indisponible");
            setText("vram", "N/A");
            setText("gpuName", "");
        }

        const disks = document.getElementById("disks");
        disks.replaceChildren();

        for (const disk of data.disks) {
            const container = document.createElement("div");
            container.style.marginBottom = "18px";

            const title = document.createElement("strong");
            title.textContent = disk.path;
            container.appendChild(title);

            const info = document.createElement("div");
            info.className = "small";
            info.textContent = `${bytes(disk.used)} / ${bytes(disk.total)} — ${disk.percent}%`;
            container.appendChild(info);

            const bar = document.createElement("div");
            bar.className = "bar";

            const value = document.createElement("div");
            value.style.width = disk.percent + "%";

            bar.appendChild(value);
            container.appendChild(bar);
            disks.appendChild(container);
        }

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
