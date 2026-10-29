import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChangePasswordCard from "../components/ChangePasswordCard";

const mockChangePassword = vi.fn();

vi.mock("../lib/api", () => ({
  api: { changePassword: (...args: unknown[]) => mockChangePassword(...args) },
}));

async function fill(current: string, next: string, confirm: string) {
  const user = userEvent.setup();
  render(<ChangePasswordCard />);
  await user.type(screen.getByLabelText("Current password"), current);
  await user.type(screen.getByLabelText("New password"), next);
  await user.type(screen.getByLabelText("Confirm new password"), confirm);
  await user.click(screen.getByRole("button", { name: "Change password" }));
}

describe("ChangePasswordCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("changes the password, clears the form and reports signed-out sessions", async () => {
    mockChangePassword.mockResolvedValueOnce({ status: "ok", signed_out_sessions: 2 });
    await fill("OldPass123!", "NewPass456!", "NewPass456!");

    expect(mockChangePassword).toHaveBeenCalledWith({ current_password: "OldPass123!", new_password: "NewPass456!" });
    expect(await screen.findByRole("status")).toHaveTextContent("Password changed. Signed out 2 other sessions.");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });

  it("stops when the new passwords don't match", async () => {
    await fill("OldPass123!", "NewPass456!", "NewPass789!");

    expect(await screen.findByRole("alert")).toHaveTextContent("The new passwords don't match.");
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it("stops when the new password is the current one", async () => {
    await fill("OldPass123!", "OldPass123!", "OldPass123!");

    expect(await screen.findByRole("alert")).toHaveTextContent("must be different");
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it("shows the API's error and keeps what was typed", async () => {
    mockChangePassword.mockRejectedValueOnce(new Error("Current password is incorrect"));
    await fill("Wrong123!", "NewPass456!", "NewPass456!");

    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect");
    expect(screen.getByLabelText("New password")).toHaveValue("NewPass456!");
  });
});
