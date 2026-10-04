# Pre-Recall Radar

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/venkateshsunkula/pre-recall-radar/blob/main/pre_recall_radar.ipynb)

An AI agent that detects emerging consumer product-safety issues from public complaint data — before official recalls or warnings.

## Result
Backtested on the public CPSC complaint database (5,286 baby-product complaints, Jan–Sep 2026), using only data that was public at the time.

**Every official CPSC safety warning on a flagged product came 53–88 days after the agent's flag:**

| Product | Agent flagged | Confirmed by | Lead time |
|---|---|---|---|
| Infant walkers (brand A) | Feb 15, 2026 | CPSC safety warning, Apr 9 | 53 days |
| Infant walkers (brand B) | Jun 7, 2026 | CPSC safety warning, Aug 6 | 60 days |
| Infant bouncers | Jun 14, 2026 | CPSC safety warning, Sep 10 | 88 days |
| Diapers (chemical-burn and rash reports) | Apr 26, 2026 | National news coverage, Sep | ~5 months |

| Alert level | Rule | Distinct products flagged (Jan–Sep 2026) | Later confirmed |
|---|---|---|---|
| Watch | 3+ complaints in 90 days, 3x usual rate | 11 | 4 |
| Alert | 10+ complaints in 90 days, 3x usual rate | 2 | 2 |

In every confirmed case, the company had not agreed to a recall. Some remaining flags may still be acted on (see Predictions log).

## How it works
**v1: detection pipeline**
1. **Data:** downloads the full public SaferProducts.gov database (CPSC)
2. **Spike detector (Python):** compares each product's last 90 days of complaints to the prior year
3. **AI judge (Claude):** reads complaint texts, checks whether they describe the same hazard, merges brand-name spellings
4. **Backtest:** replays history week by week to measure lead time and false alarms

**v2: investigator agent**
For each flag, a Claude agent investigates on its own using 4 tools, choosing which to call and when to stop:
- `get_complaints`: complaint totals, monthly trend, sample texts
- `count_mentions`: counts a hazard keyword across all complaints
- `check_official_actions`: searches CPSC recalls and safety warnings
- `web_search`: finds news coverage

The agent extracts yes/no facts (one main hazard? official action on this product? credible news?). **Python applies the verdict rules**, so verdicts are consistent.

Design principle: code does counting and decisions (exact, repeatable); the LLM does reading and judgment (messy text).

## What I learned
- **LLM hallucination:** the judge invented a brand name. I caught it by checking output against the raw data and fixed it with prompt constraints.
- **Agents don't reliably follow rules in prompts.** My agent stated facts correctly but still chose verdicts that broke my rules. Fix: the LLM only extracts facts; Python decides.
- **When an agent guesses, give it a tool.** It invented complaint counts from samples, so I added `count_mentions`. Every number in reports now comes from a tool.
- **Regression testing:** after each change, I re-ran a case with a known answer (an official CPSC warning) to make sure the fix didn't break it.
- **Data leakage:** my first backtest could "see the future." Fixed by filtering by date and using publication date (when reports became public).
- **False matches:** matching recalls by brand name alone flagged old recalls of *different* products. The agent now judges whether an official action is about the same product.
- **Thresholds are product decisions:** the Watch level caught real issues the stricter Alert level missed, at the cost of more flags to review.

## Predictions log (open cases, Oct 3, 2026)
| Product | Agent verdict | Main hazard | Status |
|---|---|---|---|
| Smart crib (brand C) | Unclear: one hazard, weak evidence | Loose hardware (choking) | Watching |
| Activity centers (brand D) | Unclear: several hazards | Mixed (neck entrapment, springs, tipping) | Watching |

## Limitations
- Complaint counts show that reports exist, not that a product causes harm. The agent reports signals, not verdicts on safety.
- 4 confirmed cases so far; more backtesting on past years is needed.
- `count_mentions` matches text inside words (e.g. "lead" also matches "leading").
- Brand-level grouping can flag big brands with complaints spread across many different products.

## Next steps
- Watchlist for products you own + daily automatic runs
- Telegram alerts
- Group by brand + product type to reduce big-brand noise
- More categories (cars via NHTSA complaints, electronics)

## Run it
1. Click **Open in Colab** above
2. Add your `ANTHROPIC_API_KEY` in Colab Secrets (🔑 icon)
3. Runtime → Run all

## Tech
Python · pandas · Claude API (Haiku 4.5, tool use, web search) · Google Colab

## Sources
- Data: U.S. Consumer Product Safety Commission, SaferProducts.gov public database and CPSC recall/warning listings
- [CPSC warning: infant bouncers (Sep 10, 2026)](https://www.cpsc.gov/Warnings/2026/CPSC-Warns-Consumers-to-Stop-Using-Flyboss-Infant-Bouncers-Immediately-Due-to-Risk-of-Collapse-and-Impact-Injury-to-Infants)
- [CPSC warning: infant walkers (Aug 6, 2026)](https://www.cpsc.gov/Warnings/2026/CPSC-Warns-Consumers-to-Stop-Using-CiuseiAnx-Infant-Walkers-Immediately-Due-to-Risk-of-Serious-Injury-or-Death-from-Fall-Hazard-Violate-Mandatory-Standard-for-Infant-Walkers)
- [News coverage of diaper complaints (Sep 2026)](https://www.wcpo.com/money/consumer/dont-waste-your-money/millie-moon-says-it-wont-recall-diapers-despite-reports-of-chemical-burns)
