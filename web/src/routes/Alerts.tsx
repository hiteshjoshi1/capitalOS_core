import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "../App.css";
import "./Alerts.css";
import "./OperationsInbox.css";
import PageShell from "../components/PageShell";
import LoadError from "../components/LoadError";
import { INBOX_SEVERITY_LABEL, inboxItemRoute } from "../lib/inbox";

/**
 * Alerts (#317): the Data Hub inbox (#316), the same list and count as the header bell,
 * so Alerts can't say "up to date" while the Data Hub has open items (#309). Refresh
 * actions run on the Data Hub; everything else links to its fix.
 */
export default function Alerts() {
  const inbox = useApiResource("operationsInbox", () => api.operationsInbox());
  const items = inbox.data?.items ?? [];

  return (
    <PageShell title="Alerts" subtitle="Everything that needs you, from the Data Hub.">
      {inbox.isLoading && (
        <p className="muted" aria-busy="true">
          Loading alerts…
        </p>
      )}
      {inbox.error && !inbox.data && <LoadError title="Couldn't load alerts" error={inbox.error.message} />}

      {inbox.data && items.length === 0 && (
        <div className="card alertEmptyState" role="status" aria-label="No alerts">
          <p className="alertEmptyIcon" aria-hidden="true">✓</p>
          <p className="alertEmptyText">Nothing needs you. Everything is up to date.</p>
        </div>
      )}

      {items.length > 0 && (
        <ul className="inboxList" aria-label="Alerts">
          {items.map((item) => {
            const route = inboxItemRoute(item);
            return (
              <li key={item.id} className={`card inboxItem inboxItem-${item.severity}`} data-testid="alert-item">
                <div className="inboxItemText">
                  <p className="inboxItemTitle">
                    <span className={`inboxSeverity inboxSeverity-${item.severity}`}>{INBOX_SEVERITY_LABEL[item.severity]}</span>
                    {item.title}
                  </p>
                  {item.detail && <p className="inboxItemDetail muted">{item.detail}</p>}
                </div>
                <div className="inboxItemAction">
                  <Link className="btn" to={route ?? "/operations"}>
                    {route ? item.action?.label ?? "Open" : "Open the Data Hub"}
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </PageShell>
  );
}
