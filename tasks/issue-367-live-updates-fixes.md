# Issue #367: live-updates client: late subscribes and malformed messages

From #353 T9 (#130 §7.9). Live updates refresh the Overview when a price refresh or import finishes.

## Change (`web/src/lib/realtime.ts`)
- A topic subscribed while the socket is already open is sent to the server (`{"action":"subscribe"}`, which
  adds to the connection's topics); before, only the topics present at `open` were ever sent. A second
  listener on an already-subscribed topic sends nothing.
- `parseRealtimeMessage`: a frame that isn't a JSON object is ignored (console warning in dev) instead of
  throwing inside the socket's message handler.

## Tests
`web/src/__tests__/realtime.test.ts`: late subscribe sent once per new topic; malformed frames ignored, valid
events still delivered. Both fail on the old client.
