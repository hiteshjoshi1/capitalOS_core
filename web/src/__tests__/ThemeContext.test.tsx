import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme } from "../context/ThemeContext";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    patchPreferences: vi.fn(),
    isAuthenticated: vi.fn<() => boolean>(() => false),
  },
}));

vi.mock("../lib/api", () => ({
  api: mockApi,
}));

function ThemeConsumer() {
  const { theme, accent, toggleTheme, setAccent, applyServerPreferences } = useTheme();
  return (
    <div>
      <div data-testid="theme">{theme}</div>
      <div data-testid="accent">{accent}</div>
      <button onClick={toggleTheme}>toggle</button>
      <button onClick={() => setAccent("#2b6ddb")}>set-accent</button>
      <button
        onClick={() =>
          applyServerPreferences({ theme: "light", accent_color: "#8650d9" })
        }
      >
        apply-server
      </button>
    </div>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockApi.patchPreferences.mockResolvedValue({ theme: "dark", accent_color: "#0f7a5c" });
    mockApi.isAuthenticated.mockReturnValue(false);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders with localStorage defaults (dark theme, green accent)", () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(screen.getByTestId("accent").textContent).toBe("#0f7a5c");
  });

  it("reads persisted theme from localStorage on mount", () => {
    window.localStorage.setItem("capitalos.theme", "light");
    window.localStorage.setItem("capitalos.accent", "#2b6ddb");

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(screen.getByTestId("accent").textContent).toBe("#2b6ddb");
  });

  it("does NOT patch server when not authenticated", async () => {
    mockApi.isAuthenticated.mockReturnValue(false);

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(mockApi.patchPreferences).not.toHaveBeenCalled();
    });
  });

  it("patches server on theme toggle when authenticated", async () => {
    mockApi.isAuthenticated.mockReturnValue(true);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    // Clear any initial effect calls
    mockApi.patchPreferences.mockClear();

    await user.click(screen.getByText("toggle"));

    await waitFor(() => {
      expect(screen.getByTestId("theme").textContent).toBe("light");
    });

    await waitFor(() => {
      expect(mockApi.patchPreferences).toHaveBeenCalledWith({ theme: "light" });
    });

    // Theme toggle must NOT also trigger a redundant accent PATCH — that would race
    // the theme PATCH and could overwrite the new theme with the old value on the server.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(mockApi.patchPreferences).toHaveBeenCalledTimes(1);
  });

  it("patches server on accent change when authenticated", async () => {
    mockApi.isAuthenticated.mockReturnValue(true);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    mockApi.patchPreferences.mockClear();

    await user.click(screen.getByText("set-accent"));

    await waitFor(() => {
      expect(screen.getByTestId("accent").textContent).toBe("#2b6ddb");
    });

    await waitFor(() => {
      expect(mockApi.patchPreferences).toHaveBeenCalledWith({ accent_color: "#2b6ddb" });
    });
  });

  it("applies server preferences and updates state", async () => {
    mockApi.isAuthenticated.mockReturnValue(true);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    mockApi.patchPreferences.mockClear();

    await user.click(screen.getByText("apply-server"));

    await waitFor(() => {
      expect(screen.getByTestId("theme").textContent).toBe("light");
      expect(screen.getByTestId("accent").textContent).toBe("#8650d9");
    });
  });

  it("does not patch server when applyServerPreferences is called", async () => {
    mockApi.isAuthenticated.mockReturnValue(true);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    // Flush any initial effect calls
    await act(async () => {
      await Promise.resolve();
    });
    mockApi.patchPreferences.mockClear();

    await user.click(screen.getByText("apply-server"));

    // Allow any potential PATCH calls to fire
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(mockApi.patchPreferences).not.toHaveBeenCalled();
  });

  it("persists theme to localStorage on change", async () => {
    mockApi.isAuthenticated.mockReturnValue(false);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    await user.click(screen.getByText("toggle"));

    await waitFor(() => {
      expect(window.localStorage.getItem("capitalos.theme")).toBe("light");
    });
  });

  it("persists accent to localStorage on change", async () => {
    mockApi.isAuthenticated.mockReturnValue(false);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    await user.click(screen.getByText("set-accent"));

    await waitFor(() => {
      expect(window.localStorage.getItem("capitalos.accent")).toBe("#2b6ddb");
    });
  });

  it("ignores patchPreferences errors gracefully", async () => {
    mockApi.isAuthenticated.mockReturnValue(true);
    mockApi.patchPreferences.mockRejectedValue(new Error("Network error"));
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    // Should not throw
    await expect(
      user.click(screen.getByText("toggle")),
    ).resolves.not.toThrow();

    await waitFor(() => {
      expect(screen.getByTestId("theme").textContent).toBe("light");
    });
  });
});
