import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { FormEvent } from "react";
import PlatformDetailsForm, { type PlatformDraft } from "../components/PlatformDetailsForm";

function renderForm(overrides: Partial<{
  value: PlatformDraft;
  onChange: (next: PlatformDraft) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
  submitLabel: string;
}> = {}) {
  const value: PlatformDraft = overrides.value ?? {
    code: "",
    name: "",
    platform_type: "",
    country: "",
    website: "",
  };
  const onChange = overrides.onChange ?? vi.fn();
  const onSubmit = overrides.onSubmit ?? vi.fn((e: FormEvent<HTMLFormElement>) => e.preventDefault());
  const onCancel = overrides.onCancel;
  const submitLabel = overrides.submitLabel ?? "Save platform";

  render(
    <PlatformDetailsForm
      value={value}
      platformTypes={["BANK", "BROKER"]}
      platformCountries={["SG", "US"]}
      onChange={onChange}
      onSubmit={onSubmit}
      onCancel={onCancel}
      submitLabel={submitLabel}
    />,
  );

  return { onChange, onSubmit };
}

describe("PlatformDetailsForm", () => {
  it("propagates input changes", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderForm({ onChange });

    await user.type(screen.getByLabelText("Platform Code"), "dbs");
    await user.type(screen.getByLabelText("Platform Name"), "DBS Bank");

    expect(onChange).toHaveBeenCalled();
  });

  it("submits the form with custom button label", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((e: FormEvent<HTMLFormElement>) => e.preventDefault());
    renderForm({
      submitLabel: "Create platform",
      onSubmit,
      value: {
        code: "DBS",
        name: "DBS Bank",
        platform_type: "BANK",
        country: "SG",
        website: "",
      },
    });

    await user.click(screen.getByRole("button", { name: "Create platform" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("renders cancel action when provided", () => {
    renderForm({ onCancel: vi.fn() });
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });
});
