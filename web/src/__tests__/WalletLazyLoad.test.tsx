import { Suspense, lazy, type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// #145: the Solana wallet stack must load only with the wallet step of "+ Add" (#319).
// Each mocked Solana module records when it is evaluated, so we can tell whether
// importing the app entry pulled it in.
const { loaded, walletProviderProps } = vi.hoisted(() => ({
  loaded: new Set<string>(),
  walletProviderProps: [] as Array<{ autoConnect?: boolean; wallets?: unknown[] }>,
}));

vi.mock("react-dom/client", () => ({
  createRoot: () => ({ render: vi.fn() }),
}));

vi.mock("@solana/wallet-adapter-react", () => {
  loaded.add("@solana/wallet-adapter-react");
  return {
    ConnectionProvider: ({ children, endpoint }: { children: ReactNode; endpoint: string }) => (
      <div data-testid="solana-connection" data-endpoint={endpoint}>
        {children}
      </div>
    ),
    WalletProvider: ({
      children,
      ...props
    }: {
      children: ReactNode;
      autoConnect?: boolean;
      wallets?: unknown[];
    }) => {
      walletProviderProps.push(props);
      return <div data-testid="solana-wallet">{children}</div>;
    },
    useWallet: () => ({}),
  };
});

vi.mock("@solana/wallet-adapter-react-ui", () => {
  loaded.add("@solana/wallet-adapter-react-ui");
  return {
    WalletModalProvider: ({ children }: { children: ReactNode }) => (
      <div data-testid="solana-modal">{children}</div>
    ),
  };
});

vi.mock("@solana/wallet-adapter-phantom", () => {
  loaded.add("@solana/wallet-adapter-phantom");
  return { PhantomWalletAdapter: class MockPhantomWalletAdapter {} };
});

vi.mock("@solana/web3.js", () => {
  loaded.add("@solana/web3.js");
  return {};
});

vi.mock("@solana/wallet-adapter-react-ui/styles.css", () => {
  loaded.add("wallet-adapter-styles");
  return {};
});

vi.mock("../wallet/WalletConnectForm.tsx", () => ({ default: () => <p>wallet page body</p> }));

describe("Solana wallet stack is lazy (#145)", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="root"></div>';
  });

  it("importing the app entry does not load any Solana module", async () => {
    await import("../main.tsx");
    expect([...loaded]).toEqual([]);
  });

  it("importing the + Add route does not load any Solana module", async () => {
    await import("../routes/AddFlow.tsx");
    expect([...loaded]).toEqual([]);
  });

  it("the wallet step loads the wallet shell with Phantom and autoConnect", async () => {
    const WalletConnectStep = lazy(() => import("../wallet/WalletConnectStep.tsx"));
    render(
      <Suspense fallback={<p>loading route</p>}>
        <WalletConnectStep chainType="evm" label="" onVerified={() => undefined} />
      </Suspense>,
    );

    expect(await screen.findByText("wallet page body")).toBeInTheDocument();
    // Page renders inside all three providers.
    const modal = screen.getByTestId("solana-modal");
    expect(screen.getByTestId("solana-wallet")).toContainElement(modal);
    expect(screen.getByTestId("solana-connection")).toContainElement(modal);
    expect(modal).toHaveTextContent("wallet page body");
    expect(screen.getByTestId("solana-connection").dataset.endpoint).toMatch(/^https?:\/\//);

    expect(loaded).toContain("@solana/wallet-adapter-react");
    expect(loaded).toContain("@solana/wallet-adapter-phantom");
    expect(loaded).toContain("wallet-adapter-styles");
    const props = walletProviderProps.at(-1)!;
    expect(props.autoConnect).toBe(true);
    expect(props.wallets).toHaveLength(1);
    expect(props.wallets![0]!.constructor.name).toBe("MockPhantomWalletAdapter");
  });
});
