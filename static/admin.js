async function loadAdminStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Erreur de chargement');
        }

        document.getElementById('hostname').textContent = data.hostname || 'Inconnu';
        document.getElementById('uptime').textContent = formatSeconds(data.uptime || 0);
        document.getElementById('cpu').textContent = `${(data.cpu?.usage ?? 0).toFixed(1)} %`;
        document.getElementById('memory').textContent = `${((data.memory?.used ?? 0) / 1024 / 1024 / 1024).toFixed(1)} Go`;
    } catch (error) {
        document.getElementById('adminStatus').textContent = 'Erreur : ' + error.message;
    }
}

function formatSeconds(totalSeconds) {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);

    if (days) return `${days}j ${hours}h ${minutes}m`;
    if (hours) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

loadAdminStatus();
