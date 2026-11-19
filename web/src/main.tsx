import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";
import InstanceBanner from "./components/InstanceBanner.tsx";
import AppShell from "./components/AppShell.tsx";
import WealthOverview from "./routes/WealthOverview.tsx";
import { ThemeProvider } from "./context/ThemeContext.tsx";
import { AuthProvider } from "./context/AuthContext.tsx";
import RequireAuth from "./components/RequireAuth.tsx";
import RedirectKeepingSearch from "./components/RedirectKeepingSearch.tsx";
import Login from "./routes/Login.tsx";
import Signup from "./routes/Signup.tsx";
import {
  AddFlow,
  Ingest,
  CryptoHoldings,
  StockHoldings,
  CashOverview,
  MarketData,
  CashFlowDetail,
  CashFlowMapping,
  Alerts,
  WealthHistory,
  WealthRisk,
  Dividends,
  Settings,
  LiabilitiesOverview,
  OperationsOverview,
  AccountsSources,
  AdminSettings,
} from "./routes/lazyRoutes.ts";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <InstanceBanner />
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
                <Route path="/wealth/history" element={<WealthHistory />} />
                <Route path="/wealth/cash-flow" element={<Navigate to="/cash-flow" replace />} />
                <Route path="/risk" element={<WealthRisk />} />
                <Route path="/income" element={<Dividends />} />
                <Route path="/dividends" element={<Navigate to="/income" replace />} />
                <Route path="/holdings" element={<StockHoldings />} />
                {/* #319: adding a wallet is a path through "+ Add". */}
                <Route path="/crypto" element={<Navigate to="/add?what=wallet" replace />} />
                <Route path="/crypto/holdings" element={<CryptoHoldings />} />
                <Route path="/cash" element={<CashOverview />} />
                <Route path="/cash-flow" element={<CashFlowDetail />} />
                <Route path="/cash-flow/income" element={<CashFlowDetail />} />
                <Route path="/cash-flow/expenses" element={<CashFlowDetail />} />
                <Route path="/cash-flow/map-transactions" element={<CashFlowMapping />} />
                <Route path="/cash-flow/mapping" element={<Navigate to="/cash-flow/map-transactions" replace />} />
                {/* #450: the page is about credit cards, so it is "Cards" at /cards. The old paths
                    (bookmarks, links in older Inbox items) redirect, query string kept. */}
                <Route path="/cards" element={<LiabilitiesOverview />} />
                <Route path="/liabilities" element={<RedirectKeepingSearch to="/cards" />} />
                <Route path="/liabilities/credit-cards" element={<RedirectKeepingSearch to="/cards" />} />
                <Route path="/credit-cards" element={<RedirectKeepingSearch to="/cards" />} />
                <Route path="/loans" element={<RedirectKeepingSearch to="/cards" />} />
                <Route path="/alerts" element={<Alerts />} />
                <Route path="/operations" element={<OperationsOverview />} />
                <Route path="/operations/sources" element={<AccountsSources />} />
                <Route path="/ingest" element={<Ingest />} />
                <Route path="/market-data" element={<MarketData />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/settings/admin" element={<AdminSettings />} />
                <Route path="/add" element={<AddFlow />} />
                {/* #319: the Add Account form became the "+ Add" stepper. */}
                <Route path="/accounts/new" element={<Navigate to="/add" replace />} />
                {/* #321: the platform directory moved to Settings → Admin. */}
                <Route path="/platforms" element={<Navigate to="/settings/admin" replace />} />
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>
);
