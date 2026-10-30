import { useEffect } from "react";

import { instanceLabel, instanceRepoUrl } from "../lib/instance";

// Marks a non-production instance (#45): a worktree's DEV stack or the batch TEST instance.
// The real-data app sets no label and shows no banner. With a repo URL, each "#N" in the
// label links to that PR (#101).
export default function InstanceBanner({
  label = instanceLabel(),
  repoUrl = instanceRepoUrl(),
}: {
  label?: string;
  repoUrl?: string;
}) {
  const kind = label.split(/\s/)[0]?.toUpperCase() || "";
  useEffect(() => {
    if (!label) return;
    const base = document.title.replace(/^\[[^\]]+\] /, "");
    document.title = `[${kind}] ${base}`;
  }, [label, kind]);
  if (!label) return null;
  const parts = repoUrl ? label.split(/(#\d+)/) : [label];
  return (
    <div
      className={`instanceBanner instanceBanner-${kind.toLowerCase()}`}
      role="status"
      aria-label="Instance"
    >
      {parts.map((part, i) =>
        /^#\d+$/.test(part) ? (
          <a key={i} href={`${repoUrl}/pull/${part.slice(1)}`} target="_blank" rel="noreferrer">
            {part}
          </a>
        ) : (
          part
        ),
      )}{" "}
      · not the real app
    </div>
  );
}
