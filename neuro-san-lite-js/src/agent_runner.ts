// Port of neuro_san_client/agent_runner.py
// BYOK chat-loop driver. Streams events out as an async iterable so the UI
// can render incrementally.

import type {
    ChatEvent,
    Json,
    RunnerOptions,
    RunnerResult,
} from "./types.js";
import {
    extractWireConfigFromNotebook,
    getNetworkName,
    verifyWireConfig,
    WireConfigError,
} from "./wire_config.js";

/** Derive the /streaming_chat URL for a given /network URL and network name. */
export function deriveStreamingChatUrl(networkUrl: string, networkName: string): string {
    let parsed: URL;
    try {
        parsed = new URL(networkUrl);
    } catch {
        throw new Error(`networkUrl is not fully qualified: ${networkUrl}`);
    }
    if (!parsed.protocol || !parsed.host) {
        throw new Error(`networkUrl is not fully qualified: ${networkUrl}`);
    }
    return `${parsed.protocol}//${parsed.host}/api/v1/${networkName}/streaming_chat`;
}

/**
 * Build the streaming_chat request body, threading BYOK keys into
 * sly_data.llm_config. Caller-supplied keys take precedence over BYOK ones,
 * matching the Python behavior (setdefault).
 */
export function buildRequest(opts: RunnerOptions): Record<string, Json> {
    // Start with caller-supplied sly_data (don't mutate it).
    const slyData: Record<string, Json> = { ...(opts.slyData ?? {}) };

    // Merge BYOK keys into sly_data.llm_config without overriding caller's choices.
    const existingLlm = (slyData["llm_config"] as Record<string, Json> | undefined) ?? {};
    const llmKeys: Record<string, Json> = { ...existingLlm };

    if (opts.anthropicKey) {
        if (llmKeys["api_key"] === undefined) {
            llmKeys["api_key"] = opts.anthropicKey;
        }
        llmKeys["anthropic_api_key"] = opts.anthropicKey;
    }
    if (opts.openaiKey) {
        if (llmKeys["api_key"] === undefined) {
            llmKeys["api_key"] = opts.openaiKey;
        }
        llmKeys["openai_api_key"] = opts.openaiKey;
    }
    if (Object.keys(llmKeys).length > 0) {
        slyData["llm_config"] = llmKeys;
    }

    const request: Record<string, Json> = {
        user_message: { type: "HUMAN", text: opts.message },
        // MAXIMAL: pass intermediate AGENT messages too (default MINIMAL
        // drops them). We need them for the network_call events that
        // ExternalActivation embeds in the stream — without them, the
        // browser can't render cross-origin choreography in its trace panel.
        chat_filter: { chat_filter_type: "MAXIMAL" },
    };
    if (opts.chatContext && Object.keys(opts.chatContext).length > 0) {
        request["chat_context"] = opts.chatContext as Json;
    }
    if (Object.keys(slyData).length > 0) {
        request["sly_data"] = slyData;
    }
    return request;
}

/**
 * Drive one chat turn. Yields ChatEvent objects as the conversation streams.
 * The final event is always `{kind: "done", payload: RunnerResult}`.
 */
export async function* runAgentTurn(opts: RunnerOptions): AsyncGenerator<ChatEvent, void, void> {
    const fetchImpl = opts.fetchImpl ?? fetch;
    const result: RunnerResult = {
        chatContext: { ...(opts.chatContext ?? {}) },
        slyData: { ...(opts.slyData ?? {}) },
        answer: "",
    };

    // 1) Fetch notebook.
    yield {
        kind: "network",
        payload: { kind: "notebook", method: "GET", url: opts.url, status: null },
    };
    let response: Response;
    try {
        response = await fetchImpl(opts.url);
    } catch (exc) {
        yield { kind: "error", payload: `Notebook fetch failed: ${(exc as Error).message}` };
        yield { kind: "done", payload: result };
        return;
    }
    if (!response.ok) {
        yield {
            kind: "error",
            payload: `Notebook GET ${opts.url} returned HTTP ${response.status}`,
        };
        yield { kind: "done", payload: result };
        return;
    }
    yield {
        kind: "network",
        payload: {
            kind: "notebook",
            method: "GET",
            url: opts.url,
            status: response.status,
        },
    };
    let notebook: unknown;
    try {
        notebook = await response.json();
    } catch (exc) {
        yield { kind: "error", payload: `Notebook JSON parse failed: ${(exc as Error).message}` };
        yield { kind: "done", payload: result };
        return;
    }

    // 2) Extract + verify wire config.
    let wire;
    try {
        wire = extractWireConfigFromNotebook(notebook);
        verifyWireConfig(wire);
    } catch (exc) {
        const msg = exc instanceof WireConfigError
            ? `Wire config invalid: ${exc.message}`
            : `Wire config invalid: ${(exc as Error).message}`;
        yield { kind: "error", payload: msg };
        yield { kind: "done", payload: result };
        return;
    }

    // 3) Stream the chat against the origin.
    const networkName = getNetworkName(wire);
    const streamingUrl = deriveStreamingChatUrl(opts.url, networkName);
    const requestBody = buildRequest(opts);

    yield {
        kind: "network",
        payload: {
            kind: "streaming_chat",
            method: "POST",
            url: streamingUrl,
            status: null,
        },
    };

    let streamResp: Response;
    try {
        streamResp = await fetchImpl(streamingUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody),
        });
    } catch (exc) {
        yield { kind: "error", payload: `streaming_chat failed: ${(exc as Error).message}` };
        yield { kind: "done", payload: result };
        return;
    }
    if (!streamResp.ok) {
        const body = await streamResp.text();
        yield {
            kind: "error",
            payload: `streaming_chat HTTP ${streamResp.status}: ${body.slice(0, 300)}`,
        };
        yield { kind: "done", payload: result };
        return;
    }
    yield {
        kind: "network",
        payload: {
            kind: "streaming_chat",
            method: "POST",
            url: streamingUrl,
            status: streamResp.status,
        },
    };

    const compiledParts: string[] = [];
    for await (const line of streamLines(streamResp)) {
        if (!line) {
            continue;
        }
        let chunk: { response?: ChunkResponse };
        try {
            chunk = JSON.parse(line);
        } catch {
            continue;
        }
        const respObj = chunk?.response ?? {};
        const msgType = respObj.type;
        const text = respObj.text;
        const chatCtx = respObj.chat_context;
        const sly = respObj.sly_data;
        const structure = respObj.structure;
        if (chatCtx) {
            result.chatContext = chatCtx;
        }
        if (sly) {
            Object.assign(result.slyData, sly);
        }
        // Server-side cross-origin calls (ExternalActivation / RemoteToolActivation
        // upstream of us) embed a `network_call` field in the message's
        // structure. Surface those as network events so the trace panel can
        // render the choreography the origin executed on the caller's behalf.
        if (structure && typeof structure === "object" && structure.network_call) {
            const annotated = {
                ...structure.network_call,
                via: structure.network_call["via"] ?? opts.url,
            };
            yield { kind: "network", payload: annotated };
        }
        // AGENT_FRAMEWORK carries the front man's final user-facing answer;
        // AI is direct LLM output (usually filtered out by default chat_filter);
        // AGENT / AGENT_PROGRESS / AGENT_TOOL_RESULT are intermediate "thinking"
        // steps that we surface separately.
        const finalKinds = new Set(["AGENT_FRAMEWORK", "AI"]);
        const thinkingKinds = new Set(["AGENT", "AGENT_PROGRESS", "AGENT_TOOL_RESULT"]);
        if (typeof msgType === "string" && finalKinds.has(msgType) && typeof text === "string" && text) {
            compiledParts.push(text);
            yield { kind: "agent", payload: text };
        } else if (typeof msgType === "string" && thinkingKinds.has(msgType) && typeof text === "string" && text) {
            yield { kind: "thinking", payload: text };
        }
    }

    result.answer = compiledParts.join("");
    yield { kind: "done", payload: result };
}

/** Shape of one chunk on the streaming_chat wire. */
interface ChunkResponse {
    type?: string;
    text?: string;
    chat_context?: Record<string, Json>;
    sly_data?: Record<string, Json>;
    structure?: {
        network_call?: {
            kind?: string;
            method?: string;
            url?: string;
            status?: number | null;
            ms?: number;
            via?: string;
        };
        [k: string]: unknown;
    };
}

/**
 * Yield successive lines from a streaming Response body. Handles chunked
 * transfer where line boundaries don't align with read chunks. Tolerates both
 * \n and \r\n line endings.
 */
export async function* streamLines(response: Response): AsyncGenerator<string, void, void> {
    if (!response.body) {
        // Some test fakes have no body; treat as empty.
        return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) {
                break;
            }
            buffer += decoder.decode(value, { stream: true });
            let newlineIdx: number;
            while ((newlineIdx = buffer.indexOf("\n")) >= 0) {
                let line = buffer.slice(0, newlineIdx);
                buffer = buffer.slice(newlineIdx + 1);
                if (line.endsWith("\r")) {
                    line = line.slice(0, -1);
                }
                yield line;
            }
        }
        // Flush any trailing line without a terminator.
        buffer += decoder.decode();
        if (buffer.length > 0) {
            yield buffer;
        }
    } finally {
        reader.releaseLock();
    }
}
