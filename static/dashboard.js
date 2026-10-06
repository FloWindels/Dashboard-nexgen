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

function renderDocker(data) {
    const summary = document.getElementById("dockerSummary");
    const list = document.getElementById("dockerList");
    list.replaceChildren();

    if (!data.docker.available) {
        summary.textContent = "Docker indisponible";
        return;
    }

    const containers = [...data.docker.containers]
        .sort((a, b) => String(a.Names).localeCompare(String(b.Names)));
    const running = containers.filter(container => container.State === "running").length;
    summary.textContent = `${running} en cours sur ${containers.length} conteneur(s)`;

    for (const container of containers) {
        const isRunning = container.State === "running";
        const item = Hyperflo.element("span", isRunning ? "badge ok" : "badge bad");
        item.textContent = `${isRunning ? "●" : "○"} ${container.Names}`;
        item.title = container.Status || "";
        list.appendChild(item);
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

        renderDocker(data);
    } catch (error) {
        console.error("Hyperflo API error:", error);
        connection.textContent = "● Erreur : " + error.message;
        connection.className = "offline";
    }
}

async function refreshLoop() {
    await refresh();
    setTimeout(refreshLoop, 5000);
}

refreshLoop();
