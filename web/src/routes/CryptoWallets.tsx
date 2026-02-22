import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount, useChainId, useDisconnect, useSignMessage } from "wagmi";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import { useWallet } from "@solana/wallet-adapter-react";
import bs58 from "bs58";

import { api } from "../lib/api";
import type { CryptoWallet, CryptoAllowlistItem } from "../lib/api";
import "../App.css";

const EVM_CHAIN_MAP: Record<number, string> = {
  1: "ethereum",
  8453: "base",
  42161: "arbitrum",
  10: "optimism",
  5000: "mantle",
  534352: "scroll",
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

  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { signMessageAsync } = useSignMessage();
  const { disconnect } = useDisconnect();
  const { publicKey, connected, signMessage, disconnect: disconnectSolana } = useWallet();

  const evmChain = useMemo(() => EVM_CHAIN_MAP[chainId] || "ethereum", [chainId]);
  const solAddress = publicKey?.toString() ?? "";
  const walletCount = wallets.length;

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

  const verifyEvm = async () => {
    if (!isConnected || !address) {
      setError("Connect your EVM wallet first.");
      return;
    }
    if (!signMessageAsync) {
      setError("Wallet does not support message signing.");
      return;
    }
    setError("");
    setStatus("");
    const init = await api.cryptoWalletInit({
      chain_type: "evm",
      chain: evmChain,
      address,
      label: label || undefined,
    });
    const signature = await signMessageAsync({ message: init.message_to_sign });
    const res = await api.cryptoWalletVerify({
      chain_type: "evm",
      chain: evmChain,
      address,
      signature,
    });
    setStatus(`Wallet ${res.wallet_id} verified`);
    setLabel("");
    await loadWallets();
  };

  const verifySolana = async () => {
    if (!connected || !publicKey || !signMessage) {
      setError("Connect your Solana wallet first.");
      return;
    }
    setError("");
    setStatus("");
    const init = await api.cryptoWalletInit({
      chain_type: "solana",
      chain: "solana",
      address: solAddress,
      label: label || undefined,
    });
    const signatureBytes = await signMessage(new TextEncoder().encode(init.message_to_sign));
    const signature = bs58.encode(signatureBytes);
    const res = await api.cryptoWalletVerify({
      chain_type: "solana",
      chain: "solana",
      address: solAddress,
      signature,
    });
    setStatus(`Wallet ${res.wallet_id} verified`);
    setLabel("");
    await loadWallets();
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
    } catch (e: any) {
      setError(e?.message ?? String(e));
    }
  };

  return (
    <div className="wrap">
      <header className="header">
        <div className="titleBlock">
          <div className="title">Crypto Wallets</div>
          <div className="subtitle">Connect a wallet, sign a message, and verify ownership.</div>
        </div>
        <div className="pillRow">
          <Link className="pill" to="/">Dashboard</Link>
          <Link className="pill" to="/ingest">Ingest</Link>
          <span className="pill">Crypto</span>
          <span className="pill">Wallets: {walletCount}</span>
        </div>
      </header>

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
                <ConnectButton.Custom>
                  {({ account, chain, openAccountModal, openChainModal, openConnectModal, mounted }) => {
                    const ready = mounted;
                    const connected = ready && account && chain;
                    if (!connected) {
                      return (
                        <button className="btn" onClick={openConnectModal}>
                          Connect wallet
                        </button>
                      );
                    }
                    return (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <div className="muted">Connected: {account.address}</div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <button className="btn" onClick={openAccountModal}>Switch wallet</button>
                          <button className="btn" onClick={openChainModal}>Switch network</button>
                          <button
                            className="btn"
                            onClick={() => navigator.clipboard.writeText(account.address)}
                          >
                            Copy address
                          </button>
                          <button className="btn" onClick={() => disconnect()}>Disconnect</button>
                        </div>
                      </div>
                    );
                  }}
                </ConnectButton.Custom>
              </div>
            ) : (
              <div style={{ marginTop: 6 }}>
                <WalletMultiButton />
                <div className="muted" style={{ marginTop: 6 }}>
                  {connected && solAddress ? `Connected: ${solAddress}` : "Not connected"}
                </div>
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
            <button className="btn" onClick={verifyEvm} disabled={!isConnected}>
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
    </div>
  );
}
