import { defineConfig } from "vitest/config";

export default defineConfig({
    test: {
        globals: true,
        environment: "node",  // We don't need DOM; fetch is global in Node 18+.
        include: ["test/**/*.test.ts"],
    },
});
