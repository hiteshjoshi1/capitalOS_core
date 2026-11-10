import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WalletConnectForm from "../wallet/WalletConnectForm";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    cryptoWallets: vi.fn(),
    cryptoAllowlist: vi.fn(),
    cryptoWalletInit: vi.fn(),
    cryptoWalletVerify: vi.fn(),
    cryptoWalletVerifyOnchain: vi.fn(),
    solanaBlockhash: vi.fn(),
    solanaPreflight: vi.fn(),
    solanaSubmit: vi.fn(),
    cryptoAllowlistAdd: vi.fn(),
  },
}));

const { mockSolanaState } = vi.hoisted(() => ({
  mockSolanaState: {
    publicKey: null as { toString: () => string } | null,
    connected: false,
    signMessage: undefined as ((msg: Uint8Array) => Promise<Uint8Array>) | undefined,
    signTransaction: undefined as ((tx: unknown) => Promise<unknown>) | undefined,
    disconnect: vi.fn(),
    wallet: null as { adapter?: { name?: string } } | null,
  },
}));

vi.mock("../lib/api", () => ({
  api: mockApi,
}));

vi.mock("@solana/wallet-adapter-react", () => ({
  useWallet: () => mockSolanaState,
}));

vi.mock("@solana/wallet-adapter-react-ui", () => ({
  WalletMultiButton: () => <button type="button">Connect Solana Wallet</button>,
}));

type EthereumProviderMock = {
  request: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  removeListener: ReturnType<typeof vi.fn>;
};

function setEthereumProvider(provider: EthereumProviderMock | undefined) {
  Object.defineProperty(window, "ethereum", {
    value: provider,
    configurable: true,
    writable: true,
  });
}

const onVerified = vi.fn();

function renderRoute(chainType: "evm" | "solana" = "evm") {
  return render(<WalletConnectForm chainType={chainType} label="" onVerified={onVerified} />);
}

// #319: the connect-and-sign step of "+ Add" (was the Add Crypto Wallets page).
describe("WalletConnectForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSolanaState.publicKey = null;
    mockSolanaState.connected = false;
    mockSolanaState.signMessage = undefined;
    mockSolanaState.signTransaction = undefined;
    mockSolanaState.wallet = null;
    mockApi.cryptoWallets.mockResolvedValue([]);
    mockApi.cryptoAllowlist.mockResolvedValue([]);
    mockApi.cryptoWalletInit.mockResolvedValue({
      verification_id: 9,
      chain_type: "evm",
      chain: "ethereum",
      address: "0xabc",
      message_to_sign: "sign me",
      nonce: "nonce-1",
      expires_at: "2099-01-01T00:00:00Z",
    });
    mockApi.cryptoWalletVerify.mockResolvedValue({ wallet_id: "w1", status: "verified" });
    mockApi.cryptoAllowlistAdd.mockResolvedValue({
      id: 1,
      chain: "ethereum",
      contract_address: "0xabc",
      symbol: "ABC",
      name: "Alpha",
    });
  });

  it("shows the connect wallet action", async () => {
    setEthereumProvider(undefined);
    renderRoute();
    expect(await screen.findByRole("button", { name: "Connect wallet" })).toBeInTheDocument();
  });

  it("shows error when trying to connect EVM without provider", async () => {
    setEthereumProvider(undefined);
    const user = userEvent.setup();
    renderRoute();

    await user.click(await screen.findByRole("button", { name: "Connect wallet" }));
    expect(await screen.findByText(/No EVM wallet detected/i)).toBeInTheDocument();
  });

  it("connects EVM wallet and verifies signature", async () => {
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_accounts") return [];
      if (method === "eth_chainId") return "0x1";
      if (method === "eth_requestAccounts") return ["0xabc"];
      if (method === "personal_sign") return "0xsigned";
      return null;
    });
    setEthereumProvider({
      request,
      on: vi.fn(),
      removeListener: vi.fn(),
    });

    const user = userEvent.setup();
    renderRoute();

    await user.click(await screen.findByRole("button", { name: "Connect wallet" }));
    await waitFor(() => {
      expect(screen.getByText("Connected: 0xabc")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Sign & verify" }));

    await waitFor(() => {
      expect(mockApi.cryptoWalletInit).toHaveBeenCalledWith({
        chain_type: "evm",
        chain: "ethereum",
        address: "0xabc",
        label: undefined,
      });
      expect(mockApi.cryptoWalletVerify).toHaveBeenCalledWith({
        chain_type: "evm",
        chain: "ethereum",
        address: "0xabc",
        signature: "0xsigned",
        verification_id: 9,
      });
    });
    expect(onVerified).toHaveBeenCalledWith("Wallet w1 verified");
  });

  it("shows verification error when wallet returns invalid signature", async () => {
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_accounts") return ["0xabc"];
      if (method === "eth_chainId") return "0x1";
      if (method === "personal_sign") return { bad: true };
      return null;
    });
    setEthereumProvider({
      request,
      on: vi.fn(),
      removeListener: vi.fn(),
    });

    const user = userEvent.setup();
    renderRoute();
    await screen.findByText("Connected: 0xabc");

    await user.click(screen.getByRole("button", { name: "Sign & verify" }));
    expect(await screen.findByText("Wallet did not return a valid signature.")).toBeInTheDocument();
  });

  it("says to connect first instead of a disabled Sign & verify (#319)", async () => {
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_accounts") return [];
      if (method === "eth_chainId") return "0x1";
      return null;
    });
    setEthereumProvider({
      request,
      on: vi.fn(),
      removeListener: vi.fn(),
    });

    const user = userEvent.setup();
    renderRoute();
    expect(await screen.findByText("To sign: connect the wallet first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign & verify" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Sign & verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connect your EVM wallet first.");
    expect(mockApi.cryptoWalletInit).not.toHaveBeenCalled();
  });

  it("shows Solana connection error when trying to verify without a connected wallet", async () => {
    setEthereumProvider(undefined);
    mockSolanaState.connected = true;
    mockSolanaState.publicKey = null;
    const user = userEvent.setup();
    renderRoute("solana");

    await user.click(screen.getByRole("button", { name: "Sign & verify" }));

    expect(await screen.findByText("Connect your Solana wallet first.")).toBeInTheDocument();
  });

  it("handles EVM connect/switch failures and Solana connected state UI", async () => {
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_accounts") return [];
      if (method === "eth_chainId") return 1;
      if (method === "eth_requestAccounts") return ["0xabc"];
      if (method === "wallet_switchEthereumChain") throw "switch failed";
      return null;
    });
    setEthereumProvider({
      request,
      on: vi.fn(),
      removeListener: vi.fn(),
    });

    mockSolanaState.connected = true;
    mockSolanaState.publicKey = { toString: () => "SoL123456789" };
    mockSolanaState.wallet = { adapter: { name: "ledger nano" } };

    const user = userEvent.setup();
    const { rerender } = renderRoute();
    await user.click(await screen.findByRole("button", { name: "Connect wallet" }));
    await screen.findByText("Connected: 0xabc");

    await user.selectOptions(screen.getByLabelText("Network"), "8453");
    expect(await screen.findByText("switch failed")).toBeInTheDocument();

    rerender(<WalletConnectForm chainType="solana" label="" onVerified={onVerified} />);
    expect(await screen.findByText("Connected: SoL123456789")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy address" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
  });

  it("shows EVM connect error when requestAccounts fails", async () => {
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_accounts") return [];
      if (method === "eth_chainId") return "0x1";
      if (method === "eth_requestAccounts") throw new Error("connect failed");
      return null;
    });
    setEthereumProvider({
      request,
      on: vi.fn(),
      removeListener: vi.fn(),
    });

    const user = userEvent.setup();
    renderRoute();

    await user.click(await screen.findByRole("button", { name: "Connect wallet" }));
    expect(await screen.findByText("connect failed")).toBeInTheDocument();
  });
});
