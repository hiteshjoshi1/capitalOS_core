"""Login throttle (#152): failed sign-ins per username and per client IP, with backoff.

In memory, per process. CapitalOS runs one API process (a single uvicorn worker), so this
counts every attempt; a restart forgets the counters, which is acceptable for a
self-hosted single-process app. With several workers each would count on its own and the
limits would scale with the worker count.

Policy, per key (a lower-cased username, or a client IP):
- failures are counted in a sliding window (AUTH_LOGIN_WINDOW_SECONDS, default 15 min);
- once a key reaches its limit (AUTH_LOGIN_MAX_FAILURES_PER_USER, default 5;
  AUTH_LOGIN_MAX_FAILURES_PER_IP, default 20) it is locked out for a backoff that doubles
  with each further failure: 30s, 60s, 120s ... capped at AUTH_LOGIN_LOCKOUT_MAX_SECONDS
  (default 15 min), counted from the last failure;
- a locked-out attempt is refused with 429 and Retry-After before any password check;
- a successful sign-in clears that username's counter (not the IP's).

The per-username limit means someone can keep a known username locked out for up to the
cap; the backoff is bounded so the owner is never locked out for longer than that.

Client IP: the TCP peer, unless the peer is a trusted proxy (loopback and private ranges
by default: the Vite dev server proxies /api from the host, and Docker publishes the API
on 127.0.0.1 only), in which case the right-most X-Forwarded-For entry is used (the
address the proxy itself appended). AUTH_TRUSTED_PROXIES overrides the list (comma
separated CIDRs; empty means trust no proxy).
"""

from __future__ import annotations

import ipaddress
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from starlette.requests import Request

_DEFAULT_TRUSTED_PROXIES = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)
_BASE_LOCKOUT_SECONDS = 30.0
_MAX_TRACKED_KEYS = 10_000


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except ValueError:
        return default


def window_seconds() -> int:
    return _env_int("AUTH_LOGIN_WINDOW_SECONDS", 900)


def max_failures_per_user() -> int:
    return _env_int("AUTH_LOGIN_MAX_FAILURES_PER_USER", 5)


def max_failures_per_ip() -> int:
    return _env_int("AUTH_LOGIN_MAX_FAILURES_PER_IP", 20)


def lockout_max_seconds() -> int:
    return _env_int("AUTH_LOGIN_LOCKOUT_MAX_SECONDS", 900)


@dataclass
class _Entry:
    failures: deque[float] = field(default_factory=deque)


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def _prune(self, entry: _Entry, now: float) -> None:
        cutoff = now - window_seconds()
        while entry.failures and entry.failures[0] < cutoff:
            entry.failures.popleft()

    def _retry_after(self, key: str, limit: int, now: float) -> float:
        entry = self._entries.get(key)
        if entry is None:
            return 0.0
        self._prune(entry, now)
        if not entry.failures:
            self._entries.pop(key, None)
            return 0.0
        over = len(entry.failures) - limit
        if over < 0:
            return 0.0
        backoff = min(_BASE_LOCKOUT_SECONDS * (2 ** min(over, 30)), float(lockout_max_seconds()))
        return max(entry.failures[-1] + backoff - now, 0.0)

    def retry_after(self, *, username: str, ip: str) -> int:
        """Seconds until a sign-in may be tried again (0: allowed now)."""
        now = self._clock()
        with self._lock:
            wait = max(
                self._retry_after(_user_key(username), max_failures_per_user(), now),
                self._retry_after(_ip_key(ip), max_failures_per_ip(), now),
            )
        return int(math.ceil(wait))

    def record_failure(self, *, username: str, ip: str) -> None:
        now = self._clock()
        with self._lock:
            for key in (_user_key(username), _ip_key(ip)):
                entry = self._entries.get(key)
                if entry is None:
                    if len(self._entries) >= _MAX_TRACKED_KEYS:
                        self._evict(now)
                    entry = self._entries[key] = _Entry()
                self._prune(entry, now)
                entry.failures.append(now)

    def record_success(self, *, username: str) -> None:
        with self._lock:
            self._entries.pop(_user_key(username), None)

    def _evict(self, now: float) -> None:
        # Bounded memory under a spray of usernames/IPs: drop expired keys, then the
        # stalest ones.
        for key in list(self._entries):
            self._prune(self._entries[key], now)
            if not self._entries[key].failures:
                del self._entries[key]
        if len(self._entries) >= _MAX_TRACKED_KEYS:
            stalest = sorted(self._entries, key=lambda k: self._entries[k].failures[-1])
            for key in stalest[: len(self._entries) - _MAX_TRACKED_KEYS + 1]:
                del self._entries[key]


def _user_key(username: str) -> str:
    return "user:" + username.strip().lower()


def _ip_key(ip: str) -> str:
    return "ip:" + ip


def _trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.getenv("AUTH_TRUSTED_PROXIES")
    items = _DEFAULT_TRUSTED_PROXIES if raw is None else tuple(p.strip() for p in raw.split(",") if p.strip())
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in items:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return networks


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    # An IPv4 client seen through an IPv6 socket (::ffff:a.b.c.d) is that IPv4 client.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def from_trusted_proxy(request: Request) -> bool:
    """Whether the direct peer is a proxy we trust for X-Forwarded-* (AUTH_TRUSTED_PROXIES)."""
    peer = _parse_ip(request.client.host if request.client else "")
    return peer is not None and any(peer in net for net in _trusted_proxy_networks())


def request_authority(request: Request) -> str:
    """The host[:port] the browser used: X-Forwarded-Host from a trusted proxy (nginx, Vite,
    tailscale serve), else the Host header (#358)."""
    if from_trusted_proxy(request):
        forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.headers.get("host", "")


def client_ip(request: Request) -> str:
    peer_raw = request.client.host if request.client else ""
    peer = _parse_ip(peer_raw)
    if peer is not None and any(peer in net for net in _trusted_proxy_networks()):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            nearest = _parse_ip(forwarded.split(",")[-1])
            if nearest is not None:
                return str(nearest)
    return str(peer) if peer is not None else (peer_raw or "unknown")


login_throttle = LoginThrottle()
