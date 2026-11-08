import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #327: the browser tab read "web" with the Vite logo (the starter template's).
describe("index.html", () => {
  const html = readFileSync(resolve(__dirname, "../../index.html"), "utf8");

  it("titles the page CapitalOS", () => {
    expect(html).toContain("<title>CapitalOS</title>");
  });

  it("uses the CapitalOS icon, not Vite's", () => {
    expect(html).toContain('href="/favicon.svg"');
    expect(html).not.toContain("vite.svg");
  });
});
