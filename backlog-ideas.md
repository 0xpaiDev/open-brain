# Backlog Ideas

Future considerations that are not currently prioritized.

---

## Cost Optimization

### Pre-LLM Dedup Check
Before sending a raw memory to the Anthropic extraction pipeline, check if the text is a near-duplicate of a recently ingested memory. If it is, skip the LLM call and either link to the existing memory or discard.

**Why**: During development/testing the same text gets re-submitted repeatedly. Even in production, users may ingest similar content. Each LLM call costs ~$0.001, so dedup at the queue level is a cheap guard.

**Approach**: Hash the normalized text (`sha256(normalize(raw_text))`). Store the hash on `raw_memory`. Before enqueueing (or at the start of `process_job`), query for an existing `raw_memory` with the same hash created within a recent window (e.g. 7 days). If found, mark the queue row as `done` and link to the existing `memory_item`.

**Tradeoff**: Exact-hash dedup only catches identical text. Fuzzy dedup (embedding similarity before embedding exists) is a chicken-and-egg problem — skip for now.
