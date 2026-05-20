// Vitest unit tests for src/agent_runner.ts.
// Mirrors neuro-san-client/tests/unit/test_agent_runner.py case-for-case.
// Uses a stub fetch to deterministically simulate the origin.

import { describe, expect, it } from "vitest";
import {
    buildRequest,
    deriveStreamingChatUrl,
    runAgentTurn,
    streamLines,
} from "../src/agent_runner.js";
import { AGENT_NETWORK_MIMETYPE, SUPPORTED_PROTOCOL_VERSION } from "../src/wire_config.js";
import type { ChatEvent, RunnerOptions, RunnerResult } from "../src/types.js";

// ---------- fixtures ----------

function minimalWire(
    origin = "http://origin.example:8801",
    networkName = "flight_finder",
): any {
    return {
        agent_web: {
            protocol_version: SUPPORTED_PROTOCOL_VERSION,
            origin,
            network_name: networkName,
        },
        llm_config: { model_name: "claude-haiku" },
        tools: [],
    };
}

function notebook(spec: unknown): any {
    return {
        nbformat: 4,
        metadata: {},
        cells: [
            {
                cell_type: "raw",
                metadata: {
                    format: AGENT_NETWORK_MIMETYPE,
                    agent_web_role: "network_spec",
                },
                source: JSON.stringify(spec),
            },
        ],
    };
}

function streamingChunk(
    text: string,
    msgType = "AI",
    chatContext?: unknown,
    slyData?: unknown,
    structure?: unknown,
): string {
    const response: Record<string, unknown> = { type: msgType, text };
    if (chatContext !== undefined) {
        response.chat_context = chatContext;
    }
    if (slyData !== undefined) {
        response.sly_data = slyData;
    }
    if (structure !== undefined) {
        response.structure = structure;
    }
    return JSON.stringify({ response }) + "\n";
}

/**
 * Build a fetch stub that serves /network with the given wire config and
 * /streaming_chat with the given line-delimited chunks. Records the
 * streaming request body and URL for assertions.
 */
function makeMockFetch(wire: unknown, chunks: string[]) {
    const recorded: { url: string; body: string } = { url: "", body: "" };

    const mockFetch: typeof fetch = async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/network")) {
            return new Response(JSON.stringify(notebook(wire)), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            });
        }
        if (url.endsWith("/streaming_chat")) {
            recorded.url = url;
            recorded.body =
                typeof init?.body === "string"
                    ? init.body
                    : init?.body instanceof ArrayBuffer
                      ? new TextDecoder().decode(init.body)
                      : String(init?.body ?? "");
            return new Response(chunks.join(""), {
                status: 200,
                headers: { "Content-Type": "application/json-lines" },
            });
        }
        return new Response(`unhandled: ${url}`, { status: 404 });
    };

    return { mockFetch, recorded };
}

// ---------- deriveStreamingChatUrl ----------

describe("deriveStreamingChatUrl", () => {
    it("simple http", () => {
        expect(
            deriveStreamingChatUrl(
                "http://origin.example:8801/api/v1/foo/network",
                "foo",
            ),
        ).toBe("http://origin.example:8801/api/v1/foo/streaming_chat");
    });

    it("https", () => {
        expect(
            deriveStreamingChatUrl(
                "https://api.example/api/v1/bar/network",
                "bar",
            ),
        ).toBe("https://api.example/api/v1/bar/streaming_chat");
    });

    it("origin takes precedence over path shape", () => {
        expect(
            deriveStreamingChatUrl("http://origin.example/anything", "x"),
        ).toMatch(/^http:\/\/origin\.example\/api\/v1\/x\//);
    });

    it("bad URL raises", () => {
        expect(() =>
            deriveStreamingChatUrl("/just/a/path", "foo"),
        ).toThrow(/not fully qualified/);
    });
});

// ---------- buildRequest ----------

describe("buildRequest", () => {
    it("minimal request has user_message and MAXIMAL chat_filter", () => {
        const opts: RunnerOptions = { url: "x", message: "hi" };
        expect(buildRequest(opts)).toEqual({
            user_message: { type: "HUMAN", text: "hi" },
            chat_filter: { chat_filter_type: "MAXIMAL" },
        });
    });

    it("anthropic key lands in sly_data.llm_config", () => {
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            anthropicKey: "sk-ant-foo",
        };
        const body = buildRequest(opts);
        const sly = (body.sly_data as any).llm_config;
        expect(sly.api_key).toBe("sk-ant-foo");
        expect(sly.anthropic_api_key).toBe("sk-ant-foo");
    });

    it("openai key lands in sly_data.llm_config", () => {
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            openaiKey: "sk-openai-bar",
        };
        const sly = (buildRequest(opts).sly_data as any).llm_config;
        expect(sly.api_key).toBe("sk-openai-bar");
        expect(sly.openai_api_key).toBe("sk-openai-bar");
    });

    it("both keys send both provider-specific", () => {
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            anthropicKey: "sk-a",
            openaiKey: "sk-o",
        };
        const sly = (buildRequest(opts).sly_data as any).llm_config;
        // api_key defaults to anthropic (set first)
        expect(sly.api_key).toBe("sk-a");
        expect(sly.anthropic_api_key).toBe("sk-a");
        expect(sly.openai_api_key).toBe("sk-o");
    });

    it("caller-supplied sly_data is preserved", () => {
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            slyData: { passenger_email: "bob@example.com" },
            anthropicKey: "sk-ant-foo",
        };
        const body = buildRequest(opts);
        expect((body.sly_data as any).passenger_email).toBe("bob@example.com");
        expect((body.sly_data as any).llm_config.api_key).toBe("sk-ant-foo");
    });

    it("caller-supplied llm_config takes precedence", () => {
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            slyData: { llm_config: { api_key: "explicitly-set" } },
            anthropicKey: "sk-ant-foo",
        };
        const sly = (buildRequest(opts).sly_data as any).llm_config;
        expect(sly.api_key).toBe("explicitly-set");
        expect(sly.anthropic_api_key).toBe("sk-ant-foo");
    });

    it("chat context threaded in", () => {
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            chatContext: { history: ["..."] },
        };
        expect(buildRequest(opts).chat_context).toEqual({ history: ["..."] });
    });

    it("empty chat context omitted", () => {
        const opts: RunnerOptions = { url: "x", message: "hi", chatContext: {} };
        expect("chat_context" in buildRequest(opts)).toBe(false);
    });

    it("no mutation of caller sly_data", () => {
        const callerSly = { passenger_email: "bob@example.com" };
        const opts: RunnerOptions = {
            url: "x",
            message: "hi",
            slyData: callerSly,
            anthropicKey: "sk-ant-foo",
        };
        buildRequest(opts);
        expect(callerSly).toEqual({ passenger_email: "bob@example.com" });
    });
});

// ---------- streamLines ----------

describe("streamLines", () => {
    function makeResponse(body: string): Response {
        return new Response(body, { status: 200 });
    }

    it("splits on newlines", async () => {
        const r = makeResponse("line1\nline2\nline3\n");
        const out: string[] = [];
        for await (const line of streamLines(r)) {
            out.push(line);
        }
        expect(out).toEqual(["line1", "line2", "line3"]);
    });

    it("handles trailing line without newline", async () => {
        const r = makeResponse("line1\nline2");
        const out: string[] = [];
        for await (const line of streamLines(r)) {
            out.push(line);
        }
        expect(out).toEqual(["line1", "line2"]);
    });

    it("handles CRLF", async () => {
        const r = makeResponse("a\r\nb\r\n");
        const out: string[] = [];
        for await (const line of streamLines(r)) {
            out.push(line);
        }
        expect(out).toEqual(["a", "b"]);
    });

    it("empty body yields nothing", async () => {
        const r = makeResponse("");
        const out: string[] = [];
        for await (const line of streamLines(r)) {
            out.push(line);
        }
        expect(out).toEqual([]);
    });

    it("yields empty lines between newlines", async () => {
        const r = makeResponse("\n\nfoo\n");
        const out: string[] = [];
        for await (const line of streamLines(r)) {
            out.push(line);
        }
        expect(out).toEqual(["", "", "foo"]);
    });
});

// ---------- runAgentTurn full streaming flow ----------

describe("runAgentTurn", () => {
    async function collect(
        opts: RunnerOptions,
    ): Promise<ChatEvent[]> {
        const events: ChatEvent[] = [];
        for await (const e of runAgentTurn(opts)) {
            events.push(e);
        }
        return events;
    }

    it("minimal successful turn", async () => {
        const wire = minimalWire("http://origin.example", "trip_planner");
        const chunks = [
            streamingChunk("Hello, how can I help?", "AGENT_FRAMEWORK"),
            streamingChunk("", "AI", { history: ["..."] }, { last_booking_code: "HOLD-XYZ" }),
        ];
        const { mockFetch } = makeMockFetch(wire, chunks);

        const events = await collect({
            url: "http://origin.example/api/v1/trip_planner/network",
            message: "hi",
            anthropicKey: "sk-ant-foo",
            fetchImpl: mockFetch,
        });

        const kinds = events.map((e) => e.kind);
        expect(kinds).toContain("network");
        expect(kinds).toContain("agent");
        expect(kinds[kinds.length - 1]).toBe("done");

        const final = events[events.length - 1].payload as RunnerResult;
        expect(final.answer).toBe("Hello, how can I help?");
        expect(final.chatContext).toEqual({ history: ["..."] });
        expect(final.slyData.last_booking_code).toBe("HOLD-XYZ");
    });

    it("BYOK key is threaded into request body", async () => {
        const wire = minimalWire();
        const chunks = [streamingChunk("hi", "AGENT_FRAMEWORK")];
        const { mockFetch, recorded } = makeMockFetch(wire, chunks);

        await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            anthropicKey: "sk-ant-the-key",
            fetchImpl: mockFetch,
        });

        const body = JSON.parse(recorded.body);
        expect(body.sly_data.llm_config.api_key).toBe("sk-ant-the-key");
        expect(body.user_message.text).toBe("hi");
    });

    it("streaming URL uses wire-config origin", async () => {
        const wire = minimalWire("http://origin.example:8801", "flight_finder");
        const chunks = [streamingChunk("hi", "AGENT_FRAMEWORK")];
        const { mockFetch, recorded } = makeMockFetch(wire, chunks);

        await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            anthropicKey: "k",
            fetchImpl: mockFetch,
        });

        expect(recorded.url).toBe(
            "http://origin.example:8801/api/v1/flight_finder/streaming_chat",
        );
    });

    it("404 notebook yields error", async () => {
        const mockFetch: typeof fetch = async () =>
            new Response("not found", { status: 404 });
        const events = await collect({
            url: "http://x/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const kinds = events.map((e) => e.kind);
        expect(kinds).toContain("error");
        expect(kinds[kinds.length - 1]).toBe("done");
    });

    it("bad protocol version yields error", async () => {
        const wire = minimalWire();
        wire.agent_web.protocol_version = "9.9";
        const { mockFetch } = makeMockFetch(wire, []);

        const events = await collect({
            url: "http://x/api/v1/x/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const errEvent = events.find((e) => e.kind === "error");
        expect(errEvent).toBeDefined();
        expect(errEvent!.payload).toMatch(/Wire config invalid/);
    });

    it("streaming 500 yields error", async () => {
        const wire = minimalWire();
        const mockFetch: typeof fetch = async (input) => {
            const url = typeof input === "string" ? input : input.toString();
            if (url.endsWith("/network")) {
                return new Response(JSON.stringify(notebook(wire)), { status: 200 });
            }
            return new Response("internal", { status: 500 });
        };
        const events = await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const kinds = events.map((e) => e.kind);
        expect(kinds).toContain("error");
        expect(kinds[kinds.length - 1]).toBe("done");
    });

    it("thinking messages surface separately", async () => {
        const wire = minimalWire();
        const chunks = [
            streamingChunk("about to call tool", "AGENT"),
            streamingChunk("progress msg", "AGENT_PROGRESS"),
            streamingChunk("tool result", "AGENT_TOOL_RESULT"),
            streamingChunk("final answer", "AGENT_FRAMEWORK"),
        ];
        const { mockFetch } = makeMockFetch(wire, chunks);

        const events = await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const kinds = events.map((e) => e.kind);
        const thinkingCount = kinds.filter((k) => k === "thinking").length;
        expect(thinkingCount).toBe(3);   // AGENT, AGENT_PROGRESS, AGENT_TOOL_RESULT
        expect(kinds).toContain("agent");
        const result = events[events.length - 1].payload as RunnerResult;
        expect(result.answer).toBe("final answer");
    });

    it("server-side network calls surface as 'network' events", async () => {
        // A chunk whose structure.network_call is set should yield a
        // ChatEvent("network", ...) regardless of msgType — that's how the
        // browser learns about cross-origin calls the origin made on its behalf.
        const wire = minimalWire();
        const chunks = [
            streamingChunk(
                "Calling flight_finder",
                "AGENT",
                undefined,
                undefined,
                {
                    tool_start: true,
                    network_call: {
                        kind: "streaming_chat",
                        method: "POST",
                        url: "http://flights.example/flight_finder",
                        status: null,
                    },
                },
            ),
            streamingChunk(
                "Got result",
                "AGENT",
                undefined,
                undefined,
                {
                    tool_end: true,
                    network_call: {
                        kind: "streaming_chat",
                        method: "POST",
                        url: "http://flights.example/flight_finder",
                        status: 200,
                        ms: 1234,
                    },
                },
            ),
            streamingChunk("final answer", "AGENT_FRAMEWORK"),
        ];
        const { mockFetch } = makeMockFetch(wire, chunks);

        const events = await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const netEvents = events.filter((e) => e.kind === "network");
        // Browser-direct GET + POST + 2 server-reported = at least 4
        expect(netEvents.length).toBeGreaterThanOrEqual(4);
        const serverReported = netEvents.filter(
            (e) => (e.payload as { url?: string }).url?.startsWith("http://flights.example"),
        );
        expect(serverReported).toHaveLength(2);
        const ends = serverReported.filter(
            (e) => (e.payload as { status?: number }).status === 200,
        );
        expect(ends).toHaveLength(1);
        expect((ends[0].payload as { ms?: number }).ms).toBe(1234);
        for (const e of serverReported) {
            expect((e.payload as { via?: string }).via).toBe(
                "http://origin.example:8801/api/v1/flight_finder/network",
            );
        }
    });

    it("legacy AI message type still treated as final answer", async () => {
        const wire = minimalWire();
        const chunks = [streamingChunk("legacy AI text", "AI")];
        const { mockFetch } = makeMockFetch(wire, chunks);
        const events = await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const result = events[events.length - 1].payload as RunnerResult;
        expect(result.answer).toBe("legacy AI text");
    });

    it("empty lines in stream are ignored", async () => {
        const wire = minimalWire();
        const chunks = ["\n", streamingChunk("hi", "AGENT_FRAMEWORK"), "\n"];
        // (regression: this used to test "AI" message type)
        const { mockFetch } = makeMockFetch(wire, chunks);

        const events = await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const result = events[events.length - 1].payload as RunnerResult;
        expect(result.answer).toBe("hi");
    });

    it("malformed JSON line is skipped", async () => {
        const wire = minimalWire();
        const chunks = ["not valid json\n", streamingChunk("ok", "AGENT_FRAMEWORK")];
        const { mockFetch } = makeMockFetch(wire, chunks);

        const events = await collect({
            url: "http://origin.example:8801/api/v1/flight_finder/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const result = events[events.length - 1].payload as RunnerResult;
        expect(result.answer).toBe("ok");
    });

    it("network fetch error yields error event", async () => {
        const mockFetch: typeof fetch = async () => {
            throw new Error("network down");
        };
        const events = await collect({
            url: "http://x/network",
            message: "hi",
            fetchImpl: mockFetch,
        });
        const errEvent = events.find((e) => e.kind === "error");
        expect(errEvent).toBeDefined();
        expect(errEvent!.payload).toMatch(/Notebook fetch failed/);
    });
});
