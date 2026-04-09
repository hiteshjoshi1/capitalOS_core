import { useState } from "react";
import "../App.css";
import PageShell from "../components/PageShell";

interface Author {
  author_id: string;
  name: string;
  score: number;
  domains: string[];
  expertise_tags: string[];
  match_reason: string[];
  worldview?: string;
  key_maxims?: string[];
  favored_decision_variables?: string[];
}

interface EvidenceChunk {
  chunk_id: string;
  author_id: string;
  author_name: string;
  text: string;
  similarity: number;
  metadata: Record<string, unknown>;
}

interface QueryResult {
  query: string;
  mode: string;
  selected_authors: Author[];
  evidence_chunks: EvidenceChunk[];
  answer: string | null;
  missing_information: string | null;
  evidence_sufficient: boolean;
}

interface CompanyContextResult {
  company: string;
  question: string;
  relevant_author_lenses: Author[];
  evidence_pack: EvidenceChunk[];
  evidence_sufficient: boolean;
}

type Mode = "retrieve" | "ask" | "company_context";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export default function AISage() {
  const [mode, setMode] = useState<Mode>("ask");
  const [query, setQuery] = useState("");
  const [authorFilter, setAuthorFilter] = useState("");
  const [company, setCompany] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [companyResult, setCompanyResult] = useState<CompanyContextResult | null>(null);

  const handleSubmit = async () => {
    setError(null);
    setQueryResult(null);
    setCompanyResult(null);
    setLoading(true);

    try {
      if (mode === "company_context") {
        const result = await postJSON<CompanyContextResult>("/rag/analyze/company-context", {
          company: company || query,
          question: query,
          top_k: 8,
        });
        setCompanyResult(result);
      } else if (mode === "ask") {
        const result = await postJSON<QueryResult>("/rag/query", {
          query,
          top_k: 8,
          author_id: authorFilter || undefined,
        });
        setQueryResult(result);
      } else {
        const result = await postJSON<QueryResult>("/rag/retrieve", {
          query,
          top_k: 5,
          author_id: authorFilter || undefined,
        });
        setQueryResult(result);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const selectedAuthors =
    queryResult?.selected_authors ?? companyResult?.relevant_author_lenses ?? [];
  const evidenceChunks =
    queryResult?.evidence_chunks ?? companyResult?.evidence_pack ?? [];

  return (
    <PageShell title="AI Sage" subtitle="Decision intelligence powered by thinker corpus">
      <div className="wrap">
        {/* Controls */}
        <div className="card" style={{ marginBottom: "1rem" }}>
          <div className="cardTitle">Query</div>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
            {(["ask", "retrieve", "company_context"] as Mode[]).map((m) => (
              <button
                key={m}
                className={mode === m ? "btn btn-primary" : "btn btn-secondary"}
                onClick={() => setMode(m)}
              >
                {m === "ask" ? "Ask" : m === "retrieve" ? "Retrieve" : "Company Context"}
              </button>
            ))}
          </div>

          {mode === "company_context" && (
            <input
              className="formInput"
              placeholder="Company name (e.g. Amazon)"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              style={{ marginBottom: "0.5rem", width: "100%" }}
            />
          )}

          <textarea
            className="formInput"
            rows={3}
            placeholder={
              mode === "company_context"
                ? "What question should we explore for this company?"
                : "Enter your query..."
            }
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: "100%", marginBottom: "0.5rem", resize: "vertical" }}
          />

          <input
            className="formInput"
            placeholder="Author filter (optional, e.g. warren_buffett)"
            value={authorFilter}
            onChange={(e) => setAuthorFilter(e.target.value)}
            style={{ width: "100%", marginBottom: "0.75rem" }}
          />

          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={loading || !query.trim()}
          >
            {loading ? "Running..." : "Submit"}
          </button>

          {error && <p className="muted" style={{ color: "var(--color-danger, red)", marginTop: "0.5rem" }}>{error}</p>}
        </div>

        {/* Selected Authors */}
        {selectedAuthors.length > 0 && (
          <div className="card" style={{ marginBottom: "1rem" }}>
            <div className="cardTitle">Selected Authors</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
              {selectedAuthors.map((a) => (
                <div key={a.author_id} style={{ border: "1px solid var(--color-border, #ccc)", borderRadius: "6px", padding: "0.75rem", minWidth: "200px", maxWidth: "300px" }}>
                  <strong>{a.name}</strong>
                  <div className="muted" style={{ fontSize: "0.8rem" }}>Score: {a.score}</div>
                  {a.worldview && (
                    <p style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}>{a.worldview}</p>
                  )}
                  {a.key_maxims && a.key_maxims.length > 0 && (
                    <div style={{ marginTop: "0.4rem" }}>
                      <span className="muted" style={{ fontSize: "0.75rem" }}>Key maxims:</span>
                      <ul style={{ margin: "0.2rem 0 0 1rem", padding: 0, fontSize: "0.75rem" }}>
                        {a.key_maxims.slice(0, 3).map((m, i) => <li key={i}>{m}</li>)}
                      </ul>
                    </div>
                  )}
                  {a.match_reason && a.match_reason.length > 0 && (
                    <div className="muted" style={{ fontSize: "0.7rem", marginTop: "0.3rem" }}>
                      {a.match_reason.join(" | ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Answer / Summary */}
        {queryResult?.answer && (
          <div className="card" style={{ marginBottom: "1rem" }}>
            <div className="cardTitle">
              {queryResult.mode === "ask" ? "Grounded Answer" : "Evidence Summary"}
            </div>
            <p style={{ whiteSpace: "pre-wrap" }}>{queryResult.answer}</p>
            {queryResult.missing_information && (
              <p className="muted" style={{ marginTop: "0.5rem", fontStyle: "italic" }}>
                Note: {queryResult.missing_information}
              </p>
            )}
          </div>
        )}

        {queryResult?.missing_information && !queryResult.answer && (
          <div className="card" style={{ marginBottom: "1rem" }}>
            <p className="muted">{queryResult.missing_information}</p>
          </div>
        )}

        {/* Evidence Chunks */}
        {evidenceChunks.length > 0 && (
          <div className="card">
            <div className="cardTitle">Evidence Chunks ({evidenceChunks.length})</div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {evidenceChunks.map((chunk, i) => (
                <div key={chunk.chunk_id} style={{ borderLeft: "3px solid var(--color-accent, #4a90e2)", paddingLeft: "0.75rem" }}>
                  <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem", flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>{chunk.author_name}</span>
                    <span className="muted" style={{ fontSize: "0.75rem" }}>sim: {(chunk.similarity * 100).toFixed(1)}%</span>
                    <span className="muted" style={{ fontSize: "0.7rem" }}>#{i + 1}</span>
                  </div>
                  <p style={{ fontSize: "0.85rem", margin: 0, lineHeight: 1.5 }}>
                    {chunk.text.length > 400 ? chunk.text.slice(0, 400) + "..." : chunk.text}
                  </p>
                  {chunk.metadata && Object.keys(chunk.metadata).length > 0 && (
                    <div className="muted" style={{ fontSize: "0.7rem", marginTop: "0.25rem" }}>
                      {chunk.metadata.title ? `"${String(chunk.metadata.title)}"` : ""}
                      {chunk.metadata.published_at ? ` · ${String(chunk.metadata.published_at)}` : ""}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* No results state */}
        {!loading && !error && (queryResult || companyResult) && evidenceChunks.length === 0 && (
          <div className="card placeholderCard">
            <p className="muted">No corpus evidence found for this query. Try ingesting more documents first.</p>
          </div>
        )}
      </div>
    </PageShell>
  );
}
