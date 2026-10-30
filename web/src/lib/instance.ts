// The non-production instance label (#45): VITE_INSTANCE_LABEL, set by `make web-up` in a
// worktree ("DEV ...") and by `make test-instance` ("TEST ..."); empty for the real app.
export function instanceLabel(env: Record<string, unknown> = import.meta.env): string {
  const raw = env.VITE_INSTANCE_LABEL;
  return typeof raw === "string" ? raw.trim() : "";
}

// The GitHub repo the label's "#N" PR numbers belong to (#101): VITE_INSTANCE_REPO_URL, set by
// `make test-instance`. Only an https URL is used; anything else means no links.
export function instanceRepoUrl(env: Record<string, unknown> = import.meta.env): string {
  const raw = env.VITE_INSTANCE_REPO_URL;
  if (typeof raw !== "string" || !/^https:\/\/[^\s"<>]+$/.test(raw.trim())) return "";
  return raw.trim().replace(/\/+$/, "");
}
