import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { inboxItemRoute } from "../lib/inbox";
import "../routes/OperationsInbox.css";

/**
 * The header bell (#317): the Data Hub inbox count (#316), the same number on every page
 * and on a phone. On a wide screen it opens the list (each item linking to its fix, or to
 * the Data Hub for a refresh); on a phone it is a link to the Data Hub Inbox.
 */
export default function InboxBell({ narrow }: { narrow: boolean }) {
  const inbox = useApiResource("operationsInbox", () => api.operationsInbox(), { staleTimeMs: 60_000 });
  const count = inbox.data?.count ?? 0;
  const label = count === 0 ? "Nothing needs you" : `${count} item${count === 1 ? "" : "s"} need${count === 1 ? "s" : ""} you`;
  const menuRef = useRef<HTMLDetailsElement | null>(null);
  const location = useLocation();

  // Close the list on navigation, outside clicks and Escape.
  useEffect(() => {
    if (menuRef.current) menuRef.current.open = false;
  }, [location.pathname, location.search]);
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      const menu = menuRef.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && menuRef.current?.open) menuRef.current.open = false;
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const icon = (
    <>
      <span className="material-symbols-outlined inboxBellIcon" aria-hidden="true">
        notifications
      </span>
      {count > 0 && (
        <span className="inboxBellCount" data-testid="inbox-bell-count" aria-hidden="true">
          {count}
        </span>
      )}
    </>
  );

  if (narrow) {
    return (
      <Link className="inboxBell" to="/operations" aria-label={label}>
        {icon}
      </Link>
    );
  }

  const items = inbox.data?.items ?? [];
  return (
    <details className="inboxBellMenu" ref={menuRef}>
      <summary className="inboxBell" aria-label={label}>
        {icon}
      </summary>
      <div className="inboxBellPanel" role="group" aria-label="Needs you">
        {items.length === 0 ? (
          <p className="inboxBellEmpty">
            <span aria-hidden="true">✓ </span>Nothing needs you.
          </p>
        ) : (
          <ul className="inboxBellList">
            {items.slice(0, 8).map((item) => (
              <li key={item.id}>
                <Link className="inboxBellItem" to={inboxItemRoute(item) ?? "/operations"}>
                  <span className={`inboxBellDot inboxBellDot-${item.severity}`} aria-hidden="true" />
                  <span className="inboxBellItemText">{item.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <Link className="inboxBellAll" to="/operations">
          Open the Data Hub{items.length > 8 ? ` (${items.length - 8} more)` : ""}
        </Link>
      </div>
    </details>
  );
}
