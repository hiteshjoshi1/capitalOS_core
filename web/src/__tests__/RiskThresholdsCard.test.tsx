import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RiskThresholdsCard from "../components/RiskThresholdsCard";
import { api } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

vi.mock("../lib/api", () => ({
  api: {
    riskThresholds: vi.fn(),
    saveRiskThresholds: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);
const NONE = { largest_position_warn_pct: null, top_n_warn_pct: null, platform_warn_pct: null };

describe("RiskThresholdsCard (#253)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearApiCache();
    mockApi.riskThresholds.mockResolvedValue({ ...NONE, largest_position_warn_pct: 20 });
  });

  it("shows the user's thresholds, with the defaults as placeholders", async () => {
    render(<RiskThresholdsCard />);

    const largest = await screen.findByLabelText("Largest position (%)");
    await waitFor(() => expect(largest).toHaveValue(20));
    const topN = screen.getByLabelText("Top 3 / top 5 positions (%)");
    expect(topN).toHaveValue(null);
    expect(topN).toHaveAttribute("placeholder", "50");
    expect(screen.getByLabelText("One platform (%)")).toHaveAttribute("placeholder", "50");
    expect(screen.getByText(/One holding's share of net worth\. Default 15%\./)).toBeInTheDocument();
  });

  it("saves the thresholds (blank = default) and shares them with the Risk page", async () => {
    const user = userEvent.setup();
    const saved = { largest_position_warn_pct: 20, top_n_warn_pct: 40, platform_warn_pct: null };
    mockApi.saveRiskThresholds.mockResolvedValue(saved);
    render(<RiskThresholdsCard />);

    const topN = await screen.findByLabelText("Top 3 / top 5 positions (%)");
    await waitFor(() => expect(topN).not.toBeDisabled());
    await user.type(topN, "40");
    await user.click(screen.getByRole("button", { name: "Save thresholds" }));

    expect(mockApi.saveRiskThresholds).toHaveBeenCalledWith(saved);
    expect(await screen.findByRole("status")).toHaveTextContent("Saved. The Risk page uses these thresholds.");
    // The saved answer is now what the shared cache entry (the Risk page's) holds: the
    // form shows it from there, with no second GET.
    expect(topN).toHaveValue(40);
    expect(mockApi.riskThresholds).toHaveBeenCalledTimes(1);
  });

  it("refuses a value outside (0, 100]", async () => {
    const user = userEvent.setup();
    render(<RiskThresholdsCard />);

    const platform = await screen.findByLabelText("One platform (%)");
    await waitFor(() => expect(platform).not.toBeDisabled());
    await user.type(platform, "150");
    await user.click(screen.getByRole("button", { name: "Save thresholds" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("One platform: enter a percent above 0 and up to 100");
    expect(mockApi.saveRiskThresholds).not.toHaveBeenCalled();
  });

  it("resets every threshold to the default", async () => {
    const user = userEvent.setup();
    mockApi.saveRiskThresholds.mockResolvedValue(NONE);
    render(<RiskThresholdsCard />);

    const reset = await screen.findByRole("button", { name: "Reset to defaults" });
    await waitFor(() => expect(reset).not.toBeDisabled());
    await user.click(reset);

    expect(mockApi.saveRiskThresholds).toHaveBeenCalledWith(NONE);
    expect(await screen.findByRole("status")).toHaveTextContent("Back to the defaults.");
    expect(screen.getByLabelText("Largest position (%)")).toHaveValue(null);
  });
});
