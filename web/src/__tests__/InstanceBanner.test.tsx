import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import InstanceBanner from "../components/InstanceBanner";
import { instanceLabel } from "../lib/instance";

describe("InstanceBanner", () => {
  it("renders nothing for the real app (no label)", () => {
    const { container } = render(<InstanceBanner label="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the label and marks the page title", () => {
    document.title = "CapitalOS";
    render(<InstanceBanner label="TEST test/20261029 PRs #54 #55" />);
    expect(screen.getByRole("status", { name: "Instance" })).toHaveTextContent(
      "TEST test/20261029 PRs #54 #55 · not the real app",
    );
    expect(screen.getByRole("status", { name: "Instance" })).toHaveClass("instanceBanner-test");
    expect(document.title).toBe("[TEST] CapitalOS");
  });

  it("reads and trims VITE_INSTANCE_LABEL, ignoring non-strings", () => {
    expect(instanceLabel({ VITE_INSTANCE_LABEL: "  DEV feature/x " })).toBe("DEV feature/x");
    expect(instanceLabel({})).toBe("");
    expect(instanceLabel({ VITE_INSTANCE_LABEL: 1 })).toBe("");
  });
});
