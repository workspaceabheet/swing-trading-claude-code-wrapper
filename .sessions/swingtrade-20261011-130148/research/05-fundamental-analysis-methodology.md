# Research: Fundamental-Analysis Methodology for Short Swing Trades

## Primary catalysts (days to ~2 weeks)
Quarterly results (5-20% same-session moves), block deals, M&A announcements, promoter pledging/buying/selling, SEBI enforcement orders, RBI/regulatory policy changes. Rough predictive-frequency ranking: quarterly earnings > M&A > block deals > promoter actions.

## Company vs. sector weighting
Dual-screen approach: filter by sector momentum first (~60% of conviction), then apply company-specific catalyst within bullish sectors (~40%). Avoid longing a stock against a down sector unless the catalyst is existential.

## Folding in macro counterweight
Treat macro as a **sector-level modifier, not a stock-level veto**: green macro = no adjustment; yellow = reduce conviction ~15-20%; red = reduce ~30%. Avoids macro noise either dominating or being ignored.

## Proposed red/yellow/green scoring rubric (0-100 weighted)
| Component | Weight | Notes |
|---|---|---|
| Catalyst strength | 40% | 0-10 weak / 20-30 moderate / 30-40 major |
| Sector momentum | 35% | negative/neutral/positive 4-week trend |
| Macro risk modifier | 25% | green=25, yellow=20, red=15 |

Thresholds: **Green 70-100** (initiate, hold 1-2 weeks) · **Yellow 50-69** (smaller size, tighter stop, 5-7 day hold) · **Red <50** (avoid).

*Orchestrator note: this rubric is a solid starting draft for the spec but should be treated as a v1 heuristic to refine after seeing real output, not a fixed formula.*

## Target price / hold-duration heuristics (no paid data)
- Volatility-based: use ~20-day ATR, target ~1.5-2.5x volatility, hold ~5-7 days or until target/volatility mean-reversion.
- Free analyst consensus (Investing.com, TipRanks, MarketScreener) as a sanity check only — lags paid sources by 1-3 weeks and carries sell-side bias.
- Exit discipline suggested: partial exit at target, trailing stop on remainder.

## Known pitfalls to guard against (India-specific)
- Pump-and-dump small/mid-caps: avoid low daily-volume (e.g. <₹50cr), no institutional ownership, sudden promotional chatter.
- News lag: retail is typically minutes behind institutions on earnings reactions.
- Stale/duplicated news: cross-check NSE announcements for whether a catalyst was already priced in weeks earlier.
- Liquidity traps: sharp mid-cap rallies can face exit walls — keep targets realistic.
- Social-media/Telegram/YouTube "tip" chatter: explicitly exclude as a signal source — cross-reference only against NSE/BSE disclosures and the vetted RSS stack from [[01-free-indian-news-data-sources]].
