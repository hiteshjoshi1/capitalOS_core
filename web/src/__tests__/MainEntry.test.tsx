import { beforeEach, describe, expect, it, vi } from "vitest";

const { createRootSpy, renderSpy } = vi.hoisted(() => {
  const renderSpyLocal = vi.fn();
  return {
    createRootSpy: vi.fn(() => ({ render: renderSpyLocal })),
    renderSpy: renderSpyLocal,
  };
});

vi.mock("react-dom/client", () => ({
  createRoot: createRootSpy,
}));

vi.mock("@solana/wallet-adapter-react", () => ({
  ConnectionProvider: ({ children }: { children: React.ReactNode }) => children,
  WalletProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@solana/wallet-adapter-react-ui", () => ({
  WalletModalProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@solana/wallet-adapter-phantom", () => ({
  PhantomWalletAdapter: class MockPhantomWalletAdapter {},
}));

vi.mock("../App.tsx", () => ({ default: () => null }));
vi.mock("../components/AppShell.tsx", () => ({ default: () => null }));
vi.mock("../routes/AddAccount.tsx", () => ({ default: () => null }));
vi.mock("../routes/Ingest.tsx", () => ({ default: () => null }));
vi.mock("../routes/CryptoWallets.tsx", () => ({ default: () => null }));
vi.mock("../routes/CryptoHoldings.tsx", () => ({ default: () => null }));
vi.mock("../routes/StockHoldings.tsx", () => ({ default: () => null }));
vi.mock("../routes/CashOverview.tsx", () => ({ default: () => null }));
vi.mock("../routes/MarketData.tsx", () => ({ default: () => null }));
vi.mock("../routes/CreditCards.tsx", () => ({ default: () => null }));
vi.mock("../routes/CashFlowDetail.tsx", () => ({ default: () => null }));
vi.mock("../routes/CashFlowMapping.tsx", () => ({ default: () => null }));
vi.mock("../routes/Alerts.tsx", () => ({ default: () => null }));
vi.mock("../routes/WealthOverview.tsx", () => ({ default: () => null }));
vi.mock("../routes/Dividends.tsx", () => ({ default: () => null }));
vi.mock("../routes/Loans.tsx", () => ({ default: () => null }));
vi.mock("../routes/Companies.tsx", () => ({ default: () => null }));
vi.mock("../routes/AIGuru.tsx", () => ({ default: () => null }));
vi.mock("../routes/Settings.tsx", () => ({ default: () => null }));
vi.mock("../routes/Platforms.tsx", () => ({ default: () => null }));
vi.mock("../context/ThemeContext.tsx", () => ({ ThemeProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../context/AuthContext.tsx", () => ({ AuthProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../components/RequireAuth.tsx", () => ({ default: () => null }));
vi.mock("../routes/Login.tsx", () => ({ default: () => null }));
vi.mock("../routes/Signup.tsx", () => ({ default: () => null }));

describe("main entry", () => {
  beforeEach(() => {
    vi.resetModules();
    createRootSpy.mockClear();
    renderSpy.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
  });

  it("creates root and renders app tree", async () => {
    await import("../main.tsx");
    expect(createRootSpy).toHaveBeenCalledTimes(1);
    expect(renderSpy).toHaveBeenCalledTimes(1);
  });
});

