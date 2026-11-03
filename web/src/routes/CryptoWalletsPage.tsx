import SolanaWalletShell from "../wallet/SolanaWalletShell";
import CryptoWallets from "./CryptoWallets";

// Route element for /crypto: the wallet page inside its own Solana providers.
// main.tsx imports this lazily, so the wallet stack loads only with this page (#145).
export default function CryptoWalletsPage() {
  return (
    <SolanaWalletShell>
      <CryptoWallets />
    </SolanaWalletShell>
  );
}
