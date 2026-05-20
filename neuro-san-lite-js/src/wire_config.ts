// Port of neuro_san_client/wire_config.py
// Extract + verify the scrubbed JSON payload from an Agent Web notebook.

import type { Json, Notebook, ToolSpec, WireConfig } from "./types.js";

export const AGENT_NETWORK_MIMETYPE = "application/x-agent-network+json";
export const SUPPORTED_PROTOCOL_VERSION = "0.1";

export class WireConfigError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "WireConfigError";
    }
}

/** Locate the network-spec raw cell inside an Agent Web notebook and parse it. */
export function extractWireConfigFromNotebook(notebook: Notebook | unknown): WireConfig {
    if (!notebook || typeof notebook !== "object" || Array.isArray(notebook)) {
        throw new WireConfigError(
            `Notebook must be an object, got ${typeof notebook}`,
        );
    }
    const nb = notebook as Notebook;
    const cells = nb.cells;
    if (!Array.isArray(cells)) {
        throw new WireConfigError("Notebook has no 'cells' array");
    }

    for (const cell of cells) {
        if (!cell || typeof cell !== "object" || cell.cell_type !== "raw") {
            continue;
        }
        const meta = (cell.metadata ?? {}) as Record<string, Json>;
        const role = meta["agent_web_role"];
        const fmt = meta["format"];
        if (role === "network_spec" || fmt === AGENT_NETWORK_MIMETYPE) {
            let source: string | string[] | undefined = cell.source as string | string[] | undefined;
            if (Array.isArray(source)) {
                source = source.join("");
            }
            if (typeof source !== "string") {
                throw new WireConfigError(
                    `Spec cell 'source' must be string or list of strings, got ${typeof source}`,
                );
            }
            try {
                return JSON.parse(source) as WireConfig;
            } catch (exc) {
                throw new WireConfigError(
                    `Spec cell does not parse as JSON: ${(exc as Error).message}`,
                );
            }
        }
    }

    throw new WireConfigError(
        "No agent_web network_spec cell found in notebook. Is this an Agent Web notebook?",
    );
}

/**
 * Enforce browser-side invariants on a wire config. Throws WireConfigError on
 * any violation. Returns void on success.
 */
export function verifyWireConfig(wire: unknown): asserts wire is WireConfig {
    if (!wire || typeof wire !== "object" || Array.isArray(wire)) {
        throw new WireConfigError(
            `Wire config must be an object, got ${typeof wire}`,
        );
    }
    const w = wire as WireConfig;

    const meta = w.agent_web ?? null;
    if (!meta || typeof meta !== "object") {
        throw new WireConfigError("agent_web metadata block is malformed");
    }
    const proto = meta.protocol_version;
    const origin = meta.origin;
    if (proto !== SUPPORTED_PROTOCOL_VERSION) {
        throw new WireConfigError(
            `Agent Web protocol version mismatch: notebook is ${JSON.stringify(proto)}, ` +
            `runtime supports ${JSON.stringify(SUPPORTED_PROTOCOL_VERSION)}.`,
        );
    }
    if (typeof origin !== "string" || !origin) {
        throw new WireConfigError(
            "Notebook missing agent_web.origin metadata; refusing to load.",
        );
    }

    let originUrl: URL;
    try {
        originUrl = new URL(origin);
    } catch {
        throw new WireConfigError(
            `agent_web.origin is not a fully-qualified URL: ${JSON.stringify(origin)}`,
        );
    }
    if (!originUrl.protocol || !originUrl.host) {
        throw new WireConfigError(
            `agent_web.origin is not a fully-qualified URL: ${JSON.stringify(origin)}`,
        );
    }

    const tools = w.tools ?? [];
    if (!Array.isArray(tools)) {
        throw new WireConfigError("wire 'tools' must be an array");
    }

    for (const tool of tools as ToolSpec[]) {
        if (!tool || typeof tool !== "object") {
            continue;
        }
        const name = tool.name ?? "<unnamed>";
        if ("class" in tool) {
            throw new WireConfigError(
                `tool ${JSON.stringify(name)} still has 'class' in the wire form. ` +
                `Origin's scrubber is misconfigured.`,
            );
        }
        if ("toolbox" in tool) {
            throw new WireConfigError(
                `tool ${JSON.stringify(name)} still has 'toolbox' in the wire form.`,
            );
        }

        const codedToolUrl = tool.coded_tool_url;
        if (codedToolUrl !== undefined && codedToolUrl !== null) {
            if (typeof codedToolUrl !== "string") {
                throw new WireConfigError(
                    `tool ${JSON.stringify(name)}: coded_tool_url must be a string`,
                );
            }
            let toolUrl: URL;
            try {
                toolUrl = new URL(codedToolUrl);
            } catch {
                throw new WireConfigError(
                    `tool ${JSON.stringify(name)}: coded_tool_url ${JSON.stringify(codedToolUrl)} is malformed.`,
                );
            }
            if (toolUrl.protocol !== originUrl.protocol || toolUrl.host !== originUrl.host) {
                throw new WireConfigError(
                    `tool ${JSON.stringify(name)}: coded_tool_url ${JSON.stringify(codedToolUrl)} ` +
                    `is not same-origin with the notebook origin ${JSON.stringify(origin)}.`,
                );
            }
        }

        if (tool.client_side) {
            if (!tool.client_side_source) {
                throw new WireConfigError(
                    `tool ${JSON.stringify(name)}: client_side tool is missing ` +
                    `client_side_source.`,
                );
            }
            const integrity = tool.integrity;
            if (typeof integrity !== "string" || !integrity.startsWith("sha256-")) {
                throw new WireConfigError(
                    `tool ${JSON.stringify(name)}: client_side tool is missing a valid ` +
                    `sha256-* integrity hash.`,
                );
            }
        }
    }
}

/**
 * Verify shipped client-side source matches its declared integrity hash and
 * return the raw bytes. Uses Web Crypto (`crypto.subtle.digest`).
 *
 * Returns a Promise<Uint8Array> because subtle.digest is async.
 */
export async function verifyClientSideSourceIntegrity(
    sourceB64: string,
    integrity: string,
): Promise<Uint8Array> {
    if (typeof sourceB64 !== "string" || !sourceB64) {
        throw new WireConfigError("client_side_source is empty or not a string");
    }
    if (typeof integrity !== "string" || !integrity.startsWith("sha256-")) {
        throw new WireConfigError(
            `integrity must be a sha256-<hex> string, got ${JSON.stringify(integrity)}`,
        );
    }

    let sourceBytes: Uint8Array;
    try {
        sourceBytes = decodeBase64(sourceB64);
    } catch (exc) {
        throw new WireConfigError(
            `bad base64 in client_side_source: ${(exc as Error).message}`,
        );
    }

    const cryptoObj = getCrypto();
    // Pass the ArrayBuffer view to keep TS strict mode happy across Node/browser.
    const digestBuffer = await cryptoObj.subtle.digest(
        "SHA-256",
        sourceBytes.buffer.slice(
            sourceBytes.byteOffset,
            sourceBytes.byteOffset + sourceBytes.byteLength,
        ) as ArrayBuffer,
    );
    const actual = hexEncode(new Uint8Array(digestBuffer));
    const expected = integrity.substring("sha256-".length);
    if (expected !== actual) {
        throw new WireConfigError(
            `integrity check failed: expected sha256-${expected}, got sha256-${actual}`,
        );
    }
    return sourceBytes;
}

/** Get the SubtleCrypto instance — works in browsers and Node 18+. */
function getCrypto(): Crypto {
    // Browser: globalThis.crypto. Node 18+: globalThis.crypto too. No fallback needed.
    const c: Crypto | undefined = (globalThis as { crypto?: Crypto }).crypto;
    if (!c || !c.subtle) {
        throw new WireConfigError(
            "Web Crypto is unavailable; cannot verify client_side_source integrity.",
        );
    }
    return c;
}

function decodeBase64(s: string): Uint8Array {
    // atob is available in browsers and Node 16+; fall back to Buffer if needed.
    if (typeof atob === "function") {
        // Validate: atob is lenient about whitespace but throws on bad chars.
        if (/[^A-Za-z0-9+/=\s]/.test(s)) {
            throw new Error("invalid base64 character");
        }
        const binary = atob(s);
        const arr = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            arr[i] = binary.charCodeAt(i);
        }
        return arr;
    }
    // Node fallback.
    const buf = (globalThis as { Buffer?: { from(s: string, e: string): Uint8Array } }).Buffer;
    if (!buf) {
        throw new Error("no base64 decoder available");
    }
    return buf.from(s, "base64");
}

function hexEncode(bytes: Uint8Array): string {
    let s = "";
    for (let i = 0; i < bytes.length; i++) {
        s += bytes[i].toString(16).padStart(2, "0");
    }
    return s;
}

export function getOrigin(wire: WireConfig): string {
    return wire.agent_web?.origin ?? "";
}

export function getNetworkName(wire: WireConfig): string {
    return wire.agent_web?.network_name ?? "";
}

export function listToolNames(wire: WireConfig): string[] {
    const out: string[] = [];
    for (const tool of wire.tools ?? []) {
        if (tool && typeof tool === "object" && typeof tool.name === "string") {
            out.push(tool.name);
        }
    }
    return out;
}
