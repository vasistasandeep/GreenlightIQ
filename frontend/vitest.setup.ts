import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * Global test setup for the frontend component suites.
 *
 * - Registers jest-dom matchers (toBeInTheDocument, toHaveTextContent, ...).
 * - Unmounts React trees after every test so suites stay isolated.
 */
afterEach(() => {
  cleanup();
});
