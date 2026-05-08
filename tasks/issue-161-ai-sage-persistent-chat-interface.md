# Issue 161: AI Sage persistent chat interface and conversation history

## Objective
- Transform AI Sage from a one-off query surface into a persistent conversational research workspace where users can create, resume, rename, search, and delete multiple saved chats.
- Support multi-turn follow-up questions inside a chat while preserving grounded retrieval, citations, and deterministic auditability for each assistant answer.
- Define the data retention, privacy, and deletion behavior for saved AI Sage conversations before implementation begins.

## UX Definition
- The AI Sage first screen should feel like a modern chat workspace, closer to ChatGPT or Claude than a static search form.
- The primary layout should have:
  - A left conversation sidebar for saved chats.
  - A main chat transcript area.
  - A bottom composer that remains available while reading.
  - A compact model/retrieval status area only where useful for auditability.
- The sidebar should show recent chats ordered by latest activity.
- The sidebar should comfortably show about 5 recent chats in the initial visible region and become vertically scrollable for larger histories.
- Each chat row should show:
  - Chat title.
  - Short preview from the latest user or assistant message.
  - Last updated timestamp.
  - Optional lightweight status such as `draft`, `answered`, or `failed` if needed.
- Users should be able to:
  - Start a new chat.
  - Continue an existing chat.
  - Rename a chat.
  - Delete a chat.
  - Search saved chats by title and message text.
  - See an empty state when no chats exist.
- Chat search should use a ChatGPT-like search modal rather than only a small inline filter control.
- The search modal should:
  - Open from an explicit search action in the AI Sage workspace.
  - Prefer a keyboard-first flow such as `Cmd/Ctrl+K` if practical inside the existing app shell.
  - Search chat titles and message text for the authenticated user only.
  - Show compact result rows with chat title, matching snippet, and last updated timestamp.
  - Open the selected chat directly into the transcript route.
- A new chat should start with a focused composer and suggested prompt chips only if they are practical and grounded in existing product workflows.
- Prompt suggestions must not be decorative marketing content. They should be useful actions such as portfolio question, author corpus question, thesis pressure test, or document-grounded research question.
- The main transcript should display messages in chronological order.
- User messages should be visually distinct from assistant messages, with dense readable spacing suitable for long research conversations.
- Assistant messages should include:
  - Main answer.
  - Cited ranked passages or source references used for that turn.
  - Retrieval metadata in a collapsed or secondary area, not as primary visual noise.
  - Follow-up suggestions where the backend already produces them.
  - Error state when a turn fails, with retry for that turn.
- The composer should support:
  - Plain text input.
  - Enter to send and Shift+Enter for newline.
  - Disabled state while a turn is in progress.
  - Streaming assistant responses in the first version so answers feel conversational rather than batch-rendered.
  - Abort/cancel generation if supported by the streaming implementation.
  - Clear validation for empty messages.
- Follow-up questions should use prior chat context, but each assistant turn must still run grounded retrieval and return evidence for the new answer.
- The user should be able to open cited documents from any assistant turn using the Author Library reader flow from issue 158.
- Long cited evidence should remain expandable so the transcript does not become unreadable.
- The interface should preserve scroll position while sending and receiving new messages.
- The latest answer should scroll into view after completion unless the user has manually scrolled away from the bottom.
- The URL should support deep linking to a chat, for example `/ai-sage/chats/:chatId`.
- Refreshing the page on a chat URL should reload the same chat transcript.
- Direct navigation to a missing or unauthorized chat should show a clear not-found or access-denied state.
- The mobile layout should collapse the sidebar behind a chats button or drawer while keeping the transcript and composer usable.
- The design should match the existing app shell and avoid a marketing-style landing page.

## Data Retention And Privacy
- Chats are saved by default for authenticated users.
- Each chat and message must be owned by the authenticated user only. Users must never see another user's conversations.
- Conversation records should include enough metadata for auditability without storing unnecessary hidden provider internals.
- Chats should be retained for 1 year from the timestamp of the last user query/message in the chat.
- Chats older than the 1-year retention window should be automatically hard deleted by a deterministic cleanup path.
- Retain the exact user message text and assistant answer text shown in the UI.
- Retain per-turn retrieval evidence needed to reconstruct why an answer was grounded:
  - `chunk_id`
  - `document_id`
  - `author_id`
  - source title or document title
  - citation snippet or passage text shown to the user
  - ranking score fields that are already exposed by AI Sage
  - retrieval mode or query classification where available
- Retain request/response timestamps, turn status, and error details needed for user-visible retry/debug behavior.
- Do not store raw provider prompts, hidden chain-of-thought, model internals, API keys, or credentials.
- If a future implementation stores full provider request payloads for debugging, that must be a separate explicitly approved issue with clear retention limits.
- Manual user deletion should remove the chat from the normal user experience immediately and hard delete it from primary application tables in the first version.
- Retention should be local-first and deterministic. No remote analytics or telemetry should be introduced by this issue.
- The user should have a visible delete action for a chat before any automated retention policy is introduced.
- Bulk export is not required in the first version, but the schema should not make future export difficult.
- Automated summarization or long-term memory derived from chats is out of scope for this issue.

## Architecture Decisions
- Decision 1: AI Sage chat persistence should be first-party application data in Postgres, not browser-only local storage.
- Decision 2: Saved chats should be scoped to authenticated user ownership only in the first version, using the existing auth model.
- Decision 3: The existing AI Sage query engine should remain the answer-generation path for each turn; this issue should wrap it in conversation persistence rather than fork retrieval logic.
- Decision 4: Each assistant turn should persist the evidence returned for that turn so old chats remain auditable even if the corpus or retrieval ranking changes later.
- Decision 5: Follow-up turns should send recent conversation context into the AI Sage orchestration layer in a bounded, deterministic way rather than concatenating unlimited history.
- Decision 6: Retrieval must still happen per user turn. Follow-up context can inform intent and phrasing, but it must not replace corpus grounding.
- Decision 7: The frontend should use route-level chat IDs and typed API clients rather than storing active chat state only in component memory.
- Decision 8: The API should expose explicit chat/session resources instead of overloading the existing one-off `/ai-sage/query` endpoint.
- Decision 9: The one-off AI Sage query endpoint should remain backward-compatible unless a migration issue explicitly removes it later.
- Decision 10: Streaming responses are required in the first version. The data model and UI state machine should support incremental assistant output.
- Decision 11: Chat search should use a dedicated ChatGPT-like modal flow rather than a small inline-only sidebar filter.
- Decision 12: Chats should be retained for 1 year from the timestamp of the last user query/message in the chat and then automatically hard deleted by deterministic cleanup. Manual delete should hard delete immediately.
- Decision 13: The first-version bounded conversation context should be chat title plus the last 5 completed user/assistant messages ordered by `created_at` then `id`.
- Decision 14: The UX should prioritize research traceability over novelty. Every answer should make it easy to inspect sources and related documents.
- Decision 15: Chat summarization, automatic memory, and cross-chat personalization are future modules and must not be implemented in this issue.

## Proposed Data Model
- Add an `ai_sage_chats` table or equivalent model:
  - `id`
  - `owner_user_id` or existing ownership fields
  - `title`
  - `created_at`
  - `updated_at`
  - optional `last_activity_at` if it is kept distinct from `updated_at`
  - optional `pinned_at`
  - optional `metadata_json`
- Add an `ai_sage_messages` table or equivalent model:
  - `id`
  - `chat_id`
  - `role` with allowed values such as `user`, `assistant`, `system`
  - `content`
  - `status` with allowed values such as `completed`, `failed`, `cancelled`
  - `created_at`
  - `completed_at`
  - optional `error_message`
  - optional `metadata_json`
- Add an `ai_sage_turn_evidence` table or equivalent structured JSON payload:
  - `id`
  - `message_id`
  - `chunk_id`
  - `document_id`
  - `author_id`
  - `author_name`
  - `source_url`
  - `title`
  - `snippet`
  - `similarity`
  - `ranking_score`
  - `score_type`
  - `metadata_json`
- Evidence should be linked to the assistant message that used it.
- Message ordering should be stable by `created_at` and a deterministic secondary key such as `id`.
- The schema should allow failed assistant messages to exist so a failed turn can be displayed and retried.

## Proposed API Surface
- `GET /ai-sage/chats`
  - Returns paginated chat summaries for the current user.
  - Supports limit/offset or cursor pagination for the sidebar.
- `GET /ai-sage/chats/search`
  - Powers the chat-search modal for the current user.
  - Searches chat titles and message text.
  - Returns compact result rows with chat id, title, matching snippet, and last updated timestamp.
- `POST /ai-sage/chats`
  - Creates a new empty chat or creates a chat with the first user message.
- `GET /ai-sage/chats/{chat_id}`
  - Returns chat metadata, ordered messages, and persisted evidence for assistant messages.
- `PATCH /ai-sage/chats/{chat_id}`
  - Renames, pins, or updates lightweight chat metadata.
- `DELETE /ai-sage/chats/{chat_id}`
  - Hard deletes the chat immediately for the current user.
- `POST /ai-sage/chats/{chat_id}/messages`
  - Adds a user message, executes AI Sage for that turn, persists the assistant response, and returns the new messages.
- `POST /ai-sage/chats/{chat_id}/messages/{message_id}/retry`
  - Retries a failed assistant response or regenerates from the associated user turn if regeneration is supported.
- Existing `POST /ai-sage/query` remains available for backward compatibility.
- All new endpoints must be OpenAPI-compatible and use typed Pydantic request/response models.
- Every endpoint must enforce current-user ownership before reading or mutating chat data.
- APIs should be curl-verifiable with login token flow.

## Conversation Context Rules
- The backend should build a bounded conversation context for follow-up turns.
- Context should include recent user and assistant messages, not every historical message without limit.
- The first implementation should use this explicit deterministic policy:
  - Chat title plus the last 5 completed user/assistant messages ordered by `created_at` then `id`.
- Older transcript history should remain persisted and scrollable in the UI, but it should not be blindly resent to the model every turn.
- The selected policy must be documented in code and tests.
- Conversation context should help resolve pronouns and follow-up references such as "compare that with Buffett" or "go deeper on the second point".
- The final answer must still include fresh evidence for the current turn.
- If retrieval returns weak evidence, the assistant should say so rather than leaning only on chat history.

## Acceptance Criteria
- [ ] AI Sage supports multiple saved chats per authenticated user.
- [ ] Users can create a new chat from the AI Sage interface.
- [ ] Users can ask multiple follow-up questions inside the same chat.
- [ ] Refreshing a chat URL reloads the persisted conversation.
- [ ] Users can switch between saved chats from a conversation sidebar or equivalent navigation surface.
- [ ] Users can rename a chat.
- [ ] Users can delete a chat.
- [ ] Deleted chats are no longer visible or fetchable through normal user APIs.
- [ ] Chats are retained for 1 year from the timestamp of the last user query/message in the chat and then automatically hard deleted.
- [ ] Chat list is ordered by latest activity.
- [ ] Chat list supports enough metadata for title, preview, and last updated timestamp.
- [ ] The sidebar remains usable for larger histories by showing about 5 chats in the initial visible region and allowing vertical scrolling for more.
- [ ] AI Sage supports a ChatGPT-like chat-search modal.
- [ ] The chat-search modal searches chat titles and message text for the authenticated user only.
- [ ] Selecting a result from the chat-search modal opens the target chat transcript directly.
- [ ] Assistant answers persist the answer text shown to the user.
- [ ] User messages persist the exact submitted text.
- [ ] Assistant messages persist evidence used for that turn.
- [ ] Evidence remains linked to `chunk_id` and `document_id` when corpus evidence is available.
- [ ] Follow-up turns use bounded prior conversation context.
- [ ] Follow-up turns still perform grounded retrieval for the current question.
- [ ] Assistant responses stream incrementally in the first-version UI.
- [ ] Existing one-off AI Sage query behavior remains backward-compatible.
- [ ] All new API responses are represented in OpenAPI.
- [ ] Frontend TypeScript types mirror the backend response models.
- [ ] The UI handles loading, empty, failed, retry, and unauthorized/not-found states.
- [ ] The mobile layout remains usable with chat navigation available.
- [ ] No provider hidden reasoning, credentials, API keys, or raw secret-bearing payloads are persisted.
- [ ] Tests cover chat creation, listing, retrieval, follow-up messages, deletion, ownership isolation, evidence persistence, and frontend chat navigation.
- [ ] The feature is verifiable via Makefile commands and curl-verifiable APIs.

## Out Of Scope
- Cross-chat memory or personalization.
- Automatic long-term user profile updates.
- Chat sharing links.
- Collaborative chats.
- Remote analytics or telemetry.
- Voice input/output.
- File upload inside chats.
- Removing or breaking the existing `/ai-sage/query` endpoint.

## Human Approval Gate
- [x] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `approved_for_implementation`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-05-05`
- Implementation plan:
  - `1. Add Postgres persistence with new ai_sage_chats, ai_sage_messages, and ai_sage_turn_evidence tables via numbered SQL migration.`
  - `2. Add SQLAlchemy models and typed Pydantic schemas for chat summaries, transcripts, evidence, create/update/delete, message post, and retry flows.`
  - `3. Extend api/app/routers/ai_sage.py with explicit chat resources while preserving POST /ai-sage/query unchanged for backward compatibility.`
  - `4. Reuse the existing AI Sage query path for each turn, persisting exact user text, assistant text, and evidence returned for that turn.`
  - `5. Implement deterministic bounded context as chat title plus the last 5 completed user/assistant messages ordered by created_at then id.`
  - `6. Implement first-version retention as 1 year from the last user query/message in the chat with automatic hard deletion after expiry, while manual delete hard deletes immediately.`
  - `7. Scope chat ownership to the authenticated user id from the existing auth model and enforce ownership on every list/fetch/mutate endpoint.`
  - `8. Replace the one-off AISage frontend route with a route-driven workspace using /ai-sage and /ai-sage/chats/:chatId, typed API calls, sidebar navigation, mobile drawer, a ChatGPT-like chat-search modal, rename/delete/search, streaming response state, and retry state.`
  - `9. Add backend tests for creation, listing, retrieval, follow-up turns, retry, deletion, ownership isolation, evidence persistence, and OpenAPI contract coverage.`
  - `10. Add frontend tests for empty/loading/failed/not-found states, deep linking, chat switching, rename/delete flows, and mobile navigation presence.`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` — `No product code changes were made while recording final human decisions on 2026-05-05.`
- `typecheck`: `skip` — `No product code changes were made while recording final human decisions on 2026-05-05.`
- `tests`: `skip` — `No product code changes were made while recording final human decisions on 2026-05-05.`
- `e2e`: `skip` — `No product code changes were made while recording final human decisions on 2026-05-05.`
- `api-smoke`: `skip` — `No product code changes were made while recording final human decisions on 2026-05-05.`
- `policy-checks`: `pass` — `Human decisions are now recorded explicitly in the task file and the issue is approved for implementation.`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `Previous blocked run on 2026-05-04 is superseded by approved human decisions recorded on 2026-05-05.`
- Attempted mitigations:
  - `Validated the current AI Sage backend/frontend surfaces and mapped the concrete code paths that would be changed.`
  - `Converted the issue narrative into an explicit implementation plan and then replaced the open defaults with final human decisions.`
- Suggested human action: `Proceed with implementation using the approved decisions below.`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Implement the issue using the approved first-version decisions now recorded in this task file.`
- Open questions:
  - `No blocking product questions remain. The following decisions were approved on 2026-05-05: authenticated user ownership only; 1-year retention from the last user query/message in the chat with automatic hard delete after expiry; manual hard delete on user deletion; streaming responses in v1; bounded model context of chat title plus the last 5 completed user/assistant messages; ChatGPT-like chat-search modal.`
- If PR raised but intent partial:
  - unmet criteria: `All implementation criteria remain unmet until product code is written in a follow-up implementation run.`
  - follow-up issue: `None currently required.`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented AI Sage as a persistent, user-scoped chat workspace with Postgres-backed chats/messages/evidence, bounded follow-up context, hard-delete retention, route-driven chat history UI, chat search, rename/delete flows, retry handling, and incremental SSE-style response streaming while keeping POST /ai-sage/query backward-compatible.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Multiple saved AI Sage chats per authenticated user with create, resume, rename, delete, search, and deep links.
- Acceptance criterion: Per-turn persistence of exact user text, assistant text, and structured evidence including chunk/document linkage when available.
- Acceptance criterion: Bounded follow-up context with fresh retrieval on every user turn.
- Acceptance criterion: Incremental chat response streaming in the first-version UI with retry/error handling.
- Acceptance criterion: One-off /ai-sage/query compatibility, OpenAPI coverage, typed frontend contracts, and make-verifiable test coverage.

## Prepare
Checked out `feature/issue-161-ai-sage-persistent-chat-interface` from `main` and ensured task file exists.

## Plan Summary
Added AI Sage persistence models/migration/services and explicit chat APIs first, then replaced the one-off frontend with a deep-linked chat workspace using typed clients and streaming state, then added backend/frontend/e2e coverage and ran the required make-based verification gates.

### Architecture Decisions
- Persist AI Sage chats, messages, and per-turn evidence as first-party Postgres application data with authenticated owner scoping.
- Keep POST /ai-sage/query intact for backward compatibility and add explicit /ai-sage/chats resources for saved conversations.
- Use deterministic bounded context for follow-ups: chat title plus the last 5 completed user/assistant messages ordered by created_at then id.
- Retain chats for 1 year from the last user message via deterministic pruning: request-path pruning plus a daily backend scheduler hard-delete expired chats.
- Support conversational feel with an additive SSE streaming endpoint that the new route-driven UI consumes without changing the legacy one-off endpoint contract.

### Acceptance Criteria
- Multiple saved AI Sage chats per authenticated user with create, resume, rename, delete, search, and deep links.
- Per-turn persistence of exact user text, assistant text, and structured evidence including chunk/document linkage when available.
- Bounded follow-up context with fresh retrieval on every user turn.
- Incremental chat response streaming in the first-version UI with retry/error handling.
- One-off /ai-sage/query compatibility, OpenAPI coverage, typed frontend contracts, and make-verifiable test coverage.

### Planned Paths
- `api/app`
- `api/tests`
- `migrations`
- `web/src`
- `web/tests/e2e`

## Build Summary
Implemented AI Sage as a persistent, user-scoped chat workspace with Postgres-backed chats/messages/evidence, bounded follow-up context, hard-delete retention, route-driven chat history UI, chat search, rename/delete flows, retry handling, and incremental SSE-style response streaming while keeping POST /ai-sage/query backward-compatible.

### Changed Files
- `api/app/main.py`
- `api/app/models/__init__.py`
- `api/app/models/ai_sage_chat.py`
- `api/app/routers/ai_sage.py`
- `api/app/schemas/ai_sage.py`
- `api/app/services/ai_sage.py`
- `api/tests/conftest.py`
- `api/tests/test_ai_sage_chats.py`
- `api/tests/test_contracts.py`
- `migrations/048_ai_sage_chat_history.sql`
- `tasks/issue-161-ai-sage-persistent-chat-interface.md`
- `web/src/App.css`
- `web/src/__tests__/AISage.test.tsx`
- `web/src/lib/api.ts`
- `web/src/main.tsx`
- `web/src/routes/AISage.tsx`
- `web/tests/e2e/ai-sage.spec.ts`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented AI Sage as a persistent, user-scoped chat workspace with Postgres-backed chats/messages/evidence, bounded follow-up context, hard-delete retention, route-driven chat history UI, chat search, rename/delete flows, retry handling, and incremental SSE-style response streaming while keeping POST /ai-sage/query backward-compatible.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` AI Sage supports multiple saved chats per authenticated user with create/list/get/rename/delete and ownership isolation.: Implemented in api/app/routers/ai_sage.py and api/app/services/ai_sage.py with persistence in api/app/models/ai_sage_chat.py; covered by api/tests/test_ai_sage_chats.py.
- `pass` Chats persist exact user/assistant text plus per-turn evidence linked to chunk_id/document_id when available.: Evidence rows are stored in ai_sage_turn_evidence via api/app/services/ai_sage.py and migration 048; verified in api/tests/test_ai_sage_chats.py::test_ai_sage_chat_crud_and_message_persistence.
- `pass` Follow-up turns use bounded prior context while still performing grounded retrieval for the current turn.: Context policy is encoded in api/app/services/ai_sage.py::_contextualize_query and stored in assistant metadata; verified by api/tests/test_ai_sage_chats.py::test_ai_sage_follow_up_uses_bounded_context_and_keeps_retrieval_per_turn.
- `pass` Chats are retained for 1 year from the last user message and then hard deleted deterministically.: Retention pruning is implemented in api/app/services/ai_sage.py::prune_expired_ai_sage_chats, scheduled in api/app/main.py, indexed in migrations/048_ai_sage_chat_history.sql, and exercised in api/tests/test_ai_sage_chats.py::test_ai_sage_retention_prunes_expired_chats.
- `pass` The frontend provides a ChatGPT-like persistent workspace with sidebar navigation, deep links, search modal, empty/loading/failed states, and mobile chat access.: Implemented in web/src/routes/AISage.tsx with styling in web/src/App.css and route wiring in web/src/main.tsx; covered by web/src/__tests__/AISage.test.tsx.
- `pass` Assistant responses stream incrementally in the first-version UI and failed turns can be retried.: Added SSE streaming endpoint in api/app/routers/ai_sage.py plus stream consumer in web/src/lib/api.ts and streaming UI state in web/src/routes/AISage.tsx; covered by web/src/__tests__/AISage.test.tsx and web/tests/e2e/ai-sage.spec.ts.
- `pass` Existing one-off AI Sage query behavior remains backward-compatible and new routes are represented in OpenAPI.: Legacy POST /ai-sage/query remains in api/app/routers/ai_sage.py; OpenAPI route coverage is asserted in api/tests/test_contracts.py::test_ai_sage_chat_routes_are_in_openapi.
- `pass` Feature is verifiable through repository make commands and tests cover backend/frontend chat workflows.: Required make gates all passed: api-rebuild, contract-backend, test-backend, api-smoke, lint, typecheck, contract-frontend, test-frontend, e2e, orch-test; dedicated chat tests were added in api/tests/test_ai_sage_chats.py and web/src/__tests__/AISage.test.tsx.

### Risk Flags
- streaming-response-is-sse-chunked-after-grounded-turn-computation
- chat-search-uses-application-side-matching-without-database-fts

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
