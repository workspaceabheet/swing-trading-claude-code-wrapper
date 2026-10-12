# Research: Claude Code Headless/CLI Engine Design

## Structured JSON output
`claude -p --output-format json` combined with `--json-schema` is well-documented and reliable; the model's output is validated against the schema and returned in a `structured_output` field, alongside `result`, `is_error`, `session_id`, `total_cost_usd`. Reliability described as very high with clear system prompts.

## Web fetching in headless mode
Built-in `WebSearch` (index-backed search) + `WebFetch` (single-page fetch, no JS rendering) tools cover this with no extra setup. Pattern: search → pick top links → fetch → parse. Cost is just standard input-token fees for fetched content.

## Cost estimate
- One sweep (search + shortlist 5-10 stocks) ≈ 50-100k tokens (~$0.20-0.40 on Sonnet).
- Ten deep-dives ≈ 30k tokens each (~$0.60-1.20 total) at base rates.
- Prompt caching cuts repeated-context cost 2.7-5.3x on same-day re-runs (cache reads ~90% cheaper than fresh input; default TTL ~5 min, so needs orchestration that re-invokes within that window to benefit, or deliberate cache-friendly structuring).
- **Practical full daily run estimate: ~$2-4 on Sonnet with caching; ~$6-10 on Opus** (note: given the user's informal/no strict cost focus, Sonnet is a reasonable default; this is a rough estimate, not a guarantee).

## Chaining invocations
- **CLI pattern**: write JSON to disk, invoke `claude -p` per stock — works but requires manual file I/O/error handling.
- **Agent SDK pattern**: one orchestrator + per-stock subagents, subagents get sweep output + ticker as input, parallel execution supported, built-in retry on transient errors. Agent describes this as the superior pattern for this pipeline shape.

## Agent SDK vs CLI headless
- **CLI pros**: simplest for one-off/occasional manual runs, no SDK boilerplate.
- **CLI cons**: custom retry/error handling and file-plumbing needed for a multi-stage pipeline; no built-in subagent orchestration or schema-guaranteed output.
- **SDK pros**: subagent orchestration with context isolation, parallel per-stock analysis, type-safe schemas (Pydantic/Zod) for guaranteed structured output, session persistence, built-in retry, cleaner cost tracking.
- **SDK cons**: more setup complexity (Python 3.10+/TS), another dependency to learn.
- Agent's verdict: SDK is the better architectural fit for a multi-stage, structured-output pipeline like this.

*Orchestrator note: this is directionally useful but not a final decision — the user explicitly confirmed "headless Claude Code CLI runs" as the preferred engine design during intake. This tradeoff should be revisited explicitly with the user at the Stage 3 clarification step rather than silently switched to the SDK.*

## Same-day re-run / "nothing changed" detection
Recommended: programmatic hash/compare of sweep results (ticker list, key news items/dates, price deltas) before invoking Claude at all — skip the LLM call entirely if the hash matches the prior run. Near-zero cost, trivial to implement; prefer this over a prompt-based "diff it yourself" instruction.

## Rate limits / stability
No documented hard per-minute limit for headless invocations as of the research; Claude Code has added automatic retry for transient rate-limit errors. Ten sequential invocations with ~1-2s spacing between them is described as safe.

## Recommendation from this research
Architecturally prefers Agent SDK orchestrator + per-stock subagents, Sonnet by default (escalate to Opus if quality insufficient), prompt caching on the reused system prompt/sweep context, and hash-based re-run skip logic — **but flag the CLI-vs-SDK call explicitly to the user since it conflicts with their stated preference for plain headless CLI invocations.**
