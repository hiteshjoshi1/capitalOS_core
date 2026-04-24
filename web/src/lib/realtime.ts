import { getAccessToken, refreshAccessTokenNow } from "./api";
import type { RealtimeEventEnvelope } from "./api";

const RAW_API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "http://localhost:8000";
const API_BASE = RAW_API_BASE.replace(/\/+$/, "");

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
    this.listeners.add(listener);
    this.shouldReconnect = true;
    handlers.onStatusChange?.("connecting");
    void this.ensureConnected();

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
    const url = new URL(`${API_BASE.replace(/^http/i, "ws")}/realtime/ws`);
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
      const parsed = JSON.parse(message.data as string) as { type?: string } & RealtimeEventEnvelope;
      if (parsed.type !== "event") {
        return;
      }
      for (const listener of this.listeners) {
        if (listener.topic === parsed.topic) {
          listener.handlers.onEvent?.(parsed);
        }
      }
    });

    this.socket.addEventListener("close", () => {
      this.socket = null;
      this.notifyStatus("disconnected");
      if (!this.shouldReconnect || !this.listeners.size) {
        return;
      }
      this.reconnectTimer = setTimeout(async () => {
        this.reconnectTimer = null;
        if (!opened) {
          await refreshAccessTokenNow();
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
