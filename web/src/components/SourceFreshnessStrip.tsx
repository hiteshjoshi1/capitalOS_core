import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { SOURCE_FRESHNESS_KEY, overdueSummary } from "../lib/sourceFreshness";
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
  return (
    <p className="sourceFreshnessStrip" role="status" data-testid="source-freshness-strip">
      <span>{summary}</span>
      <Link to="/operations">Open Data Hub →</Link>
    </p>
  );
}
