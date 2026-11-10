import { getAccessToken, refreshAccessTokenNow, resolveApiBase } from "./api";
import type { RealtimeEventEnvelope } from "./api";

const API_BASE = resolveApiBase(
  import.meta.env.VITE_API_BASE as string | undefined,
  null,
  import.meta.env.VITE_API_PORT as string | undefined,
);

// The API base may be relative (e.g. "/api" behind the dev-server proxy), so
// resolve it against the page URL before swapping http(s) for ws(s).
export function buildRealtimeUrl(apiBase: string, pageUrl: string): URL {
  const url = new URL(`${apiBase}/realtime/ws`, pageUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url;
}

/** The server's close code for "sign in again" (expired token or ended session, #364). */
export const REALTIME_CLOSE_SIGN_IN_AGAIN = 4401;
// WebSocket.OPEN, spelled out so it doesn't depend on the global (tests stub WebSocket).
const WS_OPEN = 1;

type RealtimeStatus = "connecting" | "connected" | "disconnected";

type RealtimeHandlers<TPayload = Record<string, unknown>> = {
  onEvent?: (event: RealtimeEventEnvelope<TPayload>) => void;
  onStatusChange?: (status: RealtimeStatus) => void;
};

type RealtimeListener = {
  topic: string;
  handlers: RealtimeHandlers;
};

class RealtimeClient {
  private socket: WebSocket | null = null;
  private listeners = new Set<RealtimeListener>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = false;
  private connectInFlight: Promise<void> | null = null;

  subscribe<TPayload = Record<string, unknown>>(topic: string, handlers: RealtimeHandlers<TPayload>): () => void {
    const listener: RealtimeListener = { topic, handlers: handlers as RealtimeHandlers };
    const isNewTopic = ![...this.listeners].some((existing) => existing.topic === topic);
    this.listeners.add(listener);
    this.shouldReconnect = true;
    if (this.socket?.readyState === WS_OPEN) {
      // Already connected (#367): the open handler has sent its topics, so a topic added now must
      // be subscribed on its own or the server never sends its events.
      handlers.onStatusChange?.("connected");
      if (isNewTopic) {
        this.socket.send(JSON.stringify({ action: "subscribe", topics: [topic] }));
      }
      return this.unsubscriber(listener);
    }
    handlers.onStatusChange?.("connecting");
    void this.ensureConnected();

    return this.unsubscriber(listener);
  }

  private unsubscriber(listener: RealtimeListener): () => void {
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) {
        this.shouldReconnect = false;
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
        this.socket?.close();
        this.socket = null;
      }
    };
  }

  private async ensureConnected(): Promise<void> {
    if (this.socket || !this.listeners.size || this.connectInFlight) {
      return;
    }

    this.connectInFlight = this.connect().finally(() => {
      this.connectInFlight = null;
    });
    await this.connectInFlight;
  }

  private async connect(): Promise<void> {
    let token = getAccessToken();
    if (!token || tokenExpiresSoon(token)) {
      token = await refreshAccessTokenNow();
    }
    if (!token) {
      this.notifyStatus("disconnected");
      return;
    }

    this.notifyStatus("connecting");
    const url = buildRealtimeUrl(API_BASE, window.location.href);
    url.searchParams.set("access_token", token);
    this.socket = new WebSocket(url.toString());
    let opened = false;

    this.socket.addEventListener("open", () => {
      opened = true;
      this.notifyStatus("connected");
      const topics = [...new Set([...this.listeners].map((listener) => listener.topic))];
      this.socket?.send(JSON.stringify({ action: "subscribe", topics }));
    });

    this.socket.addEventListener("message", (message) => {
      const parsed = parseRealtimeMessage(message.data);
      if (!parsed || parsed.type !== "event") {
        return;
      }
      for (const listener of this.listeners) {
        if (listener.topic === parsed.topic) {
          listener.handlers.onEvent?.(parsed);
        }
      }
    });

    this.socket.addEventListener("close", (event) => {
      this.socket = null;
      this.notifyStatus("disconnected");
      if (!this.shouldReconnect || !this.listeners.size) {
        return;
      }
      // 4401 (#364): the server closed because the access token expired or the session ended.
      // Refresh first; if the session has ended, the refresh fails and connect() stops there.
      const mustRefresh = !opened || event.code === REALTIME_CLOSE_SIGN_IN_AGAIN;
      this.reconnectTimer = setTimeout(async () => {
        this.reconnectTimer = null;
        if (mustRefresh) {
          const token = await refreshAccessTokenNow();
          if (!token) {
            this.notifyStatus("disconnected");
            return;
          }
        }
        await this.ensureConnected();
      }, 1000);
    });

    this.socket.addEventListener("error", () => {
      this.notifyStatus("disconnected");
    });
  }

  private notifyStatus(status: RealtimeStatus): void {
    for (const listener of this.listeners) {
      listener.handlers.onStatusChange?.(status);
    }
  }
}

/** A server message, or null for anything that isn't a JSON object (#367): one bad frame must
 * not throw inside the socket's handler. */
export function parseRealtimeMessage(data: unknown): ({ type?: string } & RealtimeEventEnvelope) | null {
  if (typeof data !== "string") {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(data);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as { type?: string } & RealtimeEventEnvelope;
    }
  } catch {
    // fall through
  }
  if (import.meta.env.DEV) {
    console.warn("Ignoring a malformed realtime message", data);
  }
  return null;
}

function tokenExpiresSoon(token: string): boolean {
  const parts = token.split(".");
  if (parts.length < 2) {
    return true;
  }
  try {
    const payload = JSON.parse(decodeBase64Url(parts[1])) as { exp?: number };
    if (typeof payload.exp !== "number") {
      return true;
    }
    return payload.exp <= Math.floor(Date.now() / 1000) + 30;
  } catch {
    return true;
  }
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  return atob(padded);
}

const realtimeClient = new RealtimeClient();

export function subscribeToRealtimeTopic<TPayload = Record<string, unknown>>(
  topic: string,
  handlers: RealtimeHandlers<TPayload>,
): () => void {
  return realtimeClient.subscribe(topic, handlers);
}
