import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "lcov"],
      // UI composition is protected by typecheck/build. The deterministic
      // coverage gate targets reusable client logic and stateful hooks.
      include: ["lib/**/*.ts", "hooks/**/*.ts"],
      exclude: ["lib/types.ts"],
      thresholds: {
        lines: 95,
        statements: 95,
        functions: 95,
        branches: 95,
      },
    },
  },
});
