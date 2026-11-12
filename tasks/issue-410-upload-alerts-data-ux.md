# Issue #410: uploads, alerts & data (UX U28, U29, U30)

- **U28 (upload effect):** `app/ingestion/upload_effect.py`; the runner measures the statement's month before writing and after committing; the import report gains `effect` (balance, net worth before/after/change). Ingest shows one line: "Balance S$ X on 31 Oct · net worth for Oct 2026 +S$ Y (A → B)" (`web/src/lib/uploadEffect.ts`).
- **U29 (alerts):** `app/services/insight_alerts.py`, added to the Inbox (and so the bell and Alerts): `month_closed_stale`, `concentration`, `unusual_move`, `recurring_new`, `recurring_up`. Thresholds in the module doc.
- **U30 (broker new money):** `bridge.py` `_broker_money`: no-cash-record brokers' buys/sales on New money (per broker, estimated), less bank transfers naming the broker; no longer in Unexplained.
- D-114. Tests: `test_insight_alerts.py`, `test_broker_new_money.py`, updated `test_month_bridge.py`, `test_bridge_items.py`, `test_ingest_ocbc.py`; web `uploadEffect.test.ts`.
