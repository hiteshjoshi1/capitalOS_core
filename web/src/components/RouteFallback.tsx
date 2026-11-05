// Shown inside AppShell's content area while a lazily loaded route chunk downloads,
// so the sidebar and top bar stay on screen. Same look as the pages' own loading state.
export default function RouteFallback() {
  return <div className="card" role="status">Loading…</div>;
}
