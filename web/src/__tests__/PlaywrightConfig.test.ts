import { describe, expect, it } from "vitest";
import config from "../../playwright.config";

describe("playwright config", () => {
  it("defines local e2e web server and chromium project", () => {
    expect(config.testDir).toBe("./tests/e2e");
    expect(config.use?.baseURL).toBe("http://127.0.0.1:4173");
    const webServer = Array.isArray(config.webServer) ? config.webServer[0] : config.webServer;
    expect(webServer?.url).toBe("http://127.0.0.1:4173");
    expect(config.projects?.[0]?.name).toBe("chromium");
  });
});
