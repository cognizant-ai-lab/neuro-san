// Vitest unit tests for src/wire_config.ts.
// Mirrors neuro-san-client/tests/unit/test_wire_config.py case-for-case.

import { describe, expect, it } from "vitest";

import {
    AGENT_NETWORK_MIMETYPE,
    SUPPORTED_PROTOCOL_VERSION,
    WireConfigError,
    extractWireConfigFromNotebook,
    getNetworkName,
    getOrigin,
    listToolNames,
    verifyClientSideSourceIntegrity,
    verifyWireConfig,
} from "../src/wire_config.js";

// ---------- fixtures ----------

function minimalWire(overrides: Record<string, unknown> = {}): any {
    return {
        agent_web: {
            protocol_version: SUPPORTED_PROTOCOL_VERSION,
            origin: "http://origin.example:8801",
            network_name: "flight_finder",
        },
        llm_config: { model_name: "claude-haiku" },
        tools: [],
        ...overrides,
    };
}

function notebookWithSpec(spec: unknown): any {
    return {
        nbformat: 4,
        metadata: {},
        cells: [
            { cell_type: "markdown", metadata: {}, source: "# hi" },
            {
                cell_type: "raw",
                metadata: {
                    format: AGENT_NETWORK_MIMETYPE,
                    agent_web_role: "network_spec",
                },
                source: JSON.stringify(spec),
            },
            { cell_type: "code", metadata: {}, source: "print('hi')" },
        ],
    };
}

// Helper: base64-encode a UTF-8 string in a way that works in both Node and browsers.
function base64Encode(s: string): string {
    if (typeof Buffer !== "undefined") {
        return Buffer.from(s, "utf-8").toString("base64");
    }
    return btoa(s);
}

// ---------- extractWireConfigFromNotebook ----------

describe("extractWireConfigFromNotebook", () => {
    it("finds role-tagged cell", () => {
        const spec = minimalWire();
        const nb = notebookWithSpec(spec);
        expect(extractWireConfigFromNotebook(nb)).toEqual(spec);
    });

    it("finds mimetype-tagged cell", () => {
        const spec = minimalWire();
        const nb = notebookWithSpec(spec);
        delete nb.cells[1].metadata.agent_web_role;
        expect(extractWireConfigFromNotebook(nb)).toEqual(spec);
    });

    it("source as list of lines", () => {
        const spec = minimalWire();
        const specText = JSON.stringify(spec, null, 2);
        const nb = notebookWithSpec(spec);
        // Split lines preserving terminators, like nbformat does.
        nb.cells[1].source = specText.split(/(?<=\n)/);
        expect(extractWireConfigFromNotebook(nb)).toEqual(spec);
    });

    it("skips non-spec raw cells", () => {
        const spec = minimalWire();
        const nb = {
            cells: [
                { cell_type: "raw", metadata: {}, source: "not a spec" },
                {
                    cell_type: "raw",
                    metadata: { agent_web_role: "network_spec" },
                    source: JSON.stringify(spec),
                },
            ],
        };
        expect(extractWireConfigFromNotebook(nb)).toEqual(spec);
    });

    it("no spec cell raises", () => {
        expect(() =>
            extractWireConfigFromNotebook({
                cells: [{ cell_type: "markdown", metadata: {}, source: "#" }],
            }),
        ).toThrow(/No agent_web network_spec/);
    });

    it("invalid JSON raises", () => {
        const nb = {
            cells: [
                {
                    cell_type: "raw",
                    metadata: { agent_web_role: "network_spec" },
                    source: "{ not valid json",
                },
            ],
        };
        expect(() => extractWireConfigFromNotebook(nb)).toThrow(/does not parse as JSON/);
    });

    it("non-object notebook raises", () => {
        expect(() => extractWireConfigFromNotebook("not a notebook")).toThrow(
            /Notebook must be an object/,
        );
    });

    it("missing cells raises", () => {
        expect(() => extractWireConfigFromNotebook({ nbformat: 4 })).toThrow(
            /no 'cells' array/,
        );
    });

    it("bad source type raises", () => {
        const nb = {
            cells: [
                {
                    cell_type: "raw",
                    metadata: { agent_web_role: "network_spec" },
                    source: 123,
                },
            ],
        };
        expect(() => extractWireConfigFromNotebook(nb)).toThrow(/must be string or list/);
    });
});

// ---------- verifyWireConfig ----------

describe("verifyWireConfig", () => {
    it("minimal wire passes", () => {
        expect(() => verifyWireConfig(minimalWire())).not.toThrow();
    });

    it("protocol version mismatch raises", () => {
        const w = minimalWire();
        w.agent_web.protocol_version = "9.9";
        expect(() => verifyWireConfig(w)).toThrow(/protocol version mismatch/);
    });

    it("missing origin raises", () => {
        const w = minimalWire();
        delete w.agent_web.origin;
        expect(() => verifyWireConfig(w)).toThrow(/missing agent_web.origin/);
    });

    it("origin must be fully qualified", () => {
        const w = minimalWire();
        w.agent_web.origin = "not-a-url";
        expect(() => verifyWireConfig(w)).toThrow(/not a fully-qualified URL/);
    });

    it("same-origin coded_tool_url passes", () => {
        const w = minimalWire();
        w.tools = [
            {
                name: "search_flights",
                coded_tool_url: "http://origin.example:8801/api/v1/x/tool/y",
            },
        ];
        expect(() => verifyWireConfig(w)).not.toThrow();
    });

    it("cross-origin coded_tool_url raises", () => {
        const w = minimalWire();
        w.tools = [
            {
                name: "search_flights",
                coded_tool_url: "http://evil.example/api/v1/x/tool/y",
            },
        ];
        expect(() => verifyWireConfig(w)).toThrow(/not same-origin/);
    });

    it("https vs http is a mismatch", () => {
        const w = minimalWire();
        w.agent_web.origin = "https://origin.example";
        w.tools = [
            { name: "x", coded_tool_url: "http://origin.example/tool/x" },
        ];
        expect(() => verifyWireConfig(w)).toThrow(/not same-origin/);
    });

    it("different port is a mismatch", () => {
        const w = minimalWire();
        w.tools = [
            { name: "x", coded_tool_url: "http://origin.example:9999/tool/x" },
        ];
        expect(() => verifyWireConfig(w)).toThrow(/not same-origin/);
    });

    it("leftover class field raises", () => {
        const w = minimalWire();
        w.tools = [{ name: "x", class: "should.have.been.stripped" }];
        expect(() => verifyWireConfig(w)).toThrow(/still has 'class'/);
    });

    it("leftover toolbox field raises", () => {
        const w = minimalWire();
        w.tools = [{ name: "x", toolbox: "should.have.been.stripped" }];
        expect(() => verifyWireConfig(w)).toThrow(/still has 'toolbox'/);
    });

    it("client_side missing source raises", () => {
        const w = minimalWire();
        w.tools = [{ name: "calc", client_side: true, integrity: "sha256-abc" }];
        expect(() => verifyWireConfig(w)).toThrow(/missing client_side_source/);
    });

    it("client_side missing integrity raises", () => {
        const w = minimalWire();
        w.tools = [
            { name: "calc", client_side: true, client_side_source: "Zm9v" },
        ];
        expect(() => verifyWireConfig(w)).toThrow(/missing a valid sha256/);
    });

    it("client_side bad integrity prefix raises", () => {
        const w = minimalWire();
        w.tools = [
            {
                name: "calc",
                client_side: true,
                client_side_source: "Zm9v",
                integrity: "md5-abc",
            },
        ];
        expect(() => verifyWireConfig(w)).toThrow(/missing a valid sha256/);
    });

    it("non-object wire raises", () => {
        expect(() => verifyWireConfig([])).toThrow(/must be an object/);
    });

    it("tools not list raises", () => {
        const w = minimalWire();
        w.tools = "not a list";
        expect(() => verifyWireConfig(w)).toThrow(/must be an array/);
    });
});

// ---------- verifyClientSideSourceIntegrity ----------

describe("verifyClientSideSourceIntegrity", () => {
    it("matching hash passes", async () => {
        const src = "class Calc:\n    pass\n";
        const b64 = base64Encode(src);
        // Pre-compute SHA-256 via WebCrypto to confirm round-trip.
        const cryptoObj = (globalThis as { crypto?: Crypto }).crypto!;
        const digest = await cryptoObj.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(src),
        );
        const hex = [...new Uint8Array(digest)]
            .map((b) => b.toString(16).padStart(2, "0"))
            .join("");
        const out = await verifyClientSideSourceIntegrity(b64, `sha256-${hex}`);
        expect(new TextDecoder().decode(out)).toBe(src);
    });

    it("mismatched hash raises", async () => {
        const src = "class Calc:\n    pass\n";
        const b64 = base64Encode(src);
        await expect(
            verifyClientSideSourceIntegrity(b64, "sha256-" + "0".repeat(64)),
        ).rejects.toThrow(/integrity check failed/);
    });

    it("bad base64 raises", async () => {
        await expect(
            verifyClientSideSourceIntegrity("this is not base64!", "sha256-x"),
        ).rejects.toThrow(/bad base64/);
    });

    it("empty source raises", async () => {
        await expect(
            verifyClientSideSourceIntegrity("", "sha256-x"),
        ).rejects.toThrow(/is empty/);
    });

    it("missing integrity prefix raises", async () => {
        await expect(
            verifyClientSideSourceIntegrity("Zm9v", "md5-abc"),
        ).rejects.toThrow(/sha256-<hex>/);
    });
});

// ---------- accessors ----------

describe("accessors", () => {
    it("getOrigin", () => {
        expect(getOrigin(minimalWire())).toBe("http://origin.example:8801");
        expect(getOrigin({} as any)).toBe("");
    });

    it("getNetworkName", () => {
        expect(getNetworkName(minimalWire())).toBe("flight_finder");
        expect(getNetworkName({} as any)).toBe("");
    });

    it("listToolNames", () => {
        const w = minimalWire();
        w.tools = [
            { name: "a" },
            { name: "b" },
            { no_name: "x" },
            "not a dict",
        ];
        expect(listToolNames(w as any)).toEqual(["a", "b"]);
    });

    it("listToolNames empty", () => {
        expect(listToolNames({} as any)).toEqual([]);
    });
});

// ---------- WireConfigError ----------

describe("WireConfigError", () => {
    it("has the right name", () => {
        const err = new WireConfigError("test");
        expect(err.name).toBe("WireConfigError");
        expect(err.message).toBe("test");
        expect(err).toBeInstanceOf(Error);
    });
});
