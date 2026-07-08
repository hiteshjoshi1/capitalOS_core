import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConnectionProvider, WalletProvider } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import { PhantomWalletAdapter } from "@solana/wallet-adapter-phantom";
import "./index.css";
import "@solana/wallet-adapter-react-ui/styles.css";
import App from "./App.tsx";
import AppShell from "./components/AppShell.tsx";
import AddAccount from "./routes/AddAccount.tsx";
import Ingest from "./routes/Ingest.tsx";
import CryptoWallets from "./routes/CryptoWallets.tsx";
import CryptoHoldings from "./routes/CryptoHoldings.tsx";
import StockHoldings from "./routes/StockHoldings.tsx";
import CashOverview from "./routes/CashOverview.tsx";
import MarketData from "./routes/MarketData.tsx";
import CashFlowDetail from "./routes/CashFlowDetail.tsx";
import CashFlowMapping from "./routes/CashFlowMapping.tsx";
import Alerts from "./routes/Alerts.tsx";
import WealthOverview from "./routes/WealthOverview.tsx";
import WealthRisk from "./routes/WealthRisk.tsx";
import Dividends from "./routes/Dividends.tsx";
import Companies from "./routes/Companies.tsx";
import AISage from "./routes/AISage.tsx";
import AuthorLibrary from "./routes/AuthorLibrary.tsx";
import AuthorIngestion from "./routes/AuthorIngestion.tsx";
import Settings from "./routes/Settings.tsx";
import Platforms from "./routes/Platforms.tsx";
import LiabilitiesOverview from "./routes/LiabilitiesOverview.tsx";
import OperationsOverview from "./routes/OperationsOverview.tsx";
import IntelligenceOverview from "./routes/IntelligenceOverview.tsx";
import { ThemeProvider } from "./context/ThemeContext.tsx";
import { AuthProvider } from "./context/AuthContext.tsx";
import RequireAuth from "./components/RequireAuth.tsx";
import Login from "./routes/Login.tsx";
import Signup from "./routes/Signup.tsx";

const solanaEndpoint = (import.meta.env.VITE_SOLANA_RPC as string) || "https://api.mainnet-beta.solana.com";
const solanaWallets = [new PhantomWalletAdapter()];

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConnectionProvider endpoint={solanaEndpoint}>
      <WalletProvider wallets={solanaWallets} autoConnect={true}>
        <WalletModalProvider>
          <ThemeProvider>
            <AuthProvider>
              <BrowserRouter>
                <Routes>
                  <Route path="/login" element={<Login />} />
                  <Route path="/signup" element={<Signup />} />

                  <Route element={<RequireAuth />}>
                    <Route element={<AppShell />}>
                      <Route path="/" element={<App />} />
                      <Route path="/wealth" element={<WealthOverview />} />
                      <Route path="/wealth/cash-flow" element={<Navigate to="/cash-flow" replace />} />
                      <Route path="/risk" element={<WealthRisk />} />
                      <Route path="/dividends" element={<Dividends />} />
                      <Route path="/holdings" element={<StockHoldings />} />
                      <Route path="/crypto" element={<CryptoWallets />} />
                      <Route path="/crypto/holdings" element={<CryptoHoldings />} />
                      <Route path="/cash" element={<CashOverview />} />
                      <Route path="/cash-flow" element={<CashFlowDetail />} />
                      <Route path="/cash-flow/income" element={<CashFlowDetail />} />
                      <Route path="/cash-flow/expenses" element={<CashFlowDetail />} />
                      <Route path="/cash-flow/map-transactions" element={<CashFlowMapping />} />
                      <Route path="/cash-flow/mapping" element={<Navigate to="/cash-flow/map-transactions" replace />} />
                      <Route path="/liabilities" element={<LiabilitiesOverview />} />
                      <Route path="/credit-cards" element={<Navigate to="/liabilities" replace />} />
                      <Route path="/loans" element={<Navigate to="/liabilities" replace />} />
                      <Route path="/intelligence" element={<IntelligenceOverview />} />
                      <Route path="/companies" element={<Companies />} />
                      <Route path="/alerts" element={<Alerts />} />
                      <Route path="/ai-sage" element={<AISage />} />
                      <Route path="/ai-sage/chats/:chatId" element={<AISage />} />
                      <Route path="/author-library" element={<AuthorLibrary />} />
                      <Route path="/author-library/:authorId" element={<AuthorLibrary />} />
                      <Route path="/author-library/:authorId/documents/:documentId" element={<AuthorLibrary />} />
                      <Route path="/operations" element={<OperationsOverview />} />
                      <Route path="/author-ingestion" element={<AuthorIngestion />} />
                      <Route path="/ingest" element={<Ingest />} />
                      <Route path="/market-data" element={<MarketData />} />
                      <Route path="/settings" element={<Settings />} />
                      <Route path="/accounts/new" element={<AddAccount />} />
                      <Route path="/platforms" element={<Platforms />} />
                    </Route>
                  </Route>
                </Routes>
              </BrowserRouter>
            </AuthProvider>
          </ThemeProvider>
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  </StrictMode>
);
