/* Agent Web Browser — JS side.
 *
 * Imports the neuro_san_lite ES module bundle and wires it into the chat /
 * trace UI. No Pyodide, no python-in-the-browser. The runtime is a few KB
 * of TypeScript compiled to plain ES.
 *
 * The BYOK contract: the user pastes their LLM key into the settings dialog.
 * On each turn we thread it into `sly_data.llm_config` of the streaming_chat
 * request. The origin uses it without persisting (see neuro-san's
 * replace_any_required_api_keys).
 */

import { runAgentTurn } from "./neuro_san_lite.js";

// --- DOM handles ---
const $banner = document.getElementById("banner-status");
const $url = document.getElementById("url-input");
const $loadBtn = document.getElementById("load-btn");
const $settingsBtn = document.getElementById("settings-btn");
const $settingsModal = document.getElementById("settings-modal");
const $anthropicKey = document.getElementById("anthropic-key");
const $openaiKey = document.getElementById("openai-key");
const $slyDataInput = document.getElementById("sly-data-input");
const $chatLog = document.getElementById("chat-log");
const $chatForm = document.getElementById("chat-form");
const $chatInput = document.getElementById("chat-input");
const $sendBtn = document.getElementById("send-btn");
const $traceLog = document.getElementById("trace-log");
const $networksList = document.getElementById("networks-list");
const $originLabel = document.getElementById("origin-label");

// --- Bootstrap data injected by LandingHandler ---
// Shape: { origin: string, networks: [{name, description, url, sample_queries}] }
const BOOTSTRAP = window.AGENT_WEB_BOOTSTRAP ?? null;

// --- localStorage keys ---
const LS = {
    anthropicKey: "agentweb.anthropic_key",
    openaiKey:    "agentweb.openai_key",
    slyData:      "agentweb.sly_data",
    lastUrl:      "agentweb.last_url",
};

function loadSettings() {
    $anthropicKey.value = localStorage.getItem(LS.anthropicKey) || "";
    $openaiKey.value    = localStorage.getItem(LS.openaiKey)    || "";
    $slyDataInput.value = localStorage.getItem(LS.slyData)      || "";
    $url.value          = localStorage.getItem(LS.lastUrl)      || "";
}

function saveSettings() {
    localStorage.setItem(LS.anthropicKey, $anthropicKey.value.trim());
    localStorage.setItem(LS.openaiKey,    $openaiKey.value.trim());
    localStorage.setItem(LS.slyData,      $slyDataInput.value.trim());
}

function rememberUrl(u) {
    localStorage.setItem(LS.lastUrl, u);
}

// --- UI helpers ---
function appendBubble(kind, text) {
    const div = document.createElement("div");
    div.className = `bubble ${kind}`;
    div.textContent = text;
    $chatLog.appendChild(div);
    $chatLog.scrollTop = $chatLog.scrollHeight;
    return div;
}

function setStatus(text, isError) {
    $banner.textContent = text || "";
    $banner.classList.toggle("error", !!isError);
}

function appendTrace(entry) {
    // entry: {kind, method, url, status, ms?, via?}
    const li = document.createElement("li");
    // Server-reported (via) entries get a distinct CSS class so they read as
    // "this call happened, but our browser didn't make it — it was reported
    // to us by the origin we DID call."
    const cls = entry.via ? "trace-entry via" : "trace-entry";
    li.className = cls;
    const ts = new Date().toLocaleTimeString();
    const statusBadge = entry.status === null || entry.status === undefined
        ? "<span class=\"status\">…</span>"
        : `<span class="status ${entry.status >= 200 && entry.status < 300 ? "ok" : "err"}">${entry.status}${entry.ms ? `, ${entry.ms}ms` : ""}</span>`;
    let viaLabel = "";
    if (entry.via) {
        try {
            const u = new URL(entry.via);
            viaLabel = `<span class="via-label">via ${u.host}</span>`;
        } catch {
            viaLabel = `<span class="via-label">via ${entry.via}</span>`;
        }
    }
    li.innerHTML = `
        ${statusBadge}
        <div><span class="ts">${ts}</span> <span class="method">${entry.method}</span> <span class="url">${entry.url}</span></div>
        <div class="summary">${entry.kind || ""} ${viaLabel}</div>
    `;
    $traceLog.appendChild(li);
    $traceLog.scrollTop = $traceLog.scrollHeight;
    return li;
}

function clearChat() {
    $chatLog.innerHTML = "";
}

function clearTrace() {
    $traceLog.innerHTML = "";
}

// --- Per-turn chat ---
let currentChatContext = {};
let currentSlyData = {};
let inFlight = false;

function resetSession() {
    currentChatContext = {};
    currentSlyData = {};
}

async function runTurn(message) {
    if (inFlight) {
        return;  // single-flight: ignore submits during a turn
    }
    const url = $url.value.trim();
    if (!url) {
        appendBubble("error", "No agent network URL loaded.");
        return;
    }
    inFlight = true;
    $sendBtn.disabled = true;
    $chatInput.disabled = true;
    appendBubble("user", message);

    // Build sly_data from the user's settings + carried state.
    let extraSly = {};
    const raw = ($slyDataInput.value || localStorage.getItem(LS.slyData) || "").trim();
    if (raw) {
        try {
            extraSly = JSON.parse(raw);
            if (typeof extraSly !== "object" || extraSly === null) {
                throw new Error("must be an object");
            }
        } catch (err) {
            appendBubble("error", `sly_data JSON is invalid: ${err.message}`);
            inFlight = false;
            $sendBtn.disabled = false;
            $chatInput.disabled = false;
            return;
        }
    }
    const slyData = { ...currentSlyData, ...extraSly };

    const opts = {
        url,
        message,
        anthropicKey: (localStorage.getItem(LS.anthropicKey) || "").trim(),
        openaiKey:    (localStorage.getItem(LS.openaiKey)    || "").trim(),
        chatContext:  currentChatContext,
        slyData,
    };

    try {
        for await (const event of runAgentTurn(opts)) {
            if (event.kind === "agent") {
                appendBubble("agent", event.payload);
            } else if (event.kind === "thinking") {
                appendBubble("thinking", event.payload);
            } else if (event.kind === "error") {
                appendBubble("error", String(event.payload));
            } else if (event.kind === "network") {
                appendTrace(event.payload);
            } else if (event.kind === "done") {
                const result = event.payload;
                currentChatContext = result.chatContext || {};
                // Don't carry secret-looking keys back into the next turn's
                // visible sly_data state — they were sent for this turn only.
                currentSlyData = stripSecretKeys(result.slyData || {});
            }
        }
    } catch (err) {
        appendBubble("error", String(err.message || err));
        console.error("runTurn failed", err);
    } finally {
        inFlight = false;
        $sendBtn.disabled = false;
        $chatInput.disabled = false;
        $chatInput.focus();
    }
}

// Strip api_key-like keys from a sly_data dict before persisting it across
// turns. They get re-injected on the next request from localStorage anyway,
// and we don't want them lingering in JS memory longer than necessary.
function stripSecretKeys(obj) {
    const SECRET_RE = /(api_key|apikey|secret|token|password|credential|private_key)/i;
    function strip(v) {
        if (v === null || typeof v !== "object") return v;
        if (Array.isArray(v)) return v.map(strip);
        const out = {};
        for (const [k, val] of Object.entries(v)) {
            if (SECRET_RE.test(k)) continue;
            out[k] = strip(val);
        }
        return out;
    }
    return strip(obj);
}

// --- Event wiring ---
$settingsBtn.addEventListener("click", () => $settingsModal.showModal());
$settingsModal.addEventListener("close", () => {
    if ($settingsModal.returnValue === "save") {
        saveSettings();
        setStatus("settings saved");
    }
});

$loadBtn.addEventListener("click", triggerLoad);

$chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $chatInput.value.trim();
    if (!text) return;
    $chatInput.value = "";
    await runTurn(text);
});

// --- Networks panel (bootstrap-driven) ---
function renderNetworksList() {
    if (!BOOTSTRAP || !Array.isArray(BOOTSTRAP.networks)) {
        // Loaded as standalone (no LandingHandler injection); show a hint.
        $networksList.innerHTML =
            "<li class=\"muted\">(open this page via http://&lt;origin&gt;/ to see its networks)</li>";
        return;
    }
    if ($originLabel) {
        try {
            const u = new URL(BOOTSTRAP.origin);
            $originLabel.textContent = u.host;
        } catch {
            $originLabel.textContent = BOOTSTRAP.origin;
        }
    }
    if (BOOTSTRAP.networks.length === 0) {
        $networksList.innerHTML =
            "<li class=\"muted\">(this origin has no distributable networks)</li>";
        return;
    }
    $networksList.innerHTML = "";
    for (const net of BOOTSTRAP.networks) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#";
        a.className = "network-link";
        a.textContent = net.name;
        a.title = net.url;
        a.addEventListener("click", (e) => {
            e.preventDefault();
            $url.value = net.url;
            triggerLoad();
            // Highlight the active item.
            for (const sibling of $networksList.querySelectorAll(".network-link")) {
                sibling.classList.remove("active");
            }
            a.classList.add("active");
            // If the network metadata lists a sample query, preload it into
            // the chat input so the user can hit Enter and go.
            if (Array.isArray(net.sample_queries) && net.sample_queries.length > 0) {
                $chatInput.value = net.sample_queries[0];
            }
        });
        li.appendChild(a);
        if (net.description) {
            const desc = document.createElement("div");
            desc.className = "network-desc";
            desc.textContent = net.description;
            li.appendChild(desc);
        }
        $networksList.appendChild(li);
    }
}

function triggerLoad() {
    const url = $url.value.trim();
    if (!url) return;
    rememberUrl(url);
    clearChat();
    clearTrace();
    resetSession();
    setStatus(`loaded ${url}`);
    $chatInput.disabled = false;
    $sendBtn.disabled = false;
    $chatInput.placeholder = "Send a message";
    $chatInput.focus();
}

// --- Init ---
loadSettings();
renderNetworksList();
if (!localStorage.getItem(LS.anthropicKey) && !localStorage.getItem(LS.openaiKey)) {
    setStatus("⚠ no LLM key configured — open ⚙ first.", true);
}
