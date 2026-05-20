// Smoke test: load the built neuro_san_lite.js bundle and run one chat turn
// against a live origin. Used to verify the bundle produced by the build
// pipeline actually drives the real wire format.
//
//   node demo/agent_web_browser_site/smoke.mjs
//
// Requires the demo origins running (./demo/agent_web/start_origins.sh) and
// ANTHROPIC_API_KEY set in the env (source ~/workspace/setMyEnv.sh).

import { runAgentTurn } from "./neuro_san_lite.js";

const URL_BASE = "http://localhost:8803/api/v1/trip_planner/network";
const anthropicKey = process.env.ANTHROPIC_API_KEY;

if (!anthropicKey) {
    console.error("✗ no ANTHROPIC_API_KEY in env — cannot run smoke test");
    process.exit(2);
}

const events = [];
const opts = {
    url: URL_BASE,
    message: "one short sentence: where is San Francisco?",
    anthropicKey,
    slyData: { passenger_email: "bob@example.com" },
};

let answer = "";
for await (const event of runAgentTurn(opts)) {
    events.push(event.kind);
    if (event.kind === "agent") {
        answer += event.payload;
    } else if (event.kind === "thinking") {
        process.stdout.write(`[thinking] ${event.payload}\n`);
    } else if (event.kind === "error") {
        console.error(`[error] ${event.payload}`);
    } else if (event.kind === "network") {
        const e = event.payload;
        console.log(`[net] ${e.method} ${e.url} ${e.status ?? '...'}`);
    } else if (event.kind === "done") {
        const r = event.payload;
        console.log(`\n[answer] ${r.answer}`);
        console.log(`[chatContext keys] ${Object.keys(r.chatContext).join(',')}`);
    }
}

if (!answer || !answer.toLowerCase().includes("california")) {
    console.error(`✗ smoke test FAILED: answer did not mention California: ${answer}`);
    process.exit(1);
}
console.log("\n✓ smoke test PASSED");
