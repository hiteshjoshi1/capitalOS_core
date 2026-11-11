/**
 * #371: keep the active section tab visible in the sideways-scrolling tab rail (#264).
 *
 * Scrolling once on a route change wasn't enough on a phone: the rail's width and the tabs'
 * widths change after that (web fonts load, a lazy page fills the top bar's actions), which
 * could leave the active tab off-screen. So the rail is re-checked whenever it or the active
 * tab changes size, and only `scrollLeft` moves (never the page, unlike `scrollIntoView`).
 */

export const ACTIVE_TAB_SELECTOR = ".appShellTabActive";

/** Scrolls `rail` sideways just enough to show its active tab. Returns whether it moved. */
export function revealActiveTab(rail: HTMLElement): boolean {
  const active = rail.querySelector<HTMLElement>(ACTIVE_TAB_SELECTOR);
  if (!active) return false;
  const railBox = rail.getBoundingClientRect();
  const tabBox = active.getBoundingClientRect();
  let delta = 0;
  if (tabBox.left < railBox.left) delta = tabBox.left - railBox.left;
  else if (tabBox.right > railBox.right) delta = Math.min(tabBox.right - railBox.right, tabBox.left - railBox.left);
  if (delta === 0) return false;
  rail.scrollLeft += delta;
  return true;
}

/**
 * Reveals the active tab now, after web fonts load, and whenever the rail or the active tab
 * changes size. Returns the cleanup.
 */
export function watchActiveTab(rail: HTMLElement): () => void {
  let stopped = false;
  const reveal = () => {
    if (!stopped) revealActiveTab(rail);
  };
  reveal();
  const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(reveal);
  observer?.observe(rail);
  const active = rail.querySelector<HTMLElement>(ACTIVE_TAB_SELECTOR);
  if (active) observer?.observe(active);
  void document.fonts?.ready.then(reveal);
  return () => {
    stopped = true;
    observer?.disconnect();
  };
}
