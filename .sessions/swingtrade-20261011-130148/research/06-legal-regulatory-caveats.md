# Research: Legal, Regulatory, and Practical Caveats
(General informational research only — not legal advice)

## SEBI framework
SEBI Research Analyst / Investment Adviser registration is triggered by giving advice to others for consideration (payment or public/client distribution). A personal-use-only, non-distributed, non-commercial tool is exempt — no registration required, as long as it stays personal and never shared/monetized.

## ToS / scraping risk across sources
| Source | ToS stance | Enforcement risk |
|---|---|---|
| Moneycontrol | Prohibits automated scraping/redistribution | IP block, cease-and-desist if detected |
| NSE/BSE | Explicit ban on systematic/automated collection | IP block, account termination (official APIs cost ~₹3L/year) |
| Economic Times | Prohibits scraping/unauthorized access | Rate-limiting, IP ban |
| Zerodha | Official APIs only | Account restriction/API revocation (see [[02-zerodha-kite-without-api]]) |

Low-frequency personal use (1-3 req/day) is low-to-moderate realistic risk (enforcement targets high-volume commercial scraping), but it's still a technical ToS breach. Prefer official RSS feeds and NSE's free Bhavcopy download over scraping dynamic pages.

## Disclaimer language (recommended boilerplate)
"This tool is for personal informational use only and does not constitute investment advice or personalized recommendations. It is an analytical aid for my own research and decision-making. I am not a registered investment adviser or research analyst. All investment decisions are my own responsibility. The tool has no access to my brokerage account and places no trades."

## Data retention / copyright
- Storing full article text = copyright infringement risk (original creative expression).
- Storing only headline + source + URL + a short (~1-2 sentence) snippet = low risk, standard fair-use pattern.
- **Recommendation: never persist full article bodies — store headline/source/URL/snippet + citation link only.**

## Practical safeguards (recommended, map directly to product requirements)
- Hard cap of ≤10 ideas per run.
- Mandatory citation/source link on every idea.
- Prominent "not investment advice, personal use only" disclaimer on every output.
- No auto-execution — tool only outputs suggestions, user trades manually.
- Treat as strictly personal, non-shared, non-monetized tool — this alone keeps it outside regulatory scope.

## Practical takeaways
1. Legally low-risk as personal-only tool; no SEBI registration needed.
2. Prefer official/public feeds (RSS, NSE Bhavcopy) over scraping dynamic/paywalled pages; daily cadence is low risk either way.
3. Include the disclaimer text above on every run output.
4. Store links/snippets only, never full article text.
5. Keep the 10-idea cap, citations, and no-auto-execution as hard product constraints — they are also the main risk mitigations.
