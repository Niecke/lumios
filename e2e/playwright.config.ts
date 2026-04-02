import { defineConfig } from "@playwright/test";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8080";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  retries: 0,
  workers: 1, // run serially — tests share state in the same DB
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: BACKEND_URL,
    extraHTTPHeaders: {
      Accept: "application/json",
    },
  },
});
