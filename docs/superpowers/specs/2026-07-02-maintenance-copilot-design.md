# AI Maintenance Knowledge Copilot — Pilot Module Design

**Date:** 2026-07-02
**Module:** `maintenance_copilot`
**Status:** Design approved; pending spec review before implementation planning.
**Source brief:** P1: Concept Brief and Brainstorm (MCC + Engineering Teams, 2026-07-01).

## 1. Purpose

Build a working pilot of the AI Maintenance Knowledge Copilot as an Atria
module. The copilot helps the Maintenance Control Center (MCC) and engineering
teams **retrieve, validate, and cross-reference** aircraft maintenance
documentation (AMM, MEL, CDL, TSM) faster and with fewer errors. It is strictly
**advisory**: it accelerates search and flags inconsistencies but never issues a
dispatch decision. A licensed engineer stays in the loop for every decision.

This pilot implements the five stated pilot-scope items from the brief:

1. Retrieve relevant maintenance procedures from technical manuals.
2. Validate defect entries against approved maintenance documentation.
3. Recommend the relevant AMM / MEL / CDL / TSM reference for a write-up.
4. Highlight potential inconsistencies before engineer submission.
5. Provide explainable reasoning with source references (cross-cutting).

## 2. Scope decisions (locked)

- **Fidelity:** working pilot with real vector embeddings + LLM synthesis;
  every answer is cited.
- **All models run locally** so OEM manual content never leaves the
  environment (addresses the data/IP risk in the brief).
  - **Chunking:** Chonkie `SemanticChunker` (+ `OverlapRefinery`).
  - **Embeddings:** HuggingFace model served locally via Text Embeddings
    Inference (TEI), OpenAI-compatible `/v1/embeddings`.
  - **Synthesis + KG extraction LLM:** self-hosted local chat model
    (vLLM, OpenAI-compatible `/v1/chat/completions`).
- **Vector store:** Qdrant, as a local docker-compose service.
- **Knowledge graph:** Neo4j, as a local docker-compose service.
- **KG population:** LLM-assisted extraction, guarded by mandatory provenance +
  confidence + `unverified`/`engineer_confirmed` status on every node and edge.
- **Corpus:** synthetic sample AMM/MEL/CDL/TSM manuals (no IP/licensing risk);
  real manuals swap in later via config.
- **Model-provider config:** module-local only. Not wired into Atria's global
  provider system.
- **Module status on disk:** `maintenance_copilot` is the only module; the five
  prior modules were left deleted per the user's decision.

Chosen module structure: **Approach A** — a self-contained Python CLI in the
module folder that orchestrates the four local sidecar services, with Chonkie
used only for chunking and the retrieval/citation/guardrail logic hand-rolled
and explicit (auditability is the priority in a safety-critical context).

## 3. Architecture

```
                       ┌─────────────────────────────────────────┐
   engineer / MCC ───▶ │  copilot.py  (module CLI, in Atria)       │
   (via Atria agent    │  ingest · index · graph · query · validate│
    or dashboard)      └───┬───────┬───────────┬──────────┬────────┘
                           │       │           │          │
              chunk (Chonkie)  embed        vector      graph
                           │       │        search    reason
                           ▼       ▼           ▼          ▼
                    ┌──────────┐ ┌──────┐ ┌────────┐ ┌────────┐
                    │ (in-proc │ │ TEI  │ │ Qdrant │ │ Neo4j  │
                    │  Chonkie)│ │embed │ │vectors │ │ graph  │
                    └──────────┘ └──────┘ └────────┘ └────────┘
                                     ▲                    ▲
                                     └──── local LLM ─────┘
                                       (vLLM: synthesis
                                        + KG extraction)
```

### 3.1 Sidecar services (docker-compose)

- **`tei`** — `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`,
  model `Qwen/Qwen3-Embedding-0.6B`, mounted data volume, `/v1/embeddings`.
  CPU image for dev; GPU image (`cuda-1.9`) swappable.
- **`qdrant`** — official Qdrant image; collection `manual_chunks`.
- **`neo4j`** — official Neo4j image; bolt endpoint; the aviation knowledge
  graph.
- **`copilot-llm`** — local chat model via vLLM, OpenAI-compatible. Used for
  answer synthesis and KG extraction. GPU-dependent, with a documented fallback
  (point the `synthesis`/`kg_extract` roles at the existing Qwen proxy
  `base_url`) for machines without a GPU.

All four are wired into `docker-compose.dev.yml` (and `docker-compose.yml`).
Everything the module writes lives under the module's own `data/` dir
(gitignored).

### 3.2 Module-local model-provider layer

A module-local config (e.g. `config.py` + a `models.toml` / module `.env`) maps
four **roles** to endpoints, resolved through one thin OpenAI-compatible client:

- `chunk_embed` — embedding model used by Chonkie's `SemanticChunker`
  (may reuse TEI, or a small in-process model).
- `index_embed` — TEI embedding model used for indexing/retrieval.
- `synthesis` — chat LLM that composes cited answers.
- `kg_extract` — chat LLM that extracts graph entities/relationships (may be a
  different/stricter model than `synthesis`).

Each role entry is `{provider, model, base_url, api_key}`. Swapping any model
per feature, or falling back to the proxy on a no-GPU box, is a config change —
no branching at call sites. This layer is self-contained; it does not depend on
or modify Atria internals.

## 4. Ingestion pipeline & data model

Pipeline runs one document at a time: `ingest → index → graph`.

1. **Parse** — read each source (synthetic sample AMM/MEL/CDL/TSM `.md`/`.pdf`).
   PDFs → text via `pdftotext`/`pypdf` (reused from the prior rag engine). Each
   document carries fixed front-matter: `doc_type`, `title`, `revision`,
   `effective_date`.
2. **Chunk** — Chonkie `SemanticChunker` (embedding model = `chunk_embed` role)
   with `OverlapRefinery`. Each chunk retains `text`, `token_count`, and char
   offsets; these become the citation anchor
   (`source · rev · page/§ · chunkN`).
3. **Embed + index** — embed each chunk via TEI (`index_embed`), upsert into
   Qdrant `manual_chunks` with payload: `doc_type`, `ata_chapter`, `revision`,
   `page`, `mel_category`, `chunk_id`, `text`. Payload fields are the filter
   keys for version-aware, scoped retrieval.
4. **Graph extract** — for each chunk, the `kg_extract` LLM returns a strict
   JSON list of `{entities, relationships}`, written to Neo4j with provenance +
   confidence (below). This is the only non-deterministic step and is the most
   heavily guarded.

### 4.1 Qdrant record

Vector + payload (above). Retrieval = cosine top-k, optionally filtered
(e.g. `revision = current` for version-awareness, or `ata_chapter = 32`).

### 4.2 Neo4j graph schema

**Nodes:** `Document{doc_type,title,revision,effective_date}`,
`ATAChapter{code}`, `Part{part_no}`, `MELItem{item_id,category}`,
`CDLItem{item_id}`, `FaultCode{code}`, `Procedure{task_id,title}`,
`Defect{id,description}` (historical; populated when defect logs are added).

**Edges:** `(:Procedure)-[:IN_CHAPTER]->(:ATAChapter)`,
`(:MELItem)-[:RELIEVES]->(:Defect)`,
`(:MELItem)-[:REQUIRES]->(:Part|Tooling|Placard)`,
`(:Defect)-[:SIMILAR_TO]->(:Defect)`,
`(:FaultCode)-[:TROUBLESHOT_BY]->(:Procedure)`,
`(:Document)-[:MENTIONS]->(entity)`.

**Provenance + trust props on every node and edge:** `source_doc`, `revision`,
`page`, `extracted_by` (model id), `confidence` (0–1),
`status` (`unverified` | `engineer_confirmed`). Elements below the confidence
threshold or still `unverified` are semantically/visually flagged and never
presented as fact — they are "AI-suggested links pending review." An engineer
confirming a link flips `status` and is logged to the audit trail.

### 4.3 Idempotency & version-awareness

Re-ingesting a document at the same revision replaces its chunks/nodes. A new
revision is added alongside and marked current; older revisions stay queryable,
but retrieval defaults to the current revision (the version-awareness
guardrail).

## 5. CLI capabilities (pilot scope)

`copilot.py` subcommands. Each returns structured JSON (for the Atria agent and
dashboard) and never phrases output as a decision.

- **`query "<defect or question>" [--ata NN] [--k 5]`** — *Retrieve.* Qdrant
  top-k (filtered to current revision by default) → `synthesis` LLM composes a
  plain-language answer grounded only in retrieved chunks, each claim tagged
  with its citation anchor. Related graph context (e.g. MEL items for that ATA
  chapter) pulled from Neo4j and offered alongside.
- **`validate <defect_write_up.json|->`** — *Validate.* Checks a draft defect
  entry against approved docs: does the cited AMM task / MEL item exist at the
  current revision? Returns pass/fail per assertion with the supporting
  citation.
- **`recommend-refs "<defect text>"`** — *Recommend references.* Ranked
  AMM/MEL/CDL/TSM references for a write-up, each with citation + confidence.
- **`check <defect_write_up.json|->`** — *Flag inconsistencies.* Cross-checks
  dispatch condition vs cited MEL item, missing placard/tooling/interval (via
  the graph's `REQUIRES` edges), and classification vs similar historical
  defects. Emits flagged inconsistencies with severity + source — advisory only.
- **Explainability** is a cross-cutting property: all output carries citations;
  no path returns an ungrounded claim.

Infra subcommands: `ingest`, `index`, `graph`, `list`, `reset`, `health`
(checks all four sidecars).

## 6. Guardrails (enforced in code, not prompts alone)

- **Mandatory citation** — synthesis output is post-validated; any sentence
  without a resolvable citation anchor is dropped and the response is marked
  low-confidence.
- **Confidence threshold** — retrievals/edges below `min_confidence` route to
  "manual review," not surfaced as answers.
- **Advisory-only framing** — fixed disclaimer on every response; no command
  emits an approval/dispatch verdict.
- **Version-aware** — retrieval defaults to current revision; superseded hits
  are labeled.
- **Audit trail** — every query, recommendation, and engineer confirmation is
  appended to `data/audit.log.jsonl` with the doc/revision/page used (the §4.5
  traceability item from the brief).

## 7. Dashboard

`dashboard.html` keeps the P1 brief view and gains three live tabs:

- **Query** — ask a question, see the cited answer.
- **Graph** — Neo4j subgraph for an entity; `unverified` edges rendered dashed.
- **Audit** — recent citations and engineer confirmations.

Reads via the module's existing dashboard bridge.

## 8. Testing (unit + real e2e, per CLAUDE.md)

**Unit** (sidecars mocked):
- chunking offsets → citation anchors resolve correctly;
- Qdrant payload filtering (revision / ATA chapter);
- graph provenance/`status` transitions (`unverified → engineer_confirmed`);
- citation post-validation drops uncited sentences;
- version-awareness selects the current revision.

**Real end-to-end** (live services):
- bring up the compose stack; `ingest` the synthetic manuals;
- exercise all five commands against live TEI / Qdrant / Neo4j / LLM;
- assert answers are cited, an invalid MEL reference fails `validate`, and a
  mismatched dispatch condition is flagged by `check`.

## 9. Success metrics (from the brief, for later evaluation)

- Average time to locate a correct AMM/MEL/CDL/TSM reference.
- Reference error rate before vs. after.
- Inconsistencies caught pre-submission.
- Engineer adoption / query volume.
- Citation accuracy (spot-audit pass rate).

## 10. Out of scope for this phase

- Real OEM manual ingestion (pending legal/OEM approval).
- Voice query interface; fleet-wide pattern detection; OCR of paper logbooks.
- Integration with MRO/CMS systems (AMOS, TRAX, Ultramain).
- Historical defect-log ingestion (schema is provisioned; population deferred).
- Regulatory/airworthiness sign-off workflow beyond the advisory-only framing.

## 11. Open questions / risks

- **Local LLM footprint:** `copilot-llm` (vLLM) realistically needs a GPU;
  the CPU/proxy fallback is documented but degrades data isolation if the proxy
  is used for real content.
- **Embeddings endpoint:** the existing Qwen proxy is chat-only, so embeddings
  must come from local TEI (confirmed direction).
- **KG extraction quality:** LLM-extracted edges start `unverified`; the value
  of the graph depends on engineer confirmation throughput and the confidence
  threshold tuning.
- **Chonkie semantic chunking cost:** semantic chunking calls an embedding
  model per document; batch/througput to be validated on the sample corpus.
