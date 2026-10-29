import { useEffect } from "react";

import { instanceLabel } from "../lib/instance";

// Marks a non-production instance (#45): a worktree's DEV stack or the batch TEST instance.
// The real-data app sets no label and shows no banner.
export default function InstanceBanner({ label = instanceLabel() }: { label?: string }) {
  const kind = label.split(/\s/)[0]?.toUpperCase() || "";
  useEffect(() => {
    if (!label) return;
    const base = document.title.replace(/^\[[^\]]+\] /, "");
    document.title = `[${kind}] ${base}`;
  }, [label, kind]);
  if (!label) return null;
  return (
    <div
      className={`instanceBanner instanceBanner-${kind.toLowerCase()}`}
      role="status"
      aria-label="Instance"
    >
      {label} · not the real app
    </div>
  );
}
