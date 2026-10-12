# Research: Existing GitHub projects (prior art)

## Most Relevant Existing Projects

| Project | Link | Key Details | Why Relevant |
|---------|------|------------|--------------|
| **ContextCraft** | https://github.com/arindhimar/ContextCraft | Claude + Zerodha KiteConnect, MCP integration | Only project combining Claude Agent + NSE/BSE + live trading API; closest match but focuses on order execution, not news analysis |
| **AI Trading Claude** | https://github.com/zubair-trabzada/ai-trading-claude | 5 parallel Claude agents, 16 skills, multi-dimensional analysis | Shows Claude Code + Agent SDK pattern for finance; produces PDF reports with thesis/risk/sentiment but no news scraping |
| **NSE Trading Skills** | https://github.com/Bhala-Srinivash/nse-trading-skills | 9 Claude Code skills, NSE/BSE focused, zero dependencies | India-focused, Claude Code native, but pure technical analysis—no news input |
| **MarketGPT** | https://github.com/JHenzi/MarketGPT | Claude/OpenAI/Ollama, ChromaDB RAG, news → LLM chat | Strong news scraping + embedding pipeline; but outputs summaries/chat, not buy/hold/sell signals with confidence |
| **Trade Bot** | https://github.com/pt-hieu/trade-bot | Multi-agent LLM pipeline (Vietnamese equities), ~38 PydanticAI agents, scored against actual market performance | Strongest pattern: news + macro + sector → swing-trade recommendations with validation loop; shows feedback architecture worth reusing |
| **Stock Screener** | https://github.com/xang1234/stock-screener | 80+ filters, AI chatbot (Groq/DeepSeek/Gemini), fundamental + technical | Mature filtering; AI-assisted but not news-driven |
| **Tickermind** | https://github.com/DarmorGamz/Tickermind | Local LLM sentiment analysis, McMaster 2025 capstone, privacy-focused | News + sentiment + local LLM; early-stage but aligned with local-first design |

## Patterns Worth Stealing

- Multi-agent pipelines (technical, fundamental, sentiment, risk, thesis) run in parallel — ContextCraft + AI Trading Claude demonstrate this works well.
- RAG + ChromaDB for semantic news search (MarketGPT pattern) beats simple keyword matching.
- Local LLM fallback (Tickermind, MarketGPT support Ollama) for privacy; cloud fallback for accuracy tradeoffs.
- Zerodha Kite Connect is the de-facto standard for NSE/BSE live data and order placement (note: requires paid API — not available to us per intake constraints).
- Feedback validation loops (Trade Bot) that score predictions against actual outcomes and feed back into next run's prompts enhance accuracy over time.

## Notable Gaps / Differentiation Opportunity

- No project combines: local headless CLI + max-10-ideas-per-run + red/yellow/green confidence with source citations.
- News → signals pipeline weak: MarketGPT has strong news scraping but outputs chat; ContextCraft has live trading but no news input; Trade Bot has the pattern but targets Vietnam only.
- Scoring/confidence inconsistent: most output "analysis" or "thesis," not structured buy/hold/target-price/duration/confidence with citation tracking.
- Indian market gap: ContextCraft + NSE Skills exist but are either data tools or trading APIs — no end-to-end "news → trade signal" for NSE with LLM scoring and citations.
- Claude Code + Agent SDK novelty: only ContextCraft + AI Trading Claude use Claude's Agent SDK for finance; combining it with news analysis + max-10-filtering + confidence signals is largely unexplored.
- Validation gap: no prominent projects track prediction accuracy against actual market outcomes or include source citations for every recommendation.

## Architecture Consensus

Most follow: News source → LLM scoring → persistence → UI/API. The gap is in the "max ideas" + "confidence + citations" + "hold-duration" layer — this is where this project is differentiated.
