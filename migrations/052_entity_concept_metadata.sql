-- Migration 052: Entity and concept metadata tables for RAG
-- Creates the six tables for the entity/concept data layer (Issue 170).

-- Canonical entity registry
CREATE TABLE IF NOT EXISTS rag_entities (
  id             TEXT        PRIMARY KEY,  -- slug: 'amazon', 'berkshire_hathaway'
  entity_type    TEXT        NOT NULL CHECK (entity_type IN ('company','person','author','ticker','other')),
  canonical_name TEXT        NOT NULL,
  metadata_json  JSONB       NOT NULL DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Alias -> entity mapping. One alias belongs to exactly one entity.
CREATE TABLE IF NOT EXISTS rag_entity_aliases (
  entity_id  TEXT    NOT NULL REFERENCES rag_entities(id) ON DELETE CASCADE,
  alias      TEXT    NOT NULL,  -- lowercase normalized
  alias_type TEXT    NOT NULL CHECK (alias_type IN ('name','ticker','short_name','surface_form')),
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,  -- set false to soft-disable ambiguous aliases
  PRIMARY KEY (entity_id, alias)
);
-- Partial UNIQUE enforces one active surface form -> one entity. Inactive aliases can coexist.
CREATE UNIQUE INDEX IF NOT EXISTS rag_entity_aliases_alias_uniq ON rag_entity_aliases(alias) WHERE is_active = TRUE;
CREATE INDEX        IF NOT EXISTS rag_entity_aliases_entity_id  ON rag_entity_aliases(entity_id);

-- Chunk <-> entity annotations
CREATE TABLE IF NOT EXISTS rag_chunk_entities (
  chunk_id     UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
  entity_id    TEXT NOT NULL REFERENCES rag_entities(id) ON DELETE CASCADE,
  surface_text TEXT,
  confidence   REAL NOT NULL DEFAULT 1.0,
  extractor    TEXT NOT NULL,
  PRIMARY KEY (chunk_id, entity_id)
);
CREATE INDEX IF NOT EXISTS rag_chunk_entities_entity_id ON rag_chunk_entities(entity_id);
CREATE INDEX IF NOT EXISTS rag_chunk_entities_chunk_id  ON rag_chunk_entities(chunk_id);

-- Canonical concept registry
CREATE TABLE IF NOT EXISTS rag_concepts (
  id             TEXT PRIMARY KEY,  -- slug: 'mental_models', 'margin_of_safety'
  canonical_name TEXT NOT NULL,
  domain         TEXT,              -- 'investing','psychology','valuation','operations','macro'
  description    TEXT,
  metadata_json  JSONB NOT NULL DEFAULT '{}'
);

-- Alias -> concept mapping. One alias belongs to exactly one concept.
CREATE TABLE IF NOT EXISTS rag_concept_aliases (
  concept_id TEXT    NOT NULL REFERENCES rag_concepts(id) ON DELETE CASCADE,
  alias      TEXT    NOT NULL,  -- lowercase normalized
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (concept_id, alias)
);
CREATE UNIQUE INDEX IF NOT EXISTS rag_concept_aliases_alias_uniq ON rag_concept_aliases(alias) WHERE is_active = TRUE;
CREATE INDEX        IF NOT EXISTS rag_concept_aliases_concept_id ON rag_concept_aliases(concept_id);

-- Chunk <-> concept annotations
CREATE TABLE IF NOT EXISTS rag_chunk_concepts (
  chunk_id    UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
  concept_id  TEXT NOT NULL REFERENCES rag_concepts(id) ON DELETE CASCADE,
  surface_text TEXT,
  confidence  REAL NOT NULL DEFAULT 1.0,
  extractor   TEXT NOT NULL,
  PRIMARY KEY (chunk_id, concept_id)
);
CREATE INDEX IF NOT EXISTS rag_chunk_concepts_concept_id ON rag_chunk_concepts(concept_id);
CREATE INDEX IF NOT EXISTS rag_chunk_concepts_chunk_id   ON rag_chunk_concepts(chunk_id);
