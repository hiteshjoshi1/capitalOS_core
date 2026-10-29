// The non-production instance label (#45): VITE_INSTANCE_LABEL, set by `make web-up` in a
// worktree ("DEV ...") and by `make test-instance` ("TEST ..."); empty for the real app.
export function instanceLabel(env: Record<string, unknown> = import.meta.env): string {
  const raw = env.VITE_INSTANCE_LABEL;
  return typeof raw === "string" ? raw.trim() : "";
}
