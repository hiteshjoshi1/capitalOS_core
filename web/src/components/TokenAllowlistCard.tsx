import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { CryptoAllowlistItem } from "../lib/api";
import DirectoryListRow from "./DirectoryListRow";

/** The ERC-20 token allowlist (#321): moved from the wallets page to Settings → Admin.
 * Adding a token is a shared-data write (admin only, #152). */
export default function TokenAllowlistCard() {
  const [allowlist, setAllowlist] = useState<CryptoAllowlistItem[]>([]);
  const [chain, setChain] = useState("ethereum");
  const [contract, setContract] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .cryptoAllowlist()
      .then((data) => {
        if (!cancelled) setAllowlist(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const add = async () => {
    setError("");
    setStatus("");
    if (!contract) {
      setError("Contract address is required.");
      return;
    }
    try {
      const item = await api.cryptoAllowlistAdd({ chain, contract_address: contract });
      setAllowlist((prev) => [item, ...prev.filter((p) => p.id !== item.id)]);
      setContract("");
      setStatus(`Added ${item.symbol ?? item.contract_address} to allowlist`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section aria-labelledby="admin-allowlist">
      <h2 className="coSectionTitle" id="admin-allowlist">Token allowlist</h2>
      <div className="card">
        <p className="muted">
          Only allowlisted ERC-20 contracts are priced and shown. They're checked against CoinGecko before adding.
        </p>
        <div className="formGrid">
          <label className="field">
            <span className="label">Chain</span>
            <select className="input" value={chain} onChange={(e) => setChain(e.target.value)}>
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
            <input className="input" value={contract} onChange={(e) => setContract(e.target.value)} placeholder="0x..." />
          </label>
        </div>
        <div className="actions">
          <button className="btn" type="button" onClick={() => void add()}>
            Add token
          </button>
        </div>
        {error ? (
          <p className="hint" role="alert">
            {error}
          </p>
        ) : null}
        {status ? <p className="muted" role="status">{status}</p> : null}
        <div className="adminAllowlistRows">
          {allowlist.length === 0 ? (
            <p className="muted">No allowlisted tokens yet.</p>
          ) : (
            allowlist.map((item) => (
              <DirectoryListRow
                key={item.id}
                title={item.symbol ?? "—"}
                meta={item.name ?? "—"}
                right={<span className="tag">{item.chain}</span>}
              />
            ))
          )}
        </div>
      </div>
    </section>
  );
}
