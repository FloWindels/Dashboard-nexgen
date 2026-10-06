"use strict";

/*
 * Charge avant les scripts de chaque page authentifiee.
 * - Ajoute le jeton CSRF aux requetes qui modifient quelque chose.
 * - Renvoie vers /login quand la session a expire ou a ete revoquee.
 * - Ajoute un lien de deconnexion dans la navigation.
 */

(() => {

    const CSRF_COOKIE = "__Host-hyperflo_csrf";
    const CSRF_HEADER = "X-Hyperflo-CSRF";
    const SAFE_METHODS = ["GET", "HEAD", "OPTIONS"];

    function readCookie(name) {
        const prefix = name + "=";
        for (const part of document.cookie.split(";")) {
            const cookie = part.trim();
            if (cookie.startsWith(prefix)) {
                return decodeURIComponent(cookie.slice(prefix.length));
            }
        }
        return "";
    }

    const originalFetch = window.fetch.bind(window);

    window.fetch = async (input, init = {}) => {
        const isRequest = input instanceof Request;
        const url = new URL(isRequest ? input.url : String(input), window.location.href);
        const sameOrigin = url.origin === window.location.origin;
        const method = String(init.method || (isRequest ? input.method : "GET")).toUpperCase();

        if (sameOrigin && !SAFE_METHODS.includes(method)) {
            const headers = new Headers(init.headers || (isRequest ? input.headers : undefined));
            const token = readCookie(CSRF_COOKIE);
            if (token) {
                headers.set(CSRF_HEADER, token);
            }
            init = { ...init, headers };
        }

        const response = await originalFetch(input, init);

        if (
            sameOrigin
            && response.status === 401
            && url.pathname.startsWith("/api/")
            && url.pathname !== "/api/auth/login"
        ) {
            window.location.replace("/login");
        }

        return response;
    };

    async function logout(event) {
        event.preventDefault();
        try {
            await window.fetch("/api/auth/logout", { method: "POST" });
        } finally {
            window.location.replace("/login");
        }
    }

    function addLogoutLink() {
        const nav = document.querySelector("nav.sidebar, nav.main-sidebar");
        if (!nav || nav.querySelector(".nav-logout")) {
            return;
        }
        const link = document.createElement("a");
        link.href = "/login";
        link.className = "nav-link nav-logout";
        link.textContent = "🚪 Déconnexion";
        link.addEventListener("click", logout);
        nav.appendChild(link);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", addLogoutLink);
    } else {
        addLogoutLink();
    }

})();
