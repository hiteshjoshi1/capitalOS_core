import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";

import CryptoWallets from "../routes/CryptoWallets";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    cryptoWallets: vi.fn(),
    cryptoAllowlist: vi.fn(),
  },
}));

vi.mock("wagmi", () => ({
  useAccount: () => ({ address: undefined, isConnected: false }),
  useChainId: () => 1,
  useDisconnect: () => ({ disconnect: vi.fn() }),
  useSignMessage: () => ({ signMessageAsync: undefined }),
}));

vi.mock("@solana/wallet-adapter-react", () => ({
  useWallet: () => ({
    publicKey: null,
    connected: false,
    signMessage: undefined,
    signTransaction: undefined,
    disconnect: vi.fn(),
    wallet: null,
  }),
}));

vi.mock("@solana/wallet-adapter-react-ui", () => ({
  WalletMultiButton: () => <button type="button">Connect Solana Wallet</button>,
}));

vi.mock("@rainbow-me/rainbowkit", () => ({
  ConnectButton: {
    Custom: ({
      children,
    }: {
      children: (props: {
        account: null;
        chain: null;
        openAccountModal: () => void;
        openChainModal: () => void;
        openConnectModal: () => void;
        mounted: boolean;
      }) => ReactNode;
    }) => (
      <>
        {children({
          account: null,
          chain: null,
          openAccountModal: vi.fn(),
          openChainModal: vi.fn(),
          openConnectModal: vi.fn(),
          mounted: true,
        })}
      </>
    ),
  },
}));

const mockApi = vi.mocked(api, true);

describe("CryptoWallets route", () => {
  it("renders dashboard-only primary nav without a self tab", async () => {
    mockApi.cryptoWallets.mockResolvedValueOnce([]);
    mockApi.cryptoAllowlist.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoWallets />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Add wallet")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(within(nav).getAllByRole("link")).toHaveLength(1);
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(within(nav).queryByRole("link", { name: "Crypto Wallets" })).not.toBeInTheDocument();
  });
});
