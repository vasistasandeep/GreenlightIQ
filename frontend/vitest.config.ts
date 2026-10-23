import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

/**
 * Generic frontend test harness (React Testing Library + jsdom).
 *
 * Shared by all component/interaction test suites (dashboard, title
 * evaluation, calibration studio). Kept intentionally project-wide — not
 * scoped to any single view — so sibling suites can reuse it unchanged.
 */
export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary", "html", "json-summary"],
      reportsDirectory: "./coverage",
      include: ["app/**", "components/**", "lib/**"],
      exclude: [
        "**/*.{test,spec}.{ts,tsx}",
        "**/*.d.ts",
        "**/node_modules/**",
        ".next/**",
        "**/layout.tsx",
        "lib/types.ts",
      ],
    },
  },
});
