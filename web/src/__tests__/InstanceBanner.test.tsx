import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import InstanceBanner from "../components/InstanceBanner";
import { instanceLabel, instanceRepoUrl } from "../lib/instance";

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

  it("links each #N to its PR when a repo URL is set", () => {
    render(
      <InstanceBanner label="TEST test/20261030 · PRs #96 #101" repoUrl="https://github.com/o/r" />,
    );
    const banner = screen.getByRole("status", { name: "Instance" });
    expect(banner).toHaveTextContent("TEST test/20261030 · PRs #96 #101 · not the real app");
    expect(screen.getByRole("link", { name: "#96" })).toHaveAttribute(
      "href",
      "https://github.com/o/r/pull/96",
    );
    expect(screen.getByRole("link", { name: "#101" })).toHaveAttribute(
      "href",
      "https://github.com/o/r/pull/101",
    );
  });

  it("shows plain text without a repo URL", () => {
    render(<InstanceBanner label="TEST test/20261030 · PRs #96" repoUrl="" />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("reads VITE_INSTANCE_REPO_URL, https only", () => {
    expect(instanceRepoUrl({ VITE_INSTANCE_REPO_URL: " https://github.com/o/r/ " })).toBe(
      "https://github.com/o/r",
    );
    expect(instanceRepoUrl({ VITE_INSTANCE_REPO_URL: "javascript:alert(1)" })).toBe("");
    expect(instanceRepoUrl({ VITE_INSTANCE_REPO_URL: "http://github.com/o/r" })).toBe("");
    expect(instanceRepoUrl({})).toBe("");
  });

  it("reads and trims VITE_INSTANCE_LABEL, ignoring non-strings", () => {
    expect(instanceLabel({ VITE_INSTANCE_LABEL: "  DEV feature/x " })).toBe("DEV feature/x");
    expect(instanceLabel({})).toBe("");
    expect(instanceLabel({ VITE_INSTANCE_LABEL: 1 })).toBe("");
  });
});
