"use strict";

/*
 * Fonctions partagees par les pages authentifiees.
 * Chargé après security.js et avant le script de la page.
 */

const Hyperflo = (() => {

    const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];

    function formatBytes(value) {
        let number = Number(value) || 0;
        let index = 0;

        while (number >= 1024 && index < BYTE_UNITS.length - 1) {
            number /= 1024;
            index++;
        }

        return number.toFixed(index > 1 ? 1 : 0) + " " + BYTE_UNITS[index];
    }

    function formatDuration(totalSeconds) {
        const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);

        if (days) return `${days}j ${hours}h ${minutes}m`;
        if (hours) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    }

    function formatDate(timestamp) {
        return new Date(timestamp * 1000).toLocaleString("fr-FR");
    }

    // fetch + JSON. Leve une Error avec le message "detail" de l'API.
    async function apiJson(url, options) {
        const response = await fetch(url, options);
        let data = {};

        try {
            data = await response.json();
        } catch {
            // reponse vide ou non JSON
        }

        if (!response.ok) {
            const detail = typeof data.detail === "string" ? data.detail : "";
            throw new Error(detail || `HTTP ${response.status}`);
        }

        return data;
    }

    // Cree un element avec une classe et un texte (jamais de HTML).
    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined && text !== null) {
            node.textContent = String(text);
        }
        return node;
    }

    return {
        formatBytes,
        formatDuration,
        formatDate,
        apiJson,
        element,
    };

})();
