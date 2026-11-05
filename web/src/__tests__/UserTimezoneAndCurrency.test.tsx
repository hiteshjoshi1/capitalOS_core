/**
 * #202: home timezone filled from the browser on first sign-in, base currency saved on
 * the server (the per-browser value is the first paint, the server's wins after load),
 * and Settings changes both.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import HomeRegionCard from "../components/HomeRegionCard";
import { AuthProvider } from "../context/AuthContext";
import {
  BASE_CURRENCY_STORAGE_KEY,
  resetServerBaseCurrency,
  syncServerBaseCurrency,
  useBaseCurrency,
} from "../context/CurrencyContext";
import { ThemeProvider } from "../context/ThemeContext";

const { mockApi, mockRefreshSessionNow } = vi.hoisted(() => ({
  mockApi: {
    authMe: vi.fn(),
    authLogin: vi.fn(),
    authSignup: vi.fn(),
    authLogout: vi.fn(),
    getPreferences: vi.fn(),
    patchPreferences: vi.fn(),
    isAuthenticated: vi.fn(),
  },
  mockRefreshSessionNow: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: mockApi,
  refreshAccessTokenNow: vi.fn(),
  refreshSessionNow: mockRefreshSessionNow,
  setAccessToken: vi.fn(),
  setAuthFailureHandler: vi.fn(),
}));

function Reader() {
  const [ccy] = useBaseCurrency();
  return <span data-testid="ccy">{ccy}</span>;
}

function session(preferences: Record<string, unknown>) {
  return {
    access_token: "t",
    token_type: "bearer",
    expires_in: 3600,
    user: { id: 1, username: "synthetic", is_admin: false },
    preferences: { theme: "dark", accent_color: "#0f7a5c", ...preferences },
  };
}

function renderApp() {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <Reader />
      </AuthProvider>
    </ThemeProvider>,
  );
}

function mockBrowserTimezone(zone: string) {
  const real = Intl.DateTimeFormat;
  vi.spyOn(Intl, "DateTimeFormat").mockImplementation(
    (...args: ConstructorParameters<typeof Intl.DateTimeFormat>) => {
      const formatter = new real(...args);
      const resolved = formatter.resolvedOptions();
      formatter.resolvedOptions = () => ({ ...resolved, timeZone: zone });
      return formatter;
    },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  resetServerBaseCurrency();
  mockApi.isAuthenticated.mockReturnValue(true);
  mockApi.patchPreferences.mockImplementation(async (patch: Record<string, unknown>) => ({
    theme: "dark",
    accent_color: "#0f7a5c",
    timezone: "Asia/Singapore",
    timezone_source: "user",
    base_currency: null,
    ...patch,
  }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("base currency saved on the server (#202)", () => {
  it("first paint is this browser's value; the server's value wins after load", async () => {
    window.localStorage.setItem(BASE_CURRENCY_STORAGE_KEY, "HKD");
    let resolve: (value: unknown) => void = () => {};
    mockRefreshSessionNow.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    renderApp();
    expect(screen.getByTestId("ccy").textContent).toBe("HKD");
    await act(async () => resolve(session({ timezone: "Asia/Singapore", timezone_source: "user", base_currency: "USD" })));
    await waitFor(() => expect(screen.getByTestId("ccy").textContent).toBe("USD"));
    expect(window.localStorage.getItem(BASE_CURRENCY_STORAGE_KEY)).toBe("USD");
    // Applying the server's value doesn't echo it back.
    expect(mockApi.patchPreferences).not.toHaveBeenCalledWith({ base_currency: "USD" });
  });

  it("a server with none gets this browser's saved choice, so other devices see it", async () => {
    window.localStorage.setItem(BASE_CURRENCY_STORAGE_KEY, "INR");
    mockRefreshSessionNow.mockResolvedValueOnce(session({ timezone: "Asia/Singapore", timezone_source: "user", base_currency: null }));
    renderApp();
    await waitFor(() => expect(mockApi.patchPreferences).toHaveBeenCalledWith({ base_currency: "INR" }));
    expect(screen.getByTestId("ccy").textContent).toBe("INR");
  });

  it("a server from before #202 (no field) changes nothing", () => {
    window.localStorage.setItem(BASE_CURRENCY_STORAGE_KEY, "HKD");
    act(() => syncServerBaseCurrency(undefined));
    expect(window.localStorage.getItem(BASE_CURRENCY_STORAGE_KEY)).toBe("HKD");
    expect(mockApi.patchPreferences).not.toHaveBeenCalled();
  });

  it("the header picker saves the choice on the server when signed in, and not when signed out", () => {
    render(<BaseCurrencyPicker />);
    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "USD" } });
    expect(mockApi.patchPreferences).toHaveBeenCalledWith({ base_currency: "USD" });

    mockApi.isAuthenticated.mockReturnValue(false);
    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "HKD" } });
    expect(mockApi.patchPreferences).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(BASE_CURRENCY_STORAGE_KEY)).toBe("HKD");
  });
});

describe("home timezone (#202)", () => {
  it("first sign-in fills an unset timezone from the browser", async () => {
    mockBrowserTimezone("America/New_York");
    mockRefreshSessionNow.mockResolvedValueOnce(session({ timezone: "Asia/Singapore", timezone_source: "unset", base_currency: null }));
    renderApp();
    await waitFor(() => expect(mockApi.patchPreferences).toHaveBeenCalledWith({ timezone: "America/New_York" }));
  });

  it("never overwrites a timezone the user has, or an older account's app default", async () => {
    mockBrowserTimezone("America/New_York");
    for (const source of ["user", "app"]) {
      mockRefreshSessionNow.mockResolvedValueOnce(session({ timezone: "Asia/Singapore", timezone_source: source, base_currency: "SGD" }));
      const view = renderApp();
      await waitFor(() => expect(screen.getByTestId("ccy").textContent).toBe("SGD"));
      view.unmount();
    }
    expect(mockApi.patchPreferences).not.toHaveBeenCalledWith({ timezone: "America/New_York" });
  });

  it("Settings shows the home timezone and saves a new one", async () => {
    mockBrowserTimezone("Europe/London");
    mockApi.getPreferences.mockResolvedValueOnce({
      theme: "dark",
      accent_color: "#0f7a5c",
      timezone: "Asia/Singapore",
      timezone_source: "app",
      base_currency: "SGD",
    });
    render(<HomeRegionCard />);
    const select = (await screen.findByLabelText(/Home timezone/)) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("Asia/Singapore"));
    expect(screen.getByText(/app's default \(Asia\/Singapore\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Use this device's timezone \(Europe\/London\)/ }));
    await waitFor(() => expect(mockApi.patchPreferences).toHaveBeenCalledWith({ timezone: "Europe/London" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Months now follow Europe/London");

    fireEvent.change(screen.getByLabelText(/Base currency/), { target: { value: "HKD" } });
    expect(mockApi.patchPreferences).toHaveBeenCalledWith({ base_currency: "HKD" });
  });

  it("Settings reports a timezone the server refuses", async () => {
    mockApi.getPreferences.mockResolvedValueOnce({
      theme: "dark",
      accent_color: "#0f7a5c",
      timezone: "Asia/Singapore",
      timezone_source: "user",
      base_currency: null,
    });
    mockApi.patchPreferences.mockRejectedValueOnce(new Error("timezone must be an IANA timezone name"));
    render(<HomeRegionCard />);
    const select = (await screen.findByLabelText(/Home timezone/)) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("Asia/Singapore"));
    const other = [...select.options].map((o) => o.value).find((zone) => zone && zone !== "Asia/Singapore");
    expect(other).toBeTruthy();
    fireEvent.change(select, { target: { value: other } });
    expect(await screen.findByRole("alert")).toHaveTextContent("IANA");
  });
});
