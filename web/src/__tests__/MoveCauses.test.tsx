import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MoveCauses, { MoveCausesList } from "../components/MoveCauses";
import { api } from "../lib/api";
import type { MoveCauses as MoveCausesData } from "../lib/api";
import { causeAmount, shouldShowMoveCauses } from "../lib/moveCauses";

vi.mock("../lib/api", () => ({ api: { monthBridge: vi.fn() } }));
const mockApi = vi.mocked(api, true);

function data(overrides: Partial<MoveCausesData> = {}): MoveCausesData {
  return { change: 0, change_pct: 0, is_big_move: false, causes: [], none_reason: null, ...overrides };
}

describe("move causes (#289)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows for a big move or a significant cause only", () => {
    expect(shouldShowMoveCauses(null)).toBe(false);
    expect(shouldShowMoveCauses(data())).toBe(false);
    expect(shouldShowMoveCauses(data({ causes: [{ key: "price_fallback", label: "x", amount: 5, significant: false }] }))).toBe(false);
    expect(shouldShowMoveCauses(data({ is_big_move: true }))).toBe(true);
    expect(shouldShowMoveCauses(data({ causes: [{ key: "fx_gap", label: "x", amount: null, significant: true }] }))).toBe(true);
  });

  it("sizes new things at their value and changes with a sign; unknown has no size", () => {
    expect(causeAmount({ key: "first_statement", label: "", amount: 60000, significant: true }, "SGD")).toBe("S$ 60,000");
    expect(causeAmount({ key: "catch_up", label: "", amount: -20000, significant: true }, "SGD")).toBe("-S$ 20,000");
    expect(causeAmount({ key: "statement", label: "", amount: 30000, significant: true }, "SGD")).toBe("+S$ 30,000");
    expect(causeAmount({ key: "fx_gap", label: "", amount: null, significant: true }, "SGD")).toBeNull();
  });

  it("lists significant causes, then the rest under Also, and says when nothing explains a big move", () => {
    render(
      <MoveCausesList
        currency="SGD"
        data={data({
          is_big_move: true,
          causes: [
            { key: "fx_gap", label: "No exchange rate for USD", amount: null, significant: true, detail: "Left out" },
            { key: "price_fallback", label: "2 holding(s) at their statement price", amount: 1500, significant: false },
          ],
        })}
      />,
    );
    const note = screen.getByRole("note", { name: "Why it moved" });
    expect(screen.getByTestId("move-cause-fx_gap")).toHaveTextContent("No exchange rate for USD");
    expect(screen.getByTestId("move-cause-fx_gap")).toHaveTextContent("Left out");
    expect(note).toHaveTextContent("Also: 2 holding(s) at their statement price · S$ 1,500");
    expect(screen.queryByTestId("move-cause-price_fallback")).not.toBeInTheDocument();

    render(<MoveCausesList currency="SGD" data={data({ is_big_move: true, none_reason: "No data cause found: a market move" })} />);
    expect(screen.getByText("No data cause found: a market move")).toBeInTheDocument();
  });

  it("Overview reads the month bridge's causes and hides when there's nothing to say", async () => {
    mockApi.monthBridge.mockResolvedValue({
      base_currency: "SGD",
      move_causes: data({ is_big_move: true, causes: [{ key: "catch_up", label: "Catch-up statement for Synthetic Broker", amount: 20000, significant: true }] }),
    } as never);
    render(<MoveCauses month="2026-11" baseCurrency="SGD" />);
    expect(await screen.findByText("Catch-up statement for Synthetic Broker")).toBeInTheDocument();
    expect(screen.getByText("+S$ 20,000")).toBeInTheDocument();
    expect(mockApi.monthBridge).toHaveBeenCalledWith("2026-11", "SGD");
  });

  it("renders nothing for a small move with no significant cause", async () => {
    mockApi.monthBridge.mockResolvedValue({ base_currency: "SGD", move_causes: data() } as never);
    const { container } = render(<MoveCauses month="2026-10" baseCurrency="SGD" />);
    await vi.waitFor(() => expect(mockApi.monthBridge).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
