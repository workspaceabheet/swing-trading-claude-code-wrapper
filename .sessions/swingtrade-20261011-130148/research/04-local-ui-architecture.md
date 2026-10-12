# Research: Local UI Architecture

## 1. Web Stack
**Recommended:** Pure static HTML + vanilla JS reading local JSON (fetch), optionally a thin Python Flask/`http.server` shim if filesystem fetch restrictions require a server. Skip Node/Express, React/Vue/Alpine — overkill for a static single-user card list.

## 2. History Persistence
**Recommended:** Flat JSON files per run, one file per run-date/timestamp (`runs/2026-10-11_14-32-45.json`), plus a `runs/latest.json` pointer. Skip SQLite for v1 — no benefit at daily cadence, single user.

## 3. UI Components
**Recommended:** Plain semantic HTML cards + a classless CSS framework (Pico CSS, Water.css, ~3KB) for free responsive styling. One `<article>` card per stock idea with ticker, buy/target/hold-duration, a confidence badge (🔴🟡🟢), rationale, and citation links.

## 4. Data Contract
**Recommended versioned JSON schema:**
```json
{
  "version": "1.0",
  "run_id": "2026-10-11_14-32-45",
  "generated_at": "2026-10-11T14:32:45Z",
  "ideas": [
    {
      "rank": 1,
      "ticker": "RELIANCE",
      "buy_price": 2450.0,
      "target_price": 2600.0,
      "hold_duration_days": 7,
      "confidence": "green",
      "rationale": "...",
      "citations": [{"url": "...", "text": "..."}]
    }
  ]
}
```
Include `version` in every run file; UI should handle older schema versions gracefully.

## 5. MVP Scope
**Recommended:** Read-only v1 — display latest run as a ranked card grid, a history sidebar/list of past runs, basic filter/sort. No "trigger run" button in v1; user runs the engine manually from the terminal and the UI just reads output. A "run engine now" button is a reasonable v2 addition.

## Summary table
| Layer | Recommendation |
|---|---|
| Server | Static HTML/JS, optional thin Flask/http.server |
| Frontend | Single HTML file + vanilla JS, no build step |
| Styling | Pico CSS or plain CSS, card layout + confidence badges |
| History | Flat JSON files + latest.json pointer |
| Data contract | Versioned JSON schema |
| MVP features | View latest run + browse/filter history, manual engine runs |

Estimated time to v1: very low (~a couple hours), consistent with "simple local tool" scope.
