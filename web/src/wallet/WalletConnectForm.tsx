import { useEffect, useMemo, useState } from "react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import { useWallet } from "@solana/wallet-adapter-react";
import { Transaction, TransactionInstruction, PublicKey } from "@solana/web3.js";
import bs58 from "bs58";

import { api } from "../lib/api";
import "../App.css";

// The connect-and-sign part of adding a self-custody wallet (#319: the "+ Add" stepper's last step;
// it was the Add Crypto Wallets page). The stepper picks the chain and label; this connects the
// wallet, has it sign the server's challenge, and verifies it, which starts its first sync.
// Rendered only inside SolanaWalletShell (WalletConnectStep), so the Solana stack stays lazy (#145).

const EVM_CHAIN_MAP: Record<number, string> = {
  1: "ethereum",
  8453: "base",
  42161: "arbitrum",
  10: "optimism",
  5000: "mantle",
  534352: "scroll",
};

const EVM_CHAINS = [
  { id: 1, name: "Ethereum" },
  { id: 8453, name: "Base" },
  { id: 42161, name: "Arbitrum" },
  { id: 10, name: "Optimism" },
  { id: 5000, name: "Mantle" },
  { id: 534352, name: "Scroll" },
] as const;

function isLedgerWallet(wallet: { adapter?: { name?: string } } | null | undefined): boolean {
  return (wallet?.adapter?.name?.toLowerCase() ?? "").includes("ledger");
}

type Eip1193Provider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  removeListener: (event: string, listener: (...args: unknown[]) => void) => void;
};

export type WalletConnectFormProps = {
  chainType: "evm" | "solana";
  /** Optional name for the wallet; sent with the challenge. */
  label: string;
  /** Called once the server has verified the signature (the message names the wallet). */
  onVerified: (message: string) => void;
};

export default function WalletConnectForm({ chainType, label, onVerified }: WalletConnectFormProps) {
  const [error, setError] = useState<string>("");
  const [evmAddress, setEvmAddress] = useState<string>("");
  const [evmChainId, setEvmChainId] = useState<number>(1);
  const [connectingEvm, setConnectingEvm] = useState<boolean>(false);

  const { publicKey, connected, signMessage, signTransaction, disconnect: disconnectSolana, wallet } = useWallet();

  // Selecting a Ledger adapter ticks the hardware-wallet box; the user can still untick it. Adjusted while
  // rendering when `wallet` changes (not in an effect), so the box is already right on the first paint.
  const [useHardwareSolana, setUseHardwareSolana] = useState<boolean>(() => isLedgerWallet(wallet));
  const [prevWallet, setPrevWallet] = useState(wallet);
  if (wallet !== prevWallet) {
    setPrevWallet(wallet);
    if (isLedgerWallet(wallet)) {
      setUseHardwareSolana(true);
    }
  }

  const evmChain = useMemo(() => EVM_CHAIN_MAP[evmChainId] || "ethereum", [evmChainId]);
  const evmConnected = evmAddress.length > 0;
  const solAddress = publicKey?.toString() ?? "";

  const getEthereum = (): Eip1193Provider | null => {
    const provider = (window as Window & { ethereum?: Eip1193Provider }).ethereum;
    return provider ?? null;
  };

  useEffect(() => {
    const provider = getEthereum();
    if (!provider) return;

    let cancelled = false;

    const loadEvmState = async () => {
      try {
        const [accountsResult, chainResult] = await Promise.all([
          provider.request({ method: "eth_accounts" }),
          provider.request({ method: "eth_chainId" }),
        ]);
        if (cancelled) return;
        const accounts = Array.isArray(accountsResult) ? (accountsResult as string[]) : [];
        const chainHex = typeof chainResult === "string" ? chainResult : "0x1";
        setEvmAddress(accounts[0] ?? "");
        setEvmChainId(parseInt(chainHex, 16));
      } catch {
        if (!cancelled) {
          setEvmAddress("");
          setEvmChainId(1);
        }
      }
    };

    const handleAccountsChanged = (accounts: unknown) => {
      if (Array.isArray(accounts)) {
        setEvmAddress(typeof accounts[0] === "string" ? accounts[0] : "");
      } else {
        setEvmAddress("");
      }
    };

    const handleChainChanged = (chainHex: unknown) => {
      if (typeof chainHex === "string") {
        setEvmChainId(parseInt(chainHex, 16));
      }
    };

    void loadEvmState();
    provider.on("accountsChanged", handleAccountsChanged);
    provider.on("chainChanged", handleChainChanged);

    return () => {
      cancelled = true;
      provider.removeListener("accountsChanged", handleAccountsChanged);
      provider.removeListener("chainChanged", handleChainChanged);
    };
  }, []);

  const connectEvm = async () => {
    const provider = getEthereum();
    if (!provider) {
      setError("No EVM wallet detected. Install MetaMask or a compatible extension.");
      return;
    }
    try {
      setError("");
      setConnectingEvm(true);
      const accounts = await provider.request({ method: "eth_requestAccounts" });
      if (Array.isArray(accounts) && typeof accounts[0] === "string") {
        setEvmAddress(accounts[0]);
      }
      const chainHex = await provider.request({ method: "eth_chainId" });
      if (typeof chainHex === "string") {
        setEvmChainId(parseInt(chainHex, 16));
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setConnectingEvm(false);
    }
  };

  const switchEvmChain = async (targetChainId: number) => {
    const provider = getEthereum();
    if (!provider) return;
    try {
      await provider.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: `0x${targetChainId.toString(16)}` }],
      });
      setEvmChainId(targetChainId);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const verifyEvm = async () => {
    const provider = getEthereum();
    if (!provider || !evmConnected) {
      setError("Connect your EVM wallet first.");
      return;
    }
    try {
      setError("");
      const init = await api.cryptoWalletInit({
        chain_type: "evm",
        chain: evmChain,
        address: evmAddress,
        label: label || undefined,
      });
      const signatureResult = await provider.request({
        method: "personal_sign",
        params: [init.message_to_sign, evmAddress],
      });
      if (typeof signatureResult !== "string") {
        throw new Error("Wallet did not return a valid signature.");
      }
      const res = await api.cryptoWalletVerify({
        chain_type: "evm",
        chain: evmChain,
        address: evmAddress,
        signature: signatureResult,
        verification_id: init.verification_id,
      });
      onVerified(`Wallet ${res.wallet_id} verified`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const verifySolana = async () => {
    if (!connected || !publicKey || (!signMessage && !useHardwareSolana)) {
      setError("Connect your Solana wallet first.");
      return;
    }
    try {
      setError("");
      const init = await api.cryptoWalletInit({
        chain_type: "solana",
        chain: "solana",
        address: solAddress,
        label: label || undefined,
      });
      console.log("solana_message_hash", init.message_hash);
      console.log("solana_message_to_sign", init.message_to_sign);
      console.log("solana_message_bytes_b64", init.message_bytes_b64);
      if (useHardwareSolana) {
        if (!signTransaction) {
          throw new Error("Wallet does not support signing transactions.");
        }
        const memoProgram = new PublicKey("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr");
        const memoIx = new TransactionInstruction({
          programId: memoProgram,
          keys: [],
          data: new TextEncoder().encode(`CapitalOS verify nonce: ${init.nonce}`) as unknown as Buffer,
        });
        const tx = new Transaction().add(memoIx);
        tx.feePayer = publicKey;
        const blockhash = await api.solanaBlockhash();
        tx.recentBlockhash = blockhash.blockhash;
        const signed = await signTransaction(tx);
        const raw = signed.serialize();
        const rawB64 = btoa(String.fromCharCode(...raw));
        await api.solanaPreflight({ tx_b64: rawB64 });
        const sig = await api.solanaSubmit({ tx_b64: rawB64 });
        const res = await api.cryptoWalletVerifyOnchain({
          address: solAddress,
          signature: sig.signature,
          verification_id: init.verification_id ?? 0,
        });
        onVerified(`Wallet ${res.wallet_id} verified via on-chain memo`);
      } else {
        const messageBytes = init.message_bytes_b64
          ? Uint8Array.from(atob(init.message_bytes_b64), (c) => c.charCodeAt(0))
          : new TextEncoder().encode(init.message_to_sign);
        const signatureBytes = await signMessage!(messageBytes);
        const sigHex = Array.from(signatureBytes ?? []).slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
        console.log("solana_signature_bytes_len", signatureBytes?.length ?? 0, "hex_prefix", sigHex);
        if (!signatureBytes || signatureBytes.length !== 64) {
          throw new Error(`Invalid signature bytes length: ${signatureBytes?.length ?? 0}`);
        }
        const signature = bs58.encode(signatureBytes);
        console.log("solana_signature_b58", signature, "len", signature.length);
        const res = await api.cryptoWalletVerify({
          chain_type: "solana",
          chain: "solana",
          address: solAddress,
          signature,
          verification_id: init.verification_id,
        });
        onVerified(`Wallet ${res.wallet_id} verified`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="formGrid">
      <div className="field">
        <span className="label">Wallet</span>
        {chainType === "evm" ? (
          <div style={{ marginTop: 6 }}>
            {!evmConnected ? (
              <button className="btn" type="button" onClick={connectEvm} disabled={connectingEvm}>
                {connectingEvm ? "Connecting..." : "Connect wallet"}
              </button>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div className="muted addFlowBreak">Connected: {evmAddress}</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <select
                    className="input"
                    aria-label="Network"
                    value={evmChainId}
                    onChange={(e) => void switchEvmChain(Number(e.target.value))}
                    style={{ maxWidth: 220 }}
                  >
                    {EVM_CHAINS.map((chain) => (
                      <option key={chain.id} value={chain.id}>
                        {chain.name}
                      </option>
                    ))}
                  </select>
                  <button className="btn" type="button" onClick={() => navigator.clipboard.writeText(evmAddress)}>
                    Copy address
                  </button>
                  <button className="btn" type="button" onClick={() => setEvmAddress("")}>
                    Disconnect
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div style={{ marginTop: 6 }}>
            <WalletMultiButton />
            <div className="muted addFlowBreak" style={{ marginTop: 6 }}>
              {connected && solAddress ? `Connected: ${solAddress}` : "Not connected"}
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
              <input
                type="checkbox"
                checked={useHardwareSolana}
                onChange={(e) => setUseHardwareSolana(e.target.checked)}
              />
              <span>Using Ledger / hardware wallet (verify via on-chain memo)</span>
            </label>
            {connected && solAddress && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
                <button className="btn" type="button" onClick={() => navigator.clipboard.writeText(solAddress)}>
                  Copy address
                </button>
                <button className="btn" type="button" onClick={() => disconnectSolana()}>
                  Disconnect
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="actions">
        <button
          className="btn btnPrimary"
          type="button"
          onClick={chainType === "evm" ? verifyEvm : verifySolana}
        >
          Sign &amp; verify
        </button>
      </div>
      {/* #319: say what's missing instead of a disabled button. */}
      {!error && !(chainType === "evm" ? evmConnected : connected) && (
        <p className="hint" role="note">
          To sign: connect the wallet first.
        </p>
      )}
      {error && (
        <p className="hint addFlowError" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
