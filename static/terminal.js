"use strict";

/*
 * Terminal Web: xterm.js <-> WebSocket <-> SSH (voir terminal_api.py).
 * Trames binaires = donnees du terminal, trames texte = controle JSON.
 * Le mot de passe Linux n'est envoye qu'une fois, dans le message "login",
 * et n'est conserve nulle part cote navigateur.
 */

const loginCard = document.getElementById("loginCard");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const userInput = document.getElementById("linuxUser");
const passwordInput = document.getElementById("linuxPassword");
const connectButton = document.getElementById("connectButton");
const terminalWrap = document.getElementById("terminalWrap");
const statusText = document.getElementById("terminalStatus");
const disconnectButton = document.getElementById("disconnectButton");

const encoder = new TextEncoder();

let socket = null;
let connected = false;

const term = new Terminal({
    cursorBlink: true,
    fontFamily: '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", Menlo, Consolas, monospace',
    fontSize: 14,
    scrollback: 5000,
    theme: {
        background: "#05080d",
        foreground: "#e8edf5",
        cursor: "#58a6ff",
        selectionBackground: "#264f78",
    },
});
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
let opened = false;


/* =========================================================
   Affichage
========================================================= */

function setStatus(text) {
    statusText.textContent = text;
}

function showLogin(errorMessage) {
    connected = false;
    loginCard.classList.remove("hidden");
    disconnectButton.classList.add("hidden");
    connectButton.disabled = false;
    connectButton.textContent = "Se connecter";

    if (errorMessage) {
        loginError.textContent = errorMessage;
        loginError.classList.remove("hidden");
    }
    passwordInput.focus();
}

function showTerminal() {
    terminalWrap.classList.remove("hidden");
    if (!opened) {
        term.open(document.getElementById("terminal"));
        opened = true;
    }
    fitAddon.fit();
}

function sendControl(data) {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(data));
    }
}

function sendBytes(bytes) {
    if (connected && socket && socket.readyState === WebSocket.OPEN) {
        socket.send(bytes);
    }
}


/* =========================================================
   Connexion
========================================================= */

function connect(username, password) {
    loginError.classList.add("hidden");
    connectButton.disabled = true;
    connectButton.textContent = "Connexion...";
    setStatus(`Connexion de ${username}...`);

    showTerminal();
    term.reset();

    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${window.location.host}/api/terminal/ws`);
    socket.binaryType = "arraybuffer";

    // Oublie le mot de passe des qu'il est envoye.
    let pendingPassword = password;
    password = null;

    socket.addEventListener("open", () => {
        socket.send(JSON.stringify({
            type: "login",
            csrf: Hyperflo.csrfToken(),
            username,
            password: pendingPassword,
            cols: term.cols,
            rows: term.rows,
        }));
        pendingPassword = null;
    });

    socket.addEventListener("message", event => {
        if (event.data instanceof ArrayBuffer) {
            term.write(new Uint8Array(event.data));
            return;
        }

        let message;
        try {
            message = JSON.parse(event.data);
        } catch {
            return;
        }

        if (message.type === "status" && message.state === "connected") {
            connected = true;
            loginCard.classList.add("hidden");
            disconnectButton.classList.remove("hidden");
            setStatus(`Connecté en tant que ${message.user}`);
            fitAddon.fit();
            sendControl({ type: "resize", cols: term.cols, rows: term.rows });
            term.focus();
        } else if (message.type === "status" && message.state === "closed") {
            term.write(`\r\n\x1b[90m[Session fermée : ${message.reason}]\x1b[0m\r\n`);
        } else if (message.type === "error") {
            if (connected) {
                term.write(`\r\n\x1b[31m${message.message}\x1b[0m\r\n`);
            } else {
                loginError.textContent = message.message;
                loginError.classList.remove("hidden");
            }
        }
    });

    socket.addEventListener("close", () => {
        const wasConnected = connected;
        socket = null;
        setStatus("Non connecté");
        if (wasConnected) {
            showLogin("");
        } else {
            showLogin(loginError.classList.contains("hidden") ? "Connexion refusée." : "");
            terminalWrap.classList.add("hidden");
        }
    });
}

loginForm.addEventListener("submit", event => {
    event.preventDefault();
    const username = userInput.value.trim();
    // Le champ est vide aussitot: le mot de passe n'existe plus que dans
    // l'appel en cours.
    const password = passwordInput.value;
    passwordInput.value = "";
    if (!username || !password || socket) {
        return;
    }
    connect(username, password);
});

disconnectButton.addEventListener("click", () => {
    if (socket) {
        socket.close();
    }
});


/* =========================================================
   Clavier et taille
========================================================= */

term.onData(data => sendBytes(encoder.encode(data)));
// Certaines sequences (souris) arrivent en "binaire" (octets en chaine).
term.onBinary(data => sendBytes(Uint8Array.from(data, char => char.charCodeAt(0) & 255)));
term.onResize(size => sendControl({ type: "resize", cols: size.cols, rows: size.rows }));

window.addEventListener("resize", () => {
    if (opened && !terminalWrap.classList.contains("hidden")) {
        fitAddon.fit();
    }
});

userInput.focus();
