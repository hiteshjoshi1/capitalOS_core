import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { WagmiProvider, createConfig, http } from "wagmi";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RainbowKitProvider, getDefaultConfig } from "@rainbow-me/rainbowkit";
import { mainnet, base, arbitrum, optimism, mantle, scroll } from "wagmi/chains";
import { injected } from "wagmi/connectors";
import { ConnectionProvider, WalletProvider } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import { PhantomWalletAdapter } from "@solana/wallet-adapter-wallets";
import "./index.css";
import "@rainbow-me/rainbowkit/styles.css";
import "@solana/wallet-adapter-react-ui/styles.css";
import App from "./App.tsx";
import AddAccount from "./routes/AddAccount.tsx";
import Ingest from "./routes/Ingest.tsx";
import CryptoWallets from "./routes/CryptoWallets.tsx";
import CryptoHoldings from "./routes/CryptoHoldings.tsx";
import StockHoldings from "./routes/StockHoldings.tsx";
import CashOverview from "./routes/CashOverview.tsx";
import MarketData from "./routes/MarketData.tsx";

const projectId = import.meta.env.VITE_WALLETCONNECT_PROJECT_ID as string | undefined;
const chains = [mainnet, base, arbitrum, optimism, mantle, scroll] as const;
let wagmiConfig;
if (projectId) {
  wagmiConfig = getDefaultConfig({
    appName: "CapitalOS",
    projectId,
    chains,
    ssr: false,
  });
} else {
  console.warn("VITE_WALLETCONNECT_PROJECT_ID is not set. Falling back to injected wallets only.");
  wagmiConfig = createConfig({
    chains,
    connectors: [injected()],
    transports: {
      [mainnet.id]: http(),
      [base.id]: http(),
      [arbitrum.id]: http(),
      [optimism.id]: http(),
      [mantle.id]: http(),
      [scroll.id]: http(),
    },
  });
}
const queryClient = new QueryClient();
const solanaEndpoint = (import.meta.env.VITE_SOLANA_RPC as string) || "https://api.mainnet-beta.solana.com";
const solanaWallets = [new PhantomWalletAdapter()];

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConnectionProvider endpoint={solanaEndpoint}>
      <WalletProvider wallets={solanaWallets} autoConnect={true}>
        <WalletModalProvider>
          <WagmiProvider config={wagmiConfig}>
            <QueryClientProvider client={queryClient}>
              <RainbowKitProvider>
                <BrowserRouter>
                  <Routes>
                    <Route path="/" element={<App />} />
                    <Route path="/accounts/new" element={<AddAccount />} />
                    <Route path="/ingest" element={<Ingest />} />
                    <Route path="/crypto" element={<CryptoWallets />} />
                    <Route path="/crypto/holdings" element={<CryptoHoldings />} />
                    <Route path="/holdings" element={<StockHoldings />} />
                    <Route path="/cash" element={<CashOverview />} />
                    <Route path="/market-data" element={<MarketData />} />
                  </Routes>
                </BrowserRouter>
              </RainbowKitProvider>
            </QueryClientProvider>
          </WagmiProvider>
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  </StrictMode>
);
