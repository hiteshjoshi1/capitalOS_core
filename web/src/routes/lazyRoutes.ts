import { lazy } from "react";

// The landing page (/wealth, where / and login redirect) and the auth pages load eagerly;
// every other route is its own chunk, fetched on first visit. AppShell wraps its Outlet in
// Suspense, so the shell stays on screen while a chunk loads (#145).
// The Crypto Wallets page brings its own Solana providers (CryptoWalletsPage), so the
// wallet-adapter / @solana/web3.js stack loads only with that page.
export const CryptoWalletsPage = lazy(() => import("./CryptoWalletsPage.tsx"));
export const AddAccount = lazy(() => import("./AddAccount.tsx"));
export const Ingest = lazy(() => import("./Ingest.tsx"));
export const CryptoHoldings = lazy(() => import("./CryptoHoldings.tsx"));
export const StockHoldings = lazy(() => import("./StockHoldings.tsx"));
export const CashOverview = lazy(() => import("./CashOverview.tsx"));
export const MarketData = lazy(() => import("./MarketData.tsx"));
export const CashFlowDetail = lazy(() => import("./CashFlowDetail.tsx"));
export const CashFlowMapping = lazy(() => import("./CashFlowMapping.tsx"));
export const Alerts = lazy(() => import("./Alerts.tsx"));
export const WealthHistory = lazy(() => import("./WealthHistory.tsx"));
export const WealthRisk = lazy(() => import("./WealthRisk.tsx"));
export const Dividends = lazy(() => import("./Dividends.tsx"));
export const Settings = lazy(() => import("./Settings.tsx"));
export const Platforms = lazy(() => import("./Platforms.tsx"));
export const LiabilitiesOverview = lazy(() => import("./LiabilitiesOverview.tsx"));
export const OperationsOverview = lazy(() => import("./OperationsOverview.tsx"));
export const AccountsSources = lazy(() => import("./AccountsSources.tsx"));
