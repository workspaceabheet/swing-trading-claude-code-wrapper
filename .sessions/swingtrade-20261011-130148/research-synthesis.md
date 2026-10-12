# Research Synthesis: Local Swing-Trading Helper for NSE/BSE

Consolidated from 7 research files (zero-budget constraint; no paid APIs; no Kite Connect API).

## 1. Data Sources (news, prices, fundamentals)

**Well-supported findings.** A genuinely free, low-risk stack exists. Official RSS feeds (Moneycontrol, Economic Times, Business Standard, Mint) cover NSE/BSE news with minutes-to-hours latency and high reliability. NSE's official daily **Bhavcopy** CSV gives free EOD OHLC/volume with no stated rate limit — effectively zero risk at daily polling. **Screener.in** is the best free fundamentals source (P/E, balance sheet, quarterly results). **Trading Economics** provides free macro context (economic calendar, 196 countries).

The recommended **minimal 3–5 source stack**: Moneycontrol RSS + NSE Bhavcopy + Screener.in + Trading Economics, optionally + one more RSS feed for diversification. All free, no signups, low legal risk at 1-4 requests/day.

**Avoid:** Google News RSS scraping — Google's ToS bans automated scraping of it even though the feed looks public; this is flagged as higher-risk than the publisher-direct alternative, which is just as useful.

**Lower-confidence note:** specific feed URLs and exact scraping etiquette (delay windows, user-agent choices) are general best-practice guidance, not verified against each site's current robots.txt.

## 2. Zerodha Kite Without the Paid API

**Well-supported, unambiguous finding:** scraping/replicating Kite Web via unofficial libraries **violates Zerodha's ToS (Section 16.3)** explicitly and is not a legal gray zone — risk is account suspension, and Zerodha actively monitors for anomalous session/request patterns. This holds even for personal, non-commercial use.

**Recommendation carried into the decision points below:** drop Kite entirely for v1. Manual CSV export from Kite Console (holdings, trade book) remains fine as an occasional, non-automated input. For live reference prices, the **Upstox API** (free, official, no subscription) is the recommended fallback if/when live pricing becomes important — Angel One SmartAPI and Dhan are free alternatives too. For a once-daily advisory tool, the research found **no material gap** from dropping Kite: historical OHLC comes from yfinance/Bhavcopy, and live intraday ticks aren't needed for this use case.

## 3. Engine Design: Headless CLI vs. Agent SDK — the key open tension

**This is the central decision point for Stage 3 and is deliberately left unresolved here.**

During intake, the user specified **headless Claude Code CLI runs** (`claude -p`) as the preferred engine design. The engine-design research, however, concludes that the **Claude Agent SDK with an orchestrator + per-stock subagent pattern is architecturally superior** for this specific pipeline shape — citing context isolation per stock, native parallel execution, type-safe schema-guaranteed output (Pydantic/Zod), built-in retry, and cleaner cost tracking, versus the CLI approach's need for manual JSON file-plumbing and custom retry/error handling across multiple sequential `claude -p` invocations.

Both approaches are viable; `claude -p --output-format json --json-schema` is well-documented and reliable either way. **This tradeoff must be put back to the user explicitly at Stage 3** rather than resolved by research — the user's original instruction was clear and should not be silently overridden.

**Supporting findings (well-supported):**
- Cost estimate: ~$2-4/day on Sonnet with prompt caching, ~$6-10 on Opus for a full sweep + 10 deep-dives. **This is explicitly flagged by the research as a rough estimate, not a guarantee** — token-cost figures are the softest numbers in this whole research set.
- Prompt caching can cut repeated-context cost 2.7–5.3x, but only within the ~5-minute default cache TTL — needs run structuring to realize the benefit.
- No documented hard rate limit for sequential headless invocations; ~1-2s spacing between 10 sequential calls is described as safe.
- A cheap, high-value addition regardless of CLI/SDK choice: hash/compare sweep results before invoking the LLM at all, to skip (near-zero cost) re-runs where nothing changed.

## 4. Local UI

**Well-supported, low-complexity recommendation:** static HTML + vanilla JS reading local flat JSON files via `fetch` — no Node/React/build step, no database. One JSON file per run (`runs/<timestamp>.json`) plus a `runs/latest.json` pointer; a lightweight classless CSS framework (Pico CSS, ~3KB) for card styling. v1 scope is **read-only**: view latest run as a ranked card grid + browse history; no "trigger run" button (that's a reasonable v2 add). A versioned JSON schema (shown in the UI research file) is recommended for forward compatibility. Estimated build time: a couple of hours — consistent with "simple local tool" framing.

## 5. Fundamental-Analysis Methodology

**Reasonably well-supported heuristics**, explicitly framed as a draft to validate against real output rather than a final formula:

- **Catalyst hierarchy** (days to ~2 weeks horizon): quarterly earnings > M&A > block deals > promoter actions, roughly in that predictive order.
- **Dual-screen weighting**: sector momentum (~60% of conviction) filtered first, then company catalyst (~40%) — avoid longing against a down sector unless the catalyst is existential.
- **Macro as modifier, not veto**: green macro = no change, yellow = -15-20% conviction, red = -30%.
- **Proposed v1 scoring rubric** (0-100): Catalyst strength 40%, sector momentum 35%, macro modifier 25%, with thresholds Green 70-100 / Yellow 50-69 / Red <50. **This is explicitly a draft heuristic for Stage 3 validation, not a settled formula.**
- **Target/hold-duration**: ATR-based (~1.5-2.5x 20-day volatility, 5-7 day hold), free analyst consensus as a sanity check only (lags paid sources 1-3 weeks, sell-side bias).
- **India-specific pitfalls to guard against**: pump-and-dump small/mid-caps (low volume, no institutional ownership), news lag vs. institutions, stale/already-priced-in catalysts, mid-cap liquidity traps, and excluding social-media/Telegram "tip" chatter as a signal source entirely.

## 6. Legal & Regulatory

**Well-supported:** as a strictly personal, non-distributed, non-monetized tool, **no SEBI Research Analyst/Investment Adviser registration is required** — registration is triggered by giving advice to others for consideration, which this tool never does. Scraping dynamic pages from Moneycontrol/NSE/BSE/ET technically breaches their ToS even at low frequency, but enforcement risk at 1-3 req/day is low-to-moderate (enforcement targets high-volume commercial scraping); preferring official RSS/Bhavcopy over dynamic-page scraping further reduces this. A recommended disclaimer boilerplate is provided for every run's output. (General informational research only, not legal advice.)

## 7. Prior Art (GitHub)

Several related projects exist (ContextCraft: Claude + Kite Connect for execution; AI Trading Claude: 5 parallel Claude agents producing PDF reports; NSE Trading Skills: pure technical analysis; MarketGPT: strong news-RAG but outputs chat, not signals; Trade Bot: closest architectural pattern with a feedback-validation loop, but targets Vietnamese equities). **Notable differentiator**: no existing project combines a **local headless engine + India (NSE/BSE) focus + a hard 10-idea cap + mandatory citations + red/yellow/green confidence** in one pipeline. This specific combination appears to be a genuine gap worth mentioning to the user as a differentiator, not just a reimplementation of something that already exists.

---

## Decision Points for Stage 3 Clarification

1. **CLI vs. Agent SDK** (see Section 3) — the one open tension; needs explicit user re-confirmation or override.
2. **Kite for v1**: drop entirely, vs. plan to add the free Upstox API later for live prices/holdings.
3. **Exact minimal source stack**: confirm the specific 3-5 sources (Moneycontrol RSS + Bhavcopy + Screener.in + Trading Economics, +/- one more) before building.
4. **Scoring rubric**: the red/yellow/green weighted formula in Section 5 is a v1 draft — validate or adjust after seeing real output, not lock in now.
5. **Data retention policy**: recommended hard constraint — store only headline/source/URL/short snippet, never full article text (copyright risk mitigation).
6. **Product safeguards**: recommended hard constraints — 10-idea cap, mandatory citation per idea, no-auto-execution, personal-use disclaimer on every output.
7. **UI stack**: confirm static HTML/JS + flat JSON files, no DB, no build step, read-only v1 (no "run now" button).

## Key Risks & Open Questions

- **Token-cost estimates are rough** ($2-4/day Sonnet, $6-10/day Opus) — not a guarantee, could vary with actual sweep size/caching behavior.
- **ToS exposure** remains real (if low-enforcement-risk) for any scraping beyond official RSS/Bhavcopy/Upstox channels — worth revisiting if usage frequency ever increases.
- **Scoring rubric is unvalidated** against real market outcomes; no backtesting has been done yet (Trade Bot's feedback-validation-loop pattern is a candidate for later iteration).
- **News-to-signal pipeline design** (how sweep output flows into per-stock deep-dive and then into the rubric) is sketched but not fully specified — this is squarely Stage 3/4 territory.
- **Pump-and-dump / stale-news pitfalls** require concrete filtering logic (volume thresholds, institutional-ownership checks) that hasn't been designed yet, only flagged as a risk category.
