import { useEffect, useMemo, useState } from "react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import { useWallet } from "@solana/wallet-adapter-react";
import { Transaction, TransactionInstruction, PublicKey } from "@solana/web3.js";
import bs58 from "bs58";

import { api } from "../lib/api";
import type { CryptoWallet, CryptoAllowlistItem } from "../lib/api";
import "../App.css";
import PageShell from "../components/PageShell";

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

type Eip1193Provider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  removeListener: (event: string, listener: (...args: unknown[]) => void) => void;
};

export default function CryptoWallets() {
  const [wallets, setWallets] = useState<CryptoWallet[]>([]);
  const [allowlist, setAllowlist] = useState<CryptoAllowlistItem[]>([]);
  const [allowChain, setAllowChain] = useState<string>("ethereum");
  const [allowContract, setAllowContract] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [label, setLabel] = useState<string>("");
  const [chainType, setChainType] = useState<"evm" | "solana">("evm");
  const [useHardwareSolana, setUseHardwareSolana] = useState<boolean>(false);
  const [evmAddress, setEvmAddress] = useState<string>("");
  const [evmChainId, setEvmChainId] = useState<number>(1);
  const [connectingEvm, setConnectingEvm] = useState<boolean>(false);

  const { publicKey, connected, signMessage, signTransaction, disconnect: disconnectSolana, wallet } = useWallet();

  const evmChain = useMemo(() => EVM_CHAIN_MAP[evmChainId] || "ethereum", [evmChainId]);
  const evmConnected = evmAddress.length > 0;
  const solAddress = publicKey?.toString() ?? "";
  const walletCount = wallets.length;

  const getEthereum = (): Eip1193Provider | null => {
    const provider = (window as Window & { ethereum?: Eip1193Provider }).ethereum;
    return provider ?? null;
  };

  const loadWallets = async () => {
    const data = await api.cryptoWallets();
    setWallets(data);
  };

  const loadAllowlist = async () => {
    const data = await api.cryptoAllowlist();
    setAllowlist(data);
  };

  useEffect(() => {
    loadWallets().catch((e) => setError(e?.message ?? String(e)));
    loadAllowlist().catch((e) => setError(e?.message ?? String(e)));
  }, []);

  useEffect(() => {
    const name = wallet?.adapter?.name?.toLowerCase() ?? "";
    if (name.includes("ledger")) {
      setUseHardwareSolana(true);
    }
  }, [wallet]);

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
      setStatus("");
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
      setStatus(`Wallet ${res.wallet_id} verified`);
      setLabel("");
      await loadWallets();
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
      setStatus("");
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
        setStatus(`Wallet ${res.wallet_id} verified via on-chain memo`);
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
        setStatus(`Wallet ${res.wallet_id} verified`);
      }
      setLabel("");
      await loadWallets();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const addAllowlist = async () => {
    setError("");
    if (!allowContract) {
      setError("Contract address is required.");
      return;
    }
    try {
      const item = await api.cryptoAllowlistAdd({
        chain: allowChain,
        contract_address: allowContract,
      });
      setAllowlist((prev) => [item, ...prev.filter((p) => p.id !== item.id)]);
      setAllowContract("");
      setStatus(`Added ${item.symbol ?? item.contract_address} to allowlist`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <PageShell
      title="Crypto Wallets"
      subtitle="Connect a wallet, sign a message, and verify ownership."
      activeRoute="/crypto"
      headerActions={<span className="pill">Wallets: {walletCount}</span>}
    >
      {error && (
        <div className="card error">
          <div className="cardTitle">Error</div>
          <pre className="pre">{error}</pre>
        </div>
      )}

      {status && (
        <div className="card">
          <div className="cardTitle">Status</div>
          <div>{status}</div>
        </div>
      )}

      <div className="card">
        <div className="cardTitle">Add wallet</div>
        <div className="formGrid">
          <label className="field">
            <span className="label">Chain Type</span>
            <select
              className="input"
              aria-label="Chain Type"
              value={chainType}
              onChange={(e) => setChainType(e.target.value as "evm" | "solana")}
            >
              <option value="evm">EVM</option>
              <option value="solana">Solana</option>
            </select>
          </label>
          <label className="field">
            <span className="label">Label</span>
            <input
              className="input"
              aria-label="Label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Optional label"
            />
          </label>
          <div className="field">
            <span className="label">Wallet</span>
            {chainType === "evm" ? (
              <div style={{ marginTop: 6 }}>
                {!evmConnected ? (
                  <button
                    className="btn"
                    onClick={connectEvm}
                    disabled={connectingEvm}
                  >
                    {connectingEvm ? "Connecting..." : "Connect wallet"}
                  </button>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div className="muted">Connected: {evmAddress}</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <select
                        className="input"
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
                      {evmAddress && (
                        <button
                          className="btn"
                          onClick={() => navigator.clipboard.writeText(evmAddress)}
                        >
                          Copy address
                        </button>
                      )}
                      <button className="btn" onClick={() => setEvmAddress("")}>Disconnect</button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ marginTop: 6 }}>
                <WalletMultiButton />
                <div className="muted" style={{ marginTop: 6 }}>
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
                    <button className="btn" onClick={() => navigator.clipboard.writeText(solAddress)}>
                      Copy address
                    </button>
                    <button className="btn" onClick={() => disconnectSolana()}>Disconnect</button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="actions">
          {chainType === "evm" ? (
            <button className="btn" onClick={verifyEvm} disabled={!evmConnected}>
              Sign & verify
            </button>
          ) : (
            <button className="btn" onClick={verifySolana} disabled={!connected}>
              Sign & verify
            </button>
          )}
        </div>
        <div className="hintTag">Verification triggers ingestion</div>
      </div>

      <div className="card">
        <div className="cardTitle">Token Allowlist</div>
        <div className="muted" style={{ marginBottom: 8 }}>
          Only allowlisted ERC-20 contracts are priced and shown. We validate against CoinGecko before adding.
        </div>
        <div className="formGrid">
          <label className="field">
            <span className="label">Chain</span>
            <select
              className="input"
              value={allowChain}
              onChange={(e) => setAllowChain(e.target.value)}
            >
              <option value="ethereum">Ethereum</option>
              <option value="base">Base</option>
              <option value="arbitrum">Arbitrum</option>
              <option value="optimism">Optimism</option>
              <option value="mantle">Mantle</option>
              <option value="scroll">Scroll</option>
              <option value="solana">Solana</option>
            </select>
          </label>
          <label className="field">
            <span className="label">Contract address</span>
            <input
              className="input"
              value={allowContract}
              onChange={(e) => setAllowContract(e.target.value)}
              placeholder="0x..."
            />
          </label>
        </div>
        <div className="actions">
          <button className="btn" onClick={addAllowlist}>Add token</button>
        </div>
        <table className="table" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th>Chain</th>
              <th>Contract</th>
            </tr>
          </thead>
          <tbody>
            {allowlist.map((item) => (
              <tr key={item.id}>
                <td>{item.symbol ?? "—"}</td>
                <td>{item.name ?? "—"}</td>
                <td className="muted">{item.chain}</td>
                <td className="muted">{item.contract_address}</td>
              </tr>
            ))}
            {allowlist.length === 0 && (
              <tr>
                <td className="muted" colSpan={4}>No allowlisted tokens yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="cardTitle">Wallets</div>
        <table className="table">
          <thead>
            <tr>
              <th>Label</th>
              <th>Chain</th>
              <th>Address</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {wallets.map((w) => (
              <tr key={w.id}>
                <td>{w.label ?? "—"}</td>
                <td className="muted">{w.chain_type}:{w.chain}</td>
                <td className="muted">{w.address}</td>
                <td><span className="tag">{w.status}</span></td>
              </tr>
            ))}
            {wallets.length === 0 && (
              <tr>
                <td className="muted" colSpan={4}>No wallets added yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </PageShell>
  );
}
