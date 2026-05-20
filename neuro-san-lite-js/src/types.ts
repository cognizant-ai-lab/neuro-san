// Shared type definitions for neuro-san-lite.
// No Python counterpart — pure type layer.

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

export interface AgentWebMeta {
    protocol_version: string;
    origin: string;
    network_name: string;
    published_at?: string;
}

export interface ToolSpec {
    name: string;
    function?: Record<string, Json>;
    instructions?: string;
    tools?: string[];
    coded_tool_url?: string;
    client_side?: boolean;
    client_side_source?: string;
    client_side_class?: string;
    integrity?: string;
    allow?: Record<string, Json>;
    [k: string]: Json | undefined;
}

export interface WireConfig {
    agent_web?: AgentWebMeta;
    llm_config?: Record<string, Json>;
    tools?: ToolSpec[];
    [k: string]: Json | ToolSpec[] | AgentWebMeta | undefined;
}

export interface Notebook {
    nbformat?: number;
    metadata?: Record<string, Json>;
    cells?: NotebookCell[];
    [k: string]: Json | NotebookCell[] | undefined;
}

export interface NotebookCell {
    cell_type: string;
    metadata?: Record<string, Json>;
    source?: string | string[];
    outputs?: Json[];
    execution_count?: number | null;
}

/** sly_data is an arbitrary JSON object; values can be anything. */
export type SlyData = Record<string, Json>;

/** The shape of an emitted event from the chat runner. */
export type ChatEventKind =
    | "user"
    | "agent"
    | "thinking"
    | "network"
    | "error"
    | "done";

export interface NetworkEventPayload {
    kind: "notebook" | "streaming_chat" | "tool";
    method: string;
    url: string;
    status: number | null;
    ms?: number;
}

export interface ChatEvent {
    kind: ChatEventKind;
    payload: unknown;   // typed at the call site by kind
}

/** Options for one run of the chat loop. */
export interface RunnerOptions {
    /** Full URL to the Agent Web network endpoint. */
    url: string;
    /** The user's message for this turn. */
    message: string;
    /** Optional Anthropic key; threaded into sly_data.llm_config. */
    anthropicKey?: string;
    /** Optional OpenAI key; threaded into sly_data.llm_config. */
    openaiKey?: string;
    /** Optional chat context from a previous turn. */
    chatContext?: Record<string, Json>;
    /** Optional sly_data to merge in (BYOK keys are added on top). */
    slyData?: SlyData;
    /** Per-turn timeout in milliseconds (default 180_000). */
    timeoutMs?: number;
    /** Fetch implementation override (for tests). Defaults to global fetch. */
    fetchImpl?: typeof fetch;
}

/** Returned by the final "done" event. */
export interface RunnerResult {
    chatContext: Record<string, Json>;
    slyData: SlyData;
    answer: string;
}
