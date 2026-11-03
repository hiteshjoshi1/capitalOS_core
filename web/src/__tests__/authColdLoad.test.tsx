/**
 * #146: a cold page load makes exactly ONE auth request (POST /auth/refresh) before a
 * protected route renders. Uses the real api.ts / AuthProvider / ThemeProvider /
 * RequireAuth with only fetch stubbed.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

type FetchCall = { url: string; method: string };

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  };
}

describe("cold load auth (#146)", () => {
  let calls: FetchCall[];
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    calls = [];
    window.localStorage.clear();
    window.localStorage.setItem("capitalos.theme", "dark");
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  function stubFetch(refreshBody: unknown) {
    fetchSpy = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      if (url.endsWith("/auth/refresh")) return Promise.resolve(jsonResponse(refreshBody));
      if (url.endsWith("/auth/me")) return Promise.resolve(jsonResponse({ id: 1, username: "demo", is_admin: false }));
      if (url.endsWith("/auth/preferences")) {
        return Promise.resolve(jsonResponse({ theme: "light", accent_color: "#2b6ddb" }));
      }
      return Promise.resolve(jsonResponse({}, 404));
    });
    vi.stubGlobal("fetch", fetchSpy);
  }

  async function renderApp() {
    // Fresh module graph so the real api.ts starts with no token and no in-flight refresh.
    const [{ ThemeProvider }, { AuthProvider }, { default: RequireAuth }] = await Promise.all([
      import("../context/ThemeContext"),
      import("../context/AuthContext"),
      import("../components/RequireAuth"),
    ]);
    render(
      <ThemeProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={["/private"]}>
            <Routes>
              <Route path="/login" element={<div>login page</div>} />
              <Route element={<RequireAuth />}>
                <Route path="/private" element={<div>protected content</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </ThemeProvider>,
    );
  }

  it("renders a protected route after exactly one request, with the server theme applied", async () => {
    stubFetch({
      access_token: "token",
      token_type: "bearer",
      expires_in: 900,
      user: { id: 1, username: "demo", display_name: null, email: null, is_admin: false },
      preferences: { theme: "light", accent_color: "#2b6ddb" },
    });

    await renderApp();
    expect(await screen.findByText("protected content")).toBeInTheDocument();

    expect(calls).toEqual([{ url: expect.stringMatching(/\/auth\/refresh$/), method: "POST" }]);
    // The server theme is applied in an effect after the first protected render; on a
    // slow runner the assertion could run before it (flaked in CI), so wait for it.
    await waitFor(() => expect(document.documentElement.getAttribute("data-theme")).toBe("light"));
    expect(window.localStorage.getItem("capitalos.accent")).toBe("#2b6ddb");

    // Applying server preferences must not echo a PATCH back, nor fetch anything else.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(calls).toHaveLength(1);
  });

  it("still works against a token-only refresh response (falls back to /auth/me, preferences in background)", async () => {
    stubFetch({ access_token: "token", token_type: "bearer", expires_in: 900 });

    await renderApp();
    expect(await screen.findByText("protected content")).toBeInTheDocument();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(calls.map((c) => c.url.replace(/^.*(\/auth\/)/, "$1"))).toEqual([
      "/auth/refresh",
      "/auth/me",
      "/auth/preferences",
    ]);
    await waitFor(() => expect(document.documentElement.getAttribute("data-theme")).toBe("light"));
  });
});
