# Learning Library — Bulk Import Template

Use this document when preparing a JSON payload for `POST /v1/learning/import`.
Paste the LLM prompt and schema into Claude.ai (or ChatGPT), paste your source
material, and copy the returned JSON into the import page.

---

## Schema Reference

### Top-level

| Field | Type | Required | Max | Notes |
|---|---|---|---|---|
| `topics` | array of Topic | yes | 50 | Min 1 topic per request |

### Topic

| Field | Type | Required | Max | Notes |
|---|---|---|---|---|
| `name` | string | yes | 120 | Case-insensitive dedup against existing topics |
| `description` | string | no | — | Optional overview |
| `depth` | `"foundational"` \| `"deep"` | no | — | Default `"foundational"` |
| `sections` | array of Section | no | 20 | Default empty |
| `material` | Material object | no | — | Source text; omit if none |

**Note:** `position` is forbidden. The server auto-assigns position = array index.

### Section

| Field | Type | Required | Max |
|---|---|---|---|
| `name` | string | yes | 120 |
| `items` | array of Item | no | 20 |

### Item

| Field | Type | Required | Max |
|---|---|---|---|
| `title` | string | yes | 240 |

### Material

| Field | Type | Required | Max | Notes |
|---|---|---|---|---|
| `content` | string | yes | unlimited | Markdown body (source text verbatim) |
| `source_type` | string | no | 40 | `article` / `note` / `transcript` / `book_excerpt` / `other` |
| `source_url` | string | no | 2048 | Original URL if applicable |
| `source_title` | string | no | 240 | Title of source document |
| `metadata` | object | no | — | Arbitrary JSON for extra provenance |

---

## Examples

### Minimal (1 topic, 2 sections, 3 items each, no material)

```json
{
  "topics": [
    {
      "name": "PostgreSQL Indexing",
      "depth": "foundational",
      "sections": [
        {
          "name": "B-tree indexes",
          "items": [
            {"title": "Understand when B-tree outperforms sequential scan"},
            {"title": "Read EXPLAIN ANALYZE output for index scans"},
            {"title": "Compare index vs covering index on a real table"}
          ]
        },
        {
          "name": "GIN and GiST indexes",
          "items": [
            {"title": "Identify use cases for GIN (full-text, JSONB, arrays)"},
            {"title": "Build a GIN index on a JSONB column"},
            {"title": "Compare GiST vs GIN for tsvector full-text search"}
          ]
        }
      ]
    }
  ]
}
```

### Full (1 topic with description, material, and metadata)

```json
{
  "topics": [
    {
      "name": "pgvector Embeddings",
      "description": "Using pgvector for vector similarity search in PostgreSQL",
      "depth": "deep",
      "sections": [
        {
          "name": "Setup and schema",
          "items": [
            {"title": "Install the pgvector extension via CREATE EXTENSION"},
            {"title": "Define a vector(1024) column in SQLAlchemy"},
            {"title": "Understand the .with_variant(JSON(), 'sqlite') compat pattern"}
          ]
        },
        {
          "name": "Querying",
          "items": [
            {"title": "Write a cosine similarity query with <=> operator"},
            {"title": "Add an HNSW index and benchmark latency"},
            {"title": "Understand the tradeoff between HNSW and IVFFlat"}
          ]
        },
        {
          "name": "Integration",
          "items": [
            {"title": "Embed text with Voyage AI and store vectors"},
            {"title": "Implement hybrid search (keyword + vector reranking)"},
            {"title": "Profile GUC settings for vector scan performance"}
          ]
        }
      ],
      "material": {
        "content": "# pgvector Deep Dive\n\npgvector adds a `vector` type to PostgreSQL...\n\n## Installation\n...",
        "source_type": "article",
        "source_url": "https://github.com/pgvector/pgvector",
        "source_title": "pgvector README",
        "metadata": {"author": "Andrew Kane", "year": 2024}
      }
    }
  ]
}
```

---

## Copy-pasteable LLM Prompt

```
You are a curriculum designer for the Open Brain Learning Library.
Convert the source material below into a JSON document matching the schema.
Output ONLY valid JSON, no prose, no code fences.

Constraints:
- 3–7 items per section, max
- Item titles are concrete actions ("Read X", "Implement Y", "Compare A vs B")
- depth = "foundational" for prerequisites/basics, "deep" for advanced topics
- Preserve the source verbatim in topic.material.content (full text, not a summary)
- Do NOT include any "position" field — the server assigns positions automatically
- Do NOT wrap output in markdown code blocks

Schema:
{
  "topics": [
    {
      "name": "string (required, max 120 chars)",
      "description": "string (optional)",
      "depth": "foundational | deep",
      "sections": [
        {
          "name": "string (required, max 120 chars)",
          "items": [
            {"title": "string (required, max 240 chars)"}
          ]
        }
      ],
      "material": {
        "content": "string (required — paste the full source text here)",
        "source_type": "article | note | transcript | book_excerpt | other",
        "source_url": "string (optional)",
        "source_title": "string (optional)"
      }
    }
  ]
}

Source material:
<user_input>
{paste your article, chapter, or notes here}
</user_input>
```

---

## Operational Notes

- **Dry run first.** Always call `POST /v1/learning/import?dry_run=true` to preview
  counts and name collisions before committing.
- **Dedup is case-insensitive.** "pgvector" and "Pgvector" are treated as the same
  topic. Colliding topics are skipped with a `name_collision` warning; non-colliding
  topics in the same payload are still created.
- **Safe to re-run.** Running the same payload twice is safe — the second run skips
  all topics (all collide). No duplicates are created.
- **Rate limit.** The import endpoint allows 5 requests per minute. Dry runs count
  against this limit.
- **Size limits.** Max 50 topics per request, 20 sections per topic, 20 items per
  section. Material content is unlimited (plain TEXT in PostgreSQL), but very large
  payloads (100KB+) may render slowly on mobile.
- **No `position` field.** The server auto-assigns `position = array index` for
  topics, sections, and items. Any payload that includes `position` is rejected
  with HTTP 422.
