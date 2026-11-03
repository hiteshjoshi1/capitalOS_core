import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FxNote from "./FxNote";
import { fxNoteText } from "../lib/fxNote";

describe("FxNote (#139)", () => {
  it("says nothing when every rate is known", () => {
    expect(fxNoteText({ fx_incomplete: false, fx_missing_currencies: [], fx_stale_currencies: [] }, null)).toBeNull();
    const { container } = render(<FxNote sources={[{}]} />);
    expect(container.innerHTML).toBe("");
  });

  it("names excluded and stale currencies across responses, once each", () => {
    const text = fxNoteText(
      { fx_incomplete: true, fx_missing_currencies: ["XYZ"], fx_stale_currencies: ["USD"] },
      { fx_incomplete: true, fx_missing_currencies: ["XYZ"], fx_stale_currencies: ["XYZ", "HKD"] },
    );
    expect(text).toBe("Excludes amounts in XYZ: no exchange rate available. Uses older exchange rates for HKD, USD.");
  });

  it("renders as a note", () => {
    render(<FxNote sources={[{ fx_incomplete: true, fx_missing_currencies: ["XYZ"] }]} />);
    expect(screen.getByRole("note").textContent).toContain("Excludes amounts in XYZ");
  });
});
