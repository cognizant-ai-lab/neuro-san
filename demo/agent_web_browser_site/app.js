/* Agent Web Browser — UI driver.
 *
 * Imports the runtime bundle (neuro-san-lite). Listens to its event stream
 * and renders the chat, the live agent-graph, and the per-origin network
 * trace. No URL bar — visiting an origin IS picking that origin's network,
 * just like the WWW. To visit a different origin, navigate your real browser
 * there.
 */

import { runAgentTurn } from "./neuro_san_lite.js";

// --- DOM ---
const $brandLogo = document.getElementById("brand-logo");
const $brandName = document.getElementById("brand-name");
const $brandTagline = document.getElementById("brand-tagline");
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
const $agentGraph = document.getElementById("agent-graph");
const $banner = document.getElementById("banner-status");

// --- Bootstrap data injected by LandingHandler ---
const BOOTSTRAP = window.AGENT_WEB_BOOTSTRAP ?? null;

// --- localStorage keys ---
const LS = {
    anthropicKey: "agentweb.anthropic_key",
    openaiKey:    "agentweb.openai_key",
    slyData:      "agentweb.sly_data",
};

function loadSettings() {
    $anthropicKey.value = localStorage.getItem(LS.anthropicKey) || "";
    $openaiKey.value    = localStorage.getItem(LS.openaiKey)    || "";
    $slyDataInput.value = localStorage.getItem(LS.slyData)      || "";
}

function saveSettings() {
    localStorage.setItem(LS.anthropicKey, $anthropicKey.value.trim());
    localStorage.setItem(LS.openaiKey,    $openaiKey.value.trim());
    localStorage.setItem(LS.slyData,      $slyDataInput.value.trim());
}

// --- Branding ---
function applyBranding() {
    const b = (BOOTSTRAP && BOOTSTRAP.branding) || {};
    if (b.name) {
        $brandName.textContent = b.name;
        document.title = b.name;
    }
    if (b.logo) {
        $brandLogo.textContent = b.logo;
    }
    if (b.tagline) {
        $brandTagline.textContent = b.tagline;
    }
}

// --- Chat rendering ---
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

function clearChat() {
    $chatLog.innerHTML = "";
}

function clearTrace() {
    $traceLog.innerHTML = "";
}

// --- Network trace panel ---
function appendTrace(entry) {
    const li = document.createElement("li");
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

// --- Agent graph ---
//
// The bootstrap's networks[0].tools is a pre-classified node list provided by
// the LandingHandler:
//   [
//     { name, kind: "front_man", tools: [child1, child2, ...], description },
//     { name, kind: "cross_origin" | "client_side" | "coded_tool" | ..., url? }
//   ]
//
// We render the front-man as a parent box with its direct children below.
// Each node has a `state` of idle | active | done; events transition them.

let GRAPH_NODES = [];      // array of node objects
let GRAPH_NETWORK = null;   // network the graph is currently rendering
const $graphRows = new Map();   // node.name -> li element

function buildGraph(network) {
    $agentGraph.innerHTML = "";
    $graphRows.clear();
    GRAPH_NETWORK = network ?? null;
    const src = network
        || (BOOTSTRAP && BOOTSTRAP.networks && BOOTSTRAP.networks[0])
        || null;
    if (!src || !Array.isArray(src.tools) || src.tools.length === 0) {
        $agentGraph.innerHTML = "<div class=\"muted graph-empty\">(no graph)</div>";
        GRAPH_NODES = [];
        return null;
    }
    GRAPH_NODES = src.tools.map((t) => ({ ...t, state: "idle" }));

    // Front-man at the top, children below.
    const frontMan = GRAPH_NODES.find((n) => n.kind === "front_man");
    const children = GRAPH_NODES.filter((n) => n.kind !== "front_man");

    const fragment = document.createDocumentFragment();
    if (frontMan) {
        fragment.appendChild(renderNode(frontMan, /*isChild=*/ false));
        if (children.length > 0) {
            const stem = document.createElement("div");
            stem.className = "graph-stem";
            fragment.appendChild(stem);
        }
    }
    const childrenWrap = document.createElement("div");
    childrenWrap.className = "graph-children";
    for (const child of children) {
        childrenWrap.appendChild(renderNode(child, /*isChild=*/ true));
    }
    fragment.appendChild(childrenWrap);
    $agentGraph.appendChild(fragment);
    return frontMan;
}

function renderNode(node, isChild) {
    const li = document.createElement("div");
    li.className = `graph-node state-idle kind-${node.kind} ${isChild ? "is-child" : "is-front"}`;
    li.dataset.name = node.name;

    const badge = document.createElement("span");
    badge.className = "kind-badge";
    badge.textContent = kindLabel(node.kind);
    li.appendChild(badge);

    const name = document.createElement("div");
    name.className = "node-name";
    name.textContent = node.name;
    li.appendChild(name);

    if (node.url) {
        const url = document.createElement("div");
        url.className = "node-url";
        try {
            const u = new URL(node.url);
            url.textContent = u.host;
        } catch {
            url.textContent = node.url;
        }
        li.appendChild(url);
    }

    if (node.description) {
        const desc = document.createElement("div");
        desc.className = "node-desc";
        desc.textContent = node.description.length > 80
            ? node.description.slice(0, 77) + "…"
            : node.description;
        li.appendChild(desc);
    }

    $graphRows.set(node.name, li);
    return li;
}

function kindLabel(kind) {
    switch (kind) {
        case "front_man":     return "agent";
        case "cross_origin":  return "cross-origin";
        case "client_side":   return "client-side";
        case "coded_tool":    return "coded tool";
        case "internal_agent": return "sub-agent";
        default:              return kind || "?";
    }
}

function setNodeState(name, state) {
    const node = GRAPH_NODES.find((n) => n.name === name);
    if (!node) return;
    node.state = state;
    const el = $graphRows.get(name);
    if (!el) return;
    el.classList.remove("state-idle", "state-active", "state-done");
    el.classList.add(`state-${state}`);
}

function resetGraphStates() {
    for (const node of GRAPH_NODES) setNodeState(node.name, "idle");
}

/** Find which graph node a network event refers to.
 *  Returns the node name, or null if we don't recognize the URL. */
function nodeForNetworkUrl(url) {
    if (!url) return null;
    // Direct URL match against children that have one.
    for (const node of GRAPH_NODES) {
        if (node.url && url.startsWith(node.url)) {
            return node.name;
        }
    }
    // The front-man's own streaming_chat call comes in via the URL the
    // browser hit. Match it against the network we're currently graphing.
    const src = GRAPH_NETWORK
        || (BOOTSTRAP && BOOTSTRAP.networks && BOOTSTRAP.networks[0])
        || null;
    if (!src || !src.url) return null;
    try {
        const parent = new URL(src.url);
        const u = new URL(url);
        if (parent.host === u.host && u.pathname.endsWith("/streaming_chat")) {
            const fm = GRAPH_NODES.find((n) => n.kind === "front_man");
            return fm ? fm.name : null;
        }
    } catch { /* ignore */ }
    return null;
}

// --- Networks list (left pane bottom section) ---
function renderNetworksList() {
    if (!BOOTSTRAP || !Array.isArray(BOOTSTRAP.networks)) {
        $networksList.innerHTML =
            "<li class=\"muted\">(open this page via http://&lt;origin&gt;/ to see its networks)</li>";
        return;
    }
    if (BOOTSTRAP.networks.length === 0) {
        $networksList.innerHTML =
            "<li class=\"muted\">(this origin has no published networks)</li>";
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
            for (const sib of $networksList.querySelectorAll(".network-link")) {
                sib.classList.remove("active");
            }
            a.classList.add("active");
            switchToNetwork(net);
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
    // Pre-mark the first as active since we auto-load it.
    const firstLink = $networksList.querySelector(".network-link");
    if (firstLink) firstLink.classList.add("active");
}

// --- Per-turn chat ---
let activeNetwork = null;
let currentChatContext = {};
let currentSlyData = {};
let inFlight = false;

function switchToNetwork(net) {
    activeNetwork = net;
    currentChatContext = {};
    currentSlyData = {};
    clearChat();
    clearTrace();
    // Rebuild the graph for the newly-selected network. Different networks
    // on the same origin have different shapes; the graph should reflect
    // whichever one we're about to chat with.
    buildGraph(net);
    $chatInput.disabled = false;
    $sendBtn.disabled = false;
    $chatInput.placeholder = "Send a message";
    if (Array.isArray(net.sample_queries) && net.sample_queries.length > 0) {
        $chatInput.value = net.sample_queries[0];
    } else {
        $chatInput.value = "";
    }
    $chatInput.focus();
    const haveKey = !!(localStorage.getItem(LS.anthropicKey) || localStorage.getItem(LS.openaiKey));
    setStatus(haveKey
        ? `Loaded ${net.name}. Edit the prompt and click Send.`
        : `Loaded ${net.name}. Open ⚙ first and set your LLM key.`,
        !haveKey);
}

async function runTurn(message) {
    if (inFlight || !activeNetwork) return;
    inFlight = true;
    $sendBtn.disabled = true;
    $chatInput.disabled = true;
    appendBubble("user", message);
    resetGraphStates();

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
        url: activeNetwork.url,
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
                // Drive the agent-graph animation from these events.
                const payload = event.payload || {};
                const target = nodeForNetworkUrl(payload.url);
                if (target) {
                    // Status null = call started. Status 200ish = finished.
                    if (payload.status === null || payload.status === undefined) {
                        setNodeState(target, "active");
                    } else if (payload.status >= 200 && payload.status < 300) {
                        setNodeState(target, "done");
                    } else {
                        setNodeState(target, "done");
                    }
                }
            } else if (event.kind === "done") {
                const result = event.payload;
                currentChatContext = result.chatContext || {};
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
$chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $chatInput.value.trim();
    if (!text) return;
    $chatInput.value = "";
    await runTurn(text);
});

// --- Init ---
loadSettings();
applyBranding();
renderNetworksList();

// Auto-load the first published network so the user doesn't have to click.
// switchToNetwork() also builds the graph for that network.
if (BOOTSTRAP && Array.isArray(BOOTSTRAP.networks) && BOOTSTRAP.networks.length > 0) {
    switchToNetwork(BOOTSTRAP.networks[0]);
} else {
    buildGraph(null);  // shows the empty-state placeholder
    setStatus("⚠ no published networks on this origin.", true);
}
