async function dockerAction(container, action) {
    const message = document.getElementById("dockerMessage");

    if (action === "stop" || action === "restart") {
        if (!confirm(`Confirmer ${action} pour ${container} ?`)) {
            return;
        }
    }

    message.textContent = `${action} ${container}...`;

    try {
        const response = await fetch(`/api/docker/${encodeURIComponent(container)}/${action}`, {
            method: "POST",
            headers: {
                "X-Hyperflo-Action": "1"
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Erreur Docker");
        }

        message.textContent = `✓ ${container} : ${action}`;
        await loadDocker();
    } catch (error) {
        message.textContent = "Erreur : " + error.message;
    }
}

async function loadDocker() {
    const response = await fetch("/api/status", {
        // Rafraichissement automatique: ne prolonge pas la session.
        headers: { "X-Hyperflo-Poll": "1" }
    });
    const data = await response.json();

    const body = document.getElementById("dockerBody");
    body.replaceChildren();

    for (const container of data.docker.containers) {
        const row = document.createElement("tr");

        const name = document.createElement("td");
        name.textContent = container.Names;

        const image = document.createElement("td");
        image.textContent = container.Image;

        const state = document.createElement("td");
        state.textContent = container.State;
        state.className = container.State === "running" ? "running" : "stopped";

        const status = document.createElement("td");
        status.textContent = container.Status;

        const actions = document.createElement("td");

        const start = document.createElement("button");
        start.textContent = "▶ Start";
        start.disabled = container.State === "running";
        start.onclick = () => dockerAction(container.Names, "start");

        const stop = document.createElement("button");
        stop.textContent = "■ Stop";
        stop.disabled = container.State !== "running";
        stop.onclick = () => dockerAction(container.Names, "stop");

        const restart = document.createElement("button");
        restart.textContent = "↻ Restart";
        restart.disabled = container.State !== "running";
        restart.onclick = () => dockerAction(container.Names, "restart");

        actions.append(start, stop, restart);
        row.append(name, image, state, status, actions);
        body.appendChild(row);
    }
}

loadDocker();
setInterval(loadDocker, 5000);
