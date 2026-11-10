import SolanaWalletShell from "./SolanaWalletShell";
import WalletConnectForm, { type WalletConnectFormProps } from "./WalletConnectForm";

// The "+ Add" stepper's wallet step (#319), inside its own Solana providers. AddFlow imports this
// lazily, so the wallet-adapter / @solana/web3.js stack loads only when a wallet is being added (#145).
export default function WalletConnectStep(props: WalletConnectFormProps) {
  return (
    <SolanaWalletShell>
      <WalletConnectForm {...props} />
    </SolanaWalletShell>
  );
}
