import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { SOURCE_FRESHNESS_KEY, isUploadSource, overdueSummary, sourceLink } from "../lib/sourceFreshness";
import { useApiResource } from "../lib/useApiResource";
import "./SourceFreshness.css";

/**
 * Overview's one-line freshness summary (#252): "2 sources overdue: … · Open Data Hub".
 * Renders nothing while loading, on an error, or when every source is on time.
 * Self-contained: it reads the same resource as the Data Hub table.
 */
export default function SourceFreshnessStrip() {
  const res = useApiResource(SOURCE_FRESHNESS_KEY, () => api.sourceFreshness());
  const summary = overdueSummary(res.data);
  if (!summary) return null;
  // Exactly one overdue source, and it's an upload: link straight to its prefilled Upload (#278).
  const overdue = (res.data?.sources ?? []).filter((row) => row.overdue);
  const only = overdue.length === 1 && isUploadSource(overdue[0]) ? overdue[0] : null;
  const uploadLink = only ? sourceLink(only) : null;
  return (
    <p className="sourceFreshnessStrip" role="status" data-testid="source-freshness-strip">
      <span>{summary}</span>
      {uploadLink ? <Link to={uploadLink}>Upload it →</Link> : null}
      <Link to="/operations">Open Data Hub →</Link>
    </p>
  );
}
