---
id: 158
title: AI Sage Result Context And Full Document Reader
status: todo
priority: medium
owner: codex
created_at: 2026-04-28
tags:
  - ai-sage
  - rag
  - ux
  - reader
---

# Summary

AI Sage results currently show passage snippets and optional limited adjacent context. This is useful but insufficient when a user finds an interesting passage and wants to understand the full surrounding argument.

We need a generic result-reader flow that lets a user:

1. expand adjacent chunk context reliably from an AI Sage result
2. jump from an AI Sage result into a proper document reader
3. optionally open the full source document/work at the exact passage anchor

# Problem

- Some useful passages are too compressed to interpret safely in isolation.
- Adjacent context is currently opportunistic, not guaranteed.
- The user should be able to move from “interesting snippet” to “read the full talk / letter / transcript” without doing a separate manual search.
- This must work generically across authors and document classes, not just for Charlie Munger.

# Scope

Implement a result-context flow for AI Sage that supports:

- stable `document_id` / `chunk_id` linkage in evidence payloads
- adjacent-context expansion for every ranked corpus result
- link from result card to Author Library reader
- optional passage anchor / scroll targeting inside the reader
- ability to open the full document/work, not just the snippet

# Acceptance Criteria

- Every ranked corpus result in AI Sage can expose adjacent context from the same document.
- Every ranked corpus result can open the relevant document in the Author Library reader.
- The reader can land near the relevant chunk or highlight the matching passage when feasible.
- The flow is generic across future authors and corpus types.
- No author-specific hardcoding.
- Existing AI Sage and Author Library behavior remains backward-compatible.

# Notes

- This issue is about reader/context UX and payload support.
- It is not about retrieval ranking quality itself.
- It should build on the existing author-library document reader rather than inventing a second reader stack.
