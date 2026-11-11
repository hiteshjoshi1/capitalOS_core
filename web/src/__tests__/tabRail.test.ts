import { afterEach, describe, expect, it, vi } from "vitest";
import { revealActiveTab, watchActiveTab } from "../lib/tabRail";

// #371: the active section tab stays in view in the sideways-scrolling rail.

function box(left: number, width: number): DOMRect {
  return { left, right: left + width, width, top: 0, bottom: 20, height: 20, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
}

/** A 300px-wide rail at x=0 whose active tab sits at `tabLeft` (in viewport coordinates). */
function makeRail(tabLeft: number, tabWidth = 80) {
  const rail = document.createElement("nav");
  const tab = document.createElement("a");
  tab.className = "appShellTab appShellTabActive";
  rail.appendChild(tab);
  document.body.appendChild(rail);
  rail.getBoundingClientRect = () => box(0, 300);
  // The tab moves left as the rail scrolls.
  tab.getBoundingClientRect = () => box(tabLeft - rail.scrollLeft, tabWidth);
  return { rail, tab };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("revealActiveTab", () => {
  it("scrolls right just enough when the active tab is past the right edge", () => {
    const { rail } = makeRail(400);
    expect(revealActiveTab(rail)).toBe(true);
    expect(rail.scrollLeft).toBe(180); // tab 400..480 → right edge at 300
  });

  it("scrolls left when the active tab is before the left edge", () => {
    const { rail } = makeRail(100);
    rail.scrollLeft = 150; // tab now at -50
    expect(revealActiveTab(rail)).toBe(true);
    expect(rail.scrollLeft).toBe(100);
  });

  it("leaves the rail alone when the tab is already visible, or there is no active tab", () => {
    const { rail, tab } = makeRail(50);
    expect(revealActiveTab(rail)).toBe(false);
    expect(rail.scrollLeft).toBe(0);
    tab.className = "appShellTab";
    expect(revealActiveTab(rail)).toBe(false);
  });

  it("shows a tab wider than the rail from its start", () => {
    const { rail } = makeRail(400, 500);
    revealActiveTab(rail);
    expect(rail.scrollLeft).toBe(400);
  });
});

describe("watchActiveTab", () => {
  it("re-reveals the tab when the rail or the tab changes size later, until cleaned up", () => {
    const callbacks: Array<() => void> = [];
    const observed: Element[] = [];
    class FakeResizeObserver {
      constructor(cb: () => void) {
        callbacks.push(cb);
      }
      observe(el: Element) {
        observed.push(el);
      }
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    let tabLeft = 50;
    const { rail, tab } = makeRail(50);
    tab.getBoundingClientRect = () => box(tabLeft - rail.scrollLeft, 80);

    const stop = watchActiveTab(rail);
    expect(rail.scrollLeft).toBe(0); // visible at first
    expect(observed).toEqual([rail, tab]);

    // Fonts load / the top bar fills in: the tab ends up past the edge.
    tabLeft = 350;
    callbacks[0]();
    expect(rail.scrollLeft).toBe(130);

    stop();
    tabLeft = 600;
    callbacks[0]();
    expect(rail.scrollLeft).toBe(130);
  });
});
