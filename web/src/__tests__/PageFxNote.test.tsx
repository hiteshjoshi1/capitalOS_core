import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import FxNote from "../components/FxNote";
import PageShell from "../components/PageShell";
import { AuthContext, type AuthContextValue } from "../context/authContextObject";
import { api, type AuthMe, type FxBackfillResult } from "../lib/api";

function withUser(isAdmin: boolean, ui: React.ReactNode) {
  const value: AuthContextValue = {
    user: { id: 1, username: "owner", display_name: "Owner", is_admin: isAdmin } as AuthMe,
    loading: false,
    login: async () => {},
    signup: async () => {},
    logout: async () => {},
  };
  return <AuthContext.Provider value={value}>{ui}</AuthContext.Provider>;
}

function Page() {
  // Three cards that each used to print the same note (#290).
  return (
    <PageShell title="Overview">
      <section>
        <FxNote sources={[{ fx_incomplete: true, fx_missing_currencies: ["USD"] }]} />
      </section>
      <section>
        <FxNote sources={[{ fx_incomplete: true, fx_missing_currencies: ["USD"] }, null]} />
      </section>
      <section>
        <FxNote sources={[{ fx_incomplete: true, fx_missing_currencies: ["HKD"], fx_stale_currencies: ["INR"] }]} />
      </section>
      <FxNote sources={[{ fx_incomplete: false, fx_missing_currencies: [], fx_stale_currencies: [] }]} />
    </PageShell>
  );
}

const RESULT: FxBackfillResult = {
  status: "completed",
  span_start: "2025-12-29",
  span_end: "2026-11-06",
  currencies: ["HKD", "SGD", "USD"],
  unsupported_currencies: [],
  uncovered_days: 220,
  planned_requests: [{ start: "2025-12-29", end: "2026-11-06" }],
  remaining_requests: 0,
  fetched_requests: 1,
  failed_requests: 0,
  rows_stored: 6000,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("one FX note per page (#290)", () => {
  it("shows every card's FX gaps once, at the page level", async () => {
    render(withUser(true, <Page />));
    const notes = await screen.findAllByTestId("fx-note");
    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent(
      "Excludes amounts in HKD, USD: no exchange rate available. Uses older exchange rates for INR.",
    );
  });

  it("renders nothing when every value converted", () => {
    render(
      withUser(
        true,
        <PageShell title="Overview">
          <FxNote sources={[{ fx_incomplete: false, fx_missing_currencies: [], fx_stale_currencies: [] }]} />
        </PageShell>,
      ),
    );
    expect(screen.queryByTestId("fx-note")).not.toBeInTheDocument();
  });

  it("lets an admin fetch the missing past rates and says what happened", async () => {
    const spy = vi.spyOn(api, "fxBackfill").mockResolvedValue(RESULT);
    render(withUser(true, <Page />));
    await userEvent.click(await screen.findByRole("button", { name: "Fetch missing rates" }));
    expect(spy).toHaveBeenCalledWith("SGD");
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Fetched past exchange rates for 29 Dec 2025 to 6 Nov 2026. Reload to see them.",
      ),
    );
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });

  it("says when more remain and when the provider has no rates for a currency", async () => {
    vi.spyOn(api, "fxBackfill").mockResolvedValue({ ...RESULT, status: "partial", remaining_requests: 3, unsupported_currencies: ["ZZZ"] });
    render(withUser(true, <Page />));
    await userEvent.click(await screen.findByRole("button", { name: "Fetch missing rates" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("More remain: fetch again to continue."));
    expect(screen.getByRole("status")).toHaveTextContent("The provider has no rates for ZZZ.");
  });

  it("offers no fetch to a member, only says an admin can", async () => {
    render(withUser(false, <Page />));
    expect(await screen.findByText("An admin can fetch the missing rates.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fetch missing rates" })).not.toBeInTheDocument();
  });

  it("still renders inline outside a page (a card on its own)", () => {
    render(<FxNote sources={[{ fx_incomplete: true, fx_missing_currencies: ["USD"] }]} />);
    expect(screen.getByTestId("fx-note")).toHaveTextContent("Excludes amounts in USD");
  });
});
