import type { ReactNode } from "react";
import { ConnectionProvider, WalletProvider } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import { PhantomWalletAdapter } from "@solana/wallet-adapter-phantom";
import "@solana/wallet-adapter-react-ui/styles.css";

// The Solana wallet stack (providers, Phantom adapter, modal CSS, @solana/web3.js) is
// only needed by the Crypto Wallets page. This module is reached only through the
// lazily loaded CryptoWalletsPage, so none of it is in the initial bundle (#145).
const solanaEndpoint =
  (import.meta.env.VITE_SOLANA_RPC as string) || "https://api.mainnet-beta.solana.com";
// Module level: one adapter instance for the whole session, created the first time the
// wallet page loads, so leaving and returning to the page reuses it.
const solanaWallets = [new PhantomWalletAdapter()];

export default function SolanaWalletShell({ children }: { children: ReactNode }) {
  return (
    <ConnectionProvider endpoint={solanaEndpoint}>
      <WalletProvider wallets={solanaWallets} autoConnect={true}>
        <WalletModalProvider>{children}</WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
