"use strict";


/* =========================================================
   Configuration
========================================================= */

const STORAGE_KEY =
    "hyperflo_ollama_conversations_v2";


let conversations = [];

let currentConversationId = null;

let sending = false;


/* =========================================================
   DOM
========================================================= */

const historyList =
    document.getElementById("historyList");

const messagesElement =
    document.getElementById("messages");

const chatTitle =
    document.getElementById("chatTitle");

const modelSelect =
    document.getElementById("modelSelect");

const webEnabled =
    document.getElementById("webEnabled");
webEnabled.checked = true;

const messageInput =
    document.getElementById("messageInput");

const sendButton =
    document.getElementById("sendButton");

const newChatButton =
    document.getElementById("newChatButton");

const connectionStatus =
    document.getElementById("connectionStatus");


/* =========================================================
   Stockage
========================================================= */

function loadStorage() {

    try {

        conversations =
            JSON.parse(
                localStorage.getItem(
                    STORAGE_KEY
                )
            ) || [];

    }
    catch {

        conversations = [];

    }

}


function saveStorage() {

    localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(
            conversations
        )
    );

}


function createId() {

    return (
        Date.now().toString(36)
        +
        "-"
        +
        Math.random()
            .toString(36)
            .slice(2)
    );

}


/* =========================================================
   Conversations
========================================================= */

function getConversation() {

    return conversations.find(
        conversation =>
            conversation.id ===
            currentConversationId
    );

}


function newConversation() {

    currentConversationId = null;

    chatTitle.textContent =
        "Nouvelle conversation";

    webEnabled.checked = true;

    renderWelcome();

    renderHistory();

    messageInput.focus();

}


function openConversation(id) {

    currentConversationId = id;

    const conversation =
        getConversation();

    if (!conversation) {
        return;
    }


    chatTitle.textContent =
        conversation.title;


    if (conversation.model) {

        modelSelect.value =
            conversation.model;

    }


    webEnabled.checked =
        Boolean(
            conversation.web
        );


    renderMessages();

    renderHistory();

}


function deleteConversation(
    id,
    event
) {

    event.stopPropagation();


    conversations =
        conversations.filter(
            conversation =>
                conversation.id !== id
        );


    saveStorage();


    if (
        currentConversationId === id
    ) {

        newConversation();

    }
    else {

        renderHistory();

    }

}


function renderHistory() {

    historyList.replaceChildren();


    const sorted =
        [...conversations]
            .sort(
                (a, b) =>
                    b.updatedAt -
                    a.updatedAt
            );


    for (
        const conversation
        of sorted
    ) {

        const item =
            document.createElement(
                "div"
            );


        item.className =
            "history-item";


        if (
            conversation.id ===
            currentConversationId
        ) {

            item.classList.add(
                "active"
            );

        }


        item.append(
            document.createTextNode(
                conversation.title
            )
        );


        item.onclick = () =>
            openConversation(
                conversation.id
            );


        const remove =
            document.createElement(
                "button"
            );


        remove.type = "button";

        remove.className =
            "history-delete";

        remove.textContent =
            "×";


        remove.onclick =
            event =>
                deleteConversation(
                    conversation.id,
                    event
                );


        item.appendChild(
            remove
        );


        historyList.appendChild(
            item
        );

    }

}


/* =========================================================
   Sécurité HTML
========================================================= */

function escapeHtml(value) {

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

}


function safeUrl(value) {

    try {

        const url =
            new URL(value);

        if (
            url.protocol !== "http:"
            &&
            url.protocol !== "https:"
        ) {

            return "#";

        }

        return url.toString();

    }
    catch {

        return "#";

    }

}


/* =========================================================
   Markdown simple
========================================================= */

function inlineMarkdown(text) {

    let value =
        escapeHtml(text);


    value =
        value.replace(
            /`([^`]+)`/g,
            "<code>$1</code>"
        );


    value =
        value.replace(
            /\*\*([^*]+)\*\*/g,
            "<strong>$1</strong>"
        );


    value =
        value.replace(
            /\*([^*]+)\*/g,
            "<em>$1</em>"
        );


    return value;

}


function markdown(text) {

    const lines =
        String(text)
            .replace(/\r/g, "")
            .split("\n");


    let html = "";

    let inCode = false;

    let codeBuffer = [];

    let inList = false;

    let listType = null;


    function closeList() {

        if (!inList) {
            return;
        }


        html +=
            listType === "ol"
                ? "</ol>"
                : "</ul>";


        inList = false;

        listType = null;

    }


    for (
        const line
        of lines
    ) {

        /* Bloc code */

        if (
            line.startsWith("```")
        ) {

            closeList();


            if (!inCode) {

                inCode = true;

                codeBuffer = [];

            }
            else {

                html +=
                    "<pre><code>"
                    +
                    escapeHtml(
                        codeBuffer.join(
                            "\n"
                        )
                    )
                    +
                    "</code></pre>";


                inCode = false;

            }


            continue;

        }


        if (inCode) {

            codeBuffer.push(
                line
            );

            continue;

        }


        /* Titres */

        const heading =
            line.match(
                /^(#{1,4})\s+(.*)$/
            );


        if (heading) {

            closeList();


            const level =
                heading[1].length;


            html +=
                `<h${level}>`
                +
                inlineMarkdown(
                    heading[2]
                )
                +
                `</h${level}>`;


            continue;

        }


        /* Liste */

        const unordered =
            line.match(
                /^\s*[-*]\s+(.*)$/
            );


        if (unordered) {

            if (
                !inList
                ||
                listType !== "ul"
            ) {

                closeList();

                html += "<ul>";

                inList = true;

                listType = "ul";

            }


            html +=
                "<li>"
                +
                inlineMarkdown(
                    unordered[1]
                )
                +
                "</li>";


            continue;

        }


        const ordered =
            line.match(
                /^\s*\d+\.\s+(.*)$/
            );


        if (ordered) {

            if (
                !inList
                ||
                listType !== "ol"
            ) {

                closeList();

                html += "<ol>";

                inList = true;

                listType = "ol";

            }


            html +=
                "<li>"
                +
                inlineMarkdown(
                    ordered[1]
                )
                +
                "</li>";


            continue;

        }


        closeList();


        /* Citation */

        if (
            line.startsWith("> ")
        ) {

            html +=
                "<blockquote>"
                +
                inlineMarkdown(
                    line.substring(2)
                )
                +
                "</blockquote>";


            continue;

        }


        /* Ligne vide */

        if (
            line.trim() === ""
        ) {

            html += "<br>";

        }
        else {

            html +=
                "<p>"
                +
                inlineMarkdown(
                    line
                )
                +
                "</p>";

        }

    }


    closeList();


    if (inCode) {

        html +=
            "<pre><code>"
            +
            escapeHtml(
                codeBuffer.join(
                    "\n"
                )
            )
            +
            "</code></pre>";

    }


    return html;

}


/* =========================================================
   Sources Web
========================================================= */

function renderSources(
    sources
) {

    if (
        !Array.isArray(
            sources
        )
        ||
        sources.length === 0
    ) {

        return "";

    }


    const validSources =
        sources.filter(
            source =>
                source
                &&
                source.url
        );


    if (
        validSources.length === 0
    ) {

        return "";

    }


    const items =
        validSources.map(
            source => {

                const url =
                    safeUrl(
                        source.url
                    );


                const title =
                    source.title
                    ||
                    source.url;


                return `
                    <li>
                        <a
                            href="${escapeHtml(url)}"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            ${escapeHtml(title)}
                        </a>
                    </li>
                `;

            }
        ).join("");


    return `
        <div class="web-sources">

            <div class="web-sources-title">
                🌐 Sources Web
            </div>

            <ul>
                ${items}
            </ul>

        </div>
    `;

}


/* =========================================================
   Affichage
========================================================= */

function renderWelcome() {

    messagesElement.innerHTML = `
        <div class="welcome">

            <h2>
                🤖 Hyperflo AI
            </h2>

            <p>
                Discute avec les modèles Ollama
                installés sur hyperflo-nextgen.
            </p>

            <p class="welcome-small">
                Active 🌐 Internet pour permettre
                une recherche Web.
            </p>

        </div>
    `;

}


function renderMessages() {

    const conversation =
        getConversation();


    if (
        !conversation
        ||
        conversation.messages.length === 0
    ) {

        renderWelcome();

        return;

    }


    messagesElement.replaceChildren();


    for (
        const message
        of conversation.messages
    ) {

        const wrapper =
            document.createElement(
                "div"
            );


        wrapper.className =
            "message "
            +
            (
                message.role === "user"
                    ? "user"
                    : "assistant"
            );


        const bubble =
            document.createElement(
                "div"
            );


        bubble.className =
            "bubble";


        if (
            message.role ===
            "assistant"
        ) {

            let html = "";


            if (
                message.thinking
                &&
                message.thinking.trim()
            ) {

                html += `
                    <details
                        class="thinking-box"
                    >

                        <summary
                            class="thinking-header"
                        >
                            🧠 Thinking
                        </summary>

                        <div
                            class="thinking-content"
                        >${escapeHtml(
                            message.thinking
                        )}</div>

                    </details>
                `;

            }


            html +=
                markdown(
                    message.content
                    || ""
                );


            html +=
                renderSources(
                    message.sources
                );


            bubble.innerHTML =
                html;

        }
        else {

            bubble.textContent =
                message.content;

        }


        wrapper.appendChild(
            bubble
        );


        messagesElement.appendChild(
            wrapper
        );

    }


    scrollToBottom();

}


function scrollToBottom() {

    messagesElement.scrollTop =
        messagesElement.scrollHeight;

}


/* =========================================================
   Modèles Ollama
========================================================= */

async function loadModels() {

    try {

        const response =
            await fetch(
                "/api/ollama/models"
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const data =
            await response.json();


        modelSelect.replaceChildren();


        for (
            const model
            of data.models
        ) {

            const option =
                document.createElement(
                    "option"
                );


            option.value =
                model;


            option.textContent =
                model;


            modelSelect.appendChild(
                option
            );

        }


        if (
            data.models.length === 0
        ) {

            const option =
                document.createElement(
                    "option"
                );


            option.textContent =
                "Aucun modèle installé";


            modelSelect.appendChild(
                option
            );

        }


        connectionStatus.textContent =
            "● Ollama en ligne";


        connectionStatus.className =
            "connection-status online";


        const conversation =
            getConversation();


        if (
            conversation
            &&
            conversation.model
        ) {

            modelSelect.value =
                conversation.model;

        }

    }

    catch (error) {

        modelSelect.innerHTML =
            "<option>Ollama indisponible</option>";


        connectionStatus.textContent =
            "● Ollama indisponible";


        connectionStatus.className =
            "connection-status error";

    }

}


/* =========================================================
   Envoi / Streaming
========================================================= */

async function sendMessage() {

    if (sending) {
        return;
    }


    const text =
        messageInput.value.trim();


    if (!text) {
        return;
    }


    const model =
        modelSelect.value;


    if (
        !model
        ||
        model ===
        "Aucun modèle installé"
        ||
        model ===
        "Ollama indisponible"
    ) {

        return;

    }


    /*
     * Nouvelle conversation
     */

    if (
        !currentConversationId
    ) {

        const title =
            text.length > 45
                ? text.slice(
                    0,
                    45
                ) + "…"
                : text;


        const conversation = {

            id:
                createId(),

            title,

            model,

            web:
                webEnabled.checked,

            messages: [],

            createdAt:
                Date.now(),

            updatedAt:
                Date.now()

        };


        conversations.push(
            conversation
        );


        currentConversationId =
            conversation.id;

    }


    const conversation =
        getConversation();


    conversation.model =
        model;


    conversation.web =
        webEnabled.checked;


    /*
     * Message utilisateur
     */

    conversation.messages.push({
        role: "user",
        content: text
    });


    conversation.updatedAt =
        Date.now();


    messageInput.value = "";

    autoResizeInput();


    /*
     * Message assistant temporaire
     */

    const assistantMessage = {

        role:
            "assistant",

        content:
            "",

        thinking:
            "",

        sources:
            []

    };


    conversation.messages.push(
        assistantMessage
    );


    saveStorage();

    renderHistory();

    renderMessages();


    chatTitle.textContent =
        conversation.title;


    sending = true;

    sendButton.disabled = true;


    /*
     * On crée un rendu live spécifique
     */

    const assistantWrappers =
        messagesElement.querySelectorAll(
            ".message.assistant"
        );


    const wrapper =
        assistantWrappers[
            assistantWrappers.length - 1
        ];


    const bubble =
        wrapper.querySelector(
            ".bubble"
        );


    bubble.innerHTML = `
        <details
            class="thinking-box"
            id="liveThinkingBox"
            hidden
            open
        >

            <summary
                class="thinking-header"
            >
                🧠 Thinking

                <span
                    id="thinkingIndicator"
                    class="thinking-indicator"
                >
                    ●
                </span>
            </summary>

            <div
                class="thinking-content"
                id="liveThinking"
            ></div>

        </details>


        <div
            id="liveAnswer"
        ></div>


        <div
            id="liveSources"
        ></div>
    `;


    const thinkingBox =
        document.getElementById(
            "liveThinkingBox"
        );


    const thinkingElement =
        document.getElementById(
            "liveThinking"
        );


    const answerElement =
        document.getElementById(
            "liveAnswer"
        );


    const sourcesElement =
        document.getElementById(
            "liveSources"
        );


    try {

        /*
         * On n'envoie pas le message assistant vide.
         *
         * On ne transmet à Ollama que role/content.
         */

        const requestMessages =
            conversation.messages
                .slice(
                    0,
                    -1
                )
                .map(
                    message => ({
                        role:
                            message.role,

                        content:
                            message.content
                    })
                );


        const response =
            await fetch(
                "/api/ollama/chat/stream",
                {

                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            model:
                                conversation.model,

                            messages:
                                requestMessages,

                            think:
                                true,

                            web:
                                conversation.web

                        })

                }
            );


        if (!response.ok) {

            const errorText =
                await response.text();


            throw new Error(
                errorText
                ||
                `HTTP ${response.status}`
            );

        }


        if (!response.body) {

            throw new Error(
                "Streaming non disponible"
            );

        }


        const reader =
            response.body.getReader();


        const decoder =
            new TextDecoder();


        let buffer = "";


        while (true) {

            const {
                value,
                done
            } =
                await reader.read();


            if (done) {
                break;
            }


            buffer +=
                decoder.decode(
                    value,
                    {
                        stream: true
                    }
                );


            let newlineIndex;


            while (
                (
                    newlineIndex =
                        buffer.indexOf(
                            "\n"
                        )
                ) !== -1
            ) {

                const line =
                    buffer
                        .slice(
                            0,
                            newlineIndex
                        )
                        .trim();


                buffer =
                    buffer.slice(
                        newlineIndex + 1
                    );


                if (!line) {
                    continue;
                }


                let chunk;


                try {

                    chunk =
                        JSON.parse(
                            line
                        );

                }
                catch {

                    continue;

                }


                /*
                 * Sources Web
                 */

                if (
                    chunk.type ===
                    "web_sources"
                ) {

                    assistantMessage.sources =
                        Array.isArray(
                            chunk.sources
                        )
                            ? chunk.sources
                            : [];


                    sourcesElement.innerHTML =
                        renderSources(
                            assistantMessage.sources
                        );


                    continue;

                }


                /*
                 * Erreur backend
                 */

                if (
                    chunk.error
                ) {

                    throw new Error(
                        chunk.error
                    );

                }


                /*
                 * Thinking
                 */

                const thinkingChunk =
                    chunk.message
                        ?.thinking
                    || "";


                if (
                    thinkingChunk
                ) {

                    assistantMessage.thinking +=
                        thinkingChunk;


                    thinkingBox.hidden =
                        false;


                    thinkingElement.textContent =
                        assistantMessage.thinking;


                    thinkingElement.scrollTop =
                        thinkingElement.scrollHeight;

                }


                /*
                 * Réponse finale
                 */

                const contentChunk =
                    chunk.message
                        ?.content
                    || "";


                if (
                    contentChunk
                ) {

                    assistantMessage.content +=
                        contentChunk;


                    answerElement.innerHTML =
                        markdown(
                            assistantMessage.content
                        );


                    scrollToBottom();

                }


                /*
                 * Fin
                 */

                if (
                    chunk.done
                ) {

                    const indicator =
                        document.getElementById(
                            "thinkingIndicator"
                        );


                    if (indicator) {

                        indicator.textContent =
                            "✓";


                        indicator.classList.remove(
                            "thinking-indicator"
                        );

                    }

                }

            }

        }


        /*
         * Traiter un dernier JSON sans newline
         */

        const remaining =
            buffer.trim();


        if (remaining) {

            try {

                const chunk =
                    JSON.parse(
                        remaining
                    );


                if (
                    chunk.message
                        ?.content
                ) {

                    assistantMessage.content +=
                        chunk.message.content;

                }


                if (
                    chunk.message
                        ?.thinking
                ) {

                    assistantMessage.thinking +=
                        chunk.message.thinking;

                }

            }
            catch {
                /* rien */
            }

        }


        conversation.updatedAt =
            Date.now();


        saveStorage();

    }

    catch (error) {

        assistantMessage.content =
            (
                assistantMessage.content
                    ? assistantMessage.content
                    + "\n\n"
                    : ""
            )
            +
            "**Erreur Ollama :** "
            +
            error.message;


        saveStorage();

    }

    finally {

        sending = false;

        sendButton.disabled = false;


        renderMessages();

        renderHistory();


        messageInput.focus();

    }

}


/* =========================================================
   Textarea
========================================================= */

function autoResizeInput() {

    messageInput.style.height =
        "auto";


    messageInput.style.height =
        Math.min(
            messageInput.scrollHeight,
            170
        )
        +
        "px";

}


/* =========================================================
   Événements
========================================================= */

messageInput.addEventListener(
    "keydown",
    event => {

        if (
            event.key === "Enter"
            &&
            !event.shiftKey
        ) {

            event.preventDefault();

            sendMessage();

        }

    }
);


messageInput.addEventListener(
    "input",
    autoResizeInput
);


sendButton.addEventListener(
    "click",
    sendMessage
);


newChatButton.addEventListener(
    "click",
    newConversation
);


modelSelect.addEventListener(
    "change",
    () => {

        const conversation =
            getConversation();


        if (
            conversation
        ) {

            conversation.model =
                modelSelect.value;


            conversation.updatedAt =
                Date.now();


            saveStorage();

        }

    }
);


webEnabled.addEventListener(
    "change",
    () => {

        const conversation =
            getConversation();


        if (
            conversation
        ) {

            conversation.web =
                webEnabled.checked;


            conversation.updatedAt =
                Date.now();


            saveStorage();

        }

    }
);


/* =========================================================
   Initialisation
========================================================= */

loadStorage();

renderHistory();

renderWelcome();

webEnabled.checked = true;

loadModels();

messageInput.focus();