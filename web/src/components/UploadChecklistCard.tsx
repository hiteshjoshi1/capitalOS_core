// #449 (V23): this month's statement uploads, done and still to do, at the top of the Upload page.
// What's still to do is listed; what's done folds into one line (it's long on a phone).
import { Link } from "react-router-dom";
import type { UploadChecklist, UploadChecklistSource } from "../lib/api";
import { checklistMeta } from "../lib/batchUpload";
import { formatMonth } from "../lib/format";

function Row({ s }: { s: UploadChecklistSource }) {
  return (
    <li className={`checklistRow${s.done ? " checklistDone" : ""}`} data-testid="checklist-row">
      <span className="checklistMark" role="img" aria-label={s.done ? "done" : "to do"}>
        {s.done ? "✓" : "○"}
      </span>
      <span className="checklistLabel">
        {s.label}
        <span className="checklistMeta">
          {checklistMeta(s.last_import_date, s.last_data_date)}
          {s.overdue ? " · overdue" : ""}
        </span>
      </span>
      {!s.done ? (
        <Link className="btn btnSmall" to={`/ingest?account_id=${s.account_id}`}>
          Upload
        </Link>
      ) : null}
    </li>
  );
}

export default function UploadChecklistCard({ checklist }: { checklist: UploadChecklist }) {
  if (checklist.total === 0) return null;
  const todo = checklist.sources.filter((s) => !s.done);
  const done = checklist.sources.filter((s) => s.done);
  return (
    <section className="card" aria-label="This month's uploads">
      <div className="cardTitle">
        {formatMonth(checklist.month, "medium")} uploads · {checklist.done} of {checklist.total}
      </div>
      {todo.length === 0 ? (
        <p className="hint" role="status">Every statement for this month is in.</p>
      ) : (
        <>
          <p className="hint">Drop several files below at once: each goes to its account.</p>
          <ul className="checklistList">
            {todo.map((s) => (
              <Row s={s} key={s.source_key} />
            ))}
          </ul>
        </>
      )}
      {done.length > 0 ? (
        <details className="checklistDoneGroup">
          <summary>{done.length} done</summary>
          <ul className="checklistList">
            {done.map((s) => (
              <Row s={s} key={s.source_key} />
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
