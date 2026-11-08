import { Navigate } from "react-router-dom";

import { api } from "../lib/api";
import type { DataHubSummary } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import * as fmt from "../lib/format";
import { useAuth } from "../context/useAuth";
import PageShell from "../components/PageShell";
import PlatformDirectory from "../components/PlatformDirectory";
import TokenAllowlistCard from "../components/TokenAllowlistCard";
import StatusPill from "../components/StatusPill";
import LoadError from "../components/LoadError";
import "../App.css";
import "./AdminSettings.css";

const STATE_PILL: Record<string, { tone: "good" | "warn" | "bad" | "neutral"; label: string }> = {
  ok: { tone: "good", label: "OK" },
  warning: { tone: "warn", label: "Warning" },
  failing: { tone: "bad", label: "Failing" },
  never_run: { tone: "neutral", label: "Never run" },
  not_configured: { tone: "neutral", label: "Not set up" },
};

function when(value?: string | null): string {
  if (!value) return "never";
  const label = fmt.formatDateTime(value);
  return label === fmt.MISSING ? value : label;
}

/** Background jobs (#156): last run, last success and failures, per job. */
function JobStatusSection() {
  const res = useApiResource<DataHubSummary>("dataHubSummary", () => api.dataHubSummary());
  const jobs = res.data?.job_status ?? [];
  return (
    <section aria-labelledby="admin-jobs">
      <h2 className="coSectionTitle" id="admin-jobs">Jobs</h2>
      {res.error && !res.data ? <LoadError compact title="Couldn't load job status" error={res.error.message} /> : null}
      {res.isLoading && !res.data ? <p className="card" role="status">Loading…</p> : null}
      {res.data ? (
        <ul className="adminJobs">
          {jobs.map((job) => {
            const pill = STATE_PILL[job.state] ?? { tone: "neutral" as const, label: String(job.state) };
            return (
              <li key={job.job} className="card adminJob">
                <div className="adminJobHead">
                  <strong>{job.label}</strong>
                  <StatusPill tone={pill.tone} label={pill.label} />
                </div>
                <p className="muted adminJobMeta">
                  Last run {when(job.last_run_at)} · last success {when(job.last_success_at)}
                  {job.consecutive_failures > 0 ? ` · ${job.consecutive_failures} failed in a row` : ""}
                </p>
                {job.last_error ? <p className="hint adminJobError">{job.last_error}</p> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * Settings → Admin (#321, #309): the shared-data tools that only an admin can change: the
 * platform directory, the token allowlist and background job status. Non-admins are sent
 * back to Settings; the link to this page only shows for admins.
 */
export default function AdminSettings() {
  const { user } = useAuth();
  if (user && user.is_admin !== true) return <Navigate to="/settings" replace />;
  return (
    <PageShell title="Admin" subtitle="Shared settings: platforms, tokens and background jobs.">
      <div className="adminLayout">
        <JobStatusSection />
        <PlatformDirectory />
        <TokenAllowlistCard />
      </div>
    </PageShell>
  );
}
