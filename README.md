# Pre-Recall Radar

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/venkateshsunkula/pre-recall-radar/blob/main/pre_recall_radar.ipynb)
· [View full notebook with outputs](https://nbviewer.org/github/venkateshsunkula/pre-recall-radar/blob/main/pre_recall_radar.ipynb)

An AI agent that detects emerging product-safety issues from public complaint data before official recalls or warnings. It covers **baby products** (CPSC) and **cars** (NHTSA), and sends me a daily report on Telegram.

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

In every confirmed case, the company had not agreed to a recall.

**Cars (NHTSA, Oct 2026):** from NHTSA's 2025–2026 vehicle complaints, the spike detector flagged 11 vehicle parts, and the agent investigated each one:

| Verdict | Count | Example (complaints describe…) |
|---|---|---|
| 🚨 Likely real issue, no recall yet | 6 | Interior door handles snapping on a 2025 pickup |
| ⚠️ Recalled, but complaints continue | 3 | Battery problems still reported ~10 months after a plug-in hybrid recall |
| ⚠️ Recall gap: same defect recalled, but not for this model year | 1 | Engine failures in a newer model year than the recall covers |
| Unclear: several different problems | 1 | Mixed engine complaints |

On manual review of the first full run, 9 of 11 verdicts held up. The 2 misses came from reports that described two different problems while the agent's facts said "one main hazard"; a prompt fix corrected this.

## How it works
**v1: detection pipeline (baby products)**
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

**v3: cars (NHTSA)**
- Tracks **make + model + year + component** (e.g. one truck's steering).
- **Compares each part with its own vehicle.** My first rule flagged mostly new models: more cars on the road means more complaints about *every* part. A real defect makes one part grow faster than the rest of the car, so a part is flagged only if its complaints grow 3x faster than its vehicle's.
- Checks NHTSA's recalls API and adds two verdicts: **recalled but complaints continue** (the fix may not be working) and **recall gap** (same defect recalled in other model years, not this one).
- **A code check flags any complaint count in a report that no tool actually returned**, which catches invented numbers.

**Daily alerts**
| Part | Runs on | When |
|---|---|---|
| Baby data refresh (notebook cell) | Google Colab | Weekly |
| `radar.py` (baby + car watchlists, investigator) | GitHub Actions (`.github/workflows/daily.yml`) | Daily, ~8 AM Central |
| Car data | NHTSA API, fetched live | Daily |
| Report | Telegram bot | Every run |

Example morning report (vehicle anonymized):
```
Millie Moon: 🚨 Alert
  Last 90 days: 378 complaints (prior year: 196)
  Verdict: LIKELY REAL ISSUE

Flyboss: ⛔ OFFICIAL WARNING/RECALL - stop using, check cpsc.gov
  Verdict: LIKELY REAL ISSUE

🚗 CARS (NHTSA, live)
Pickup 2025: 🚨 Alert
  ⚠️ Structure: 24 complaints, 3.2x faster than rest of car
  Verdict: 🚨 LIKELY REAL ISSUE: no recall yet

SUV 2026: ❓ No complaints found in NHTSA's API under this name - can't assess
```

Design principle: code does counting and decisions (exact, repeatable); the LLM does reading and judgment (messy text).

## What I learned
- **LLM hallucination:** the judge invented a brand name. I caught it by checking output against the raw data and fixed it with prompt constraints.
- **A rule in a prompt is a request, not a guarantee.** My agent stated facts correctly but still chose verdicts that broke my rules, and kept inventing counts from sample texts. Fixes: the LLM only extracts facts and Python decides; a `count_mentions` tool for counting; and a code check that flags numbers no tool returned.
- **Check the math behind a rule.** "Monthly rate tripled" simplifies to "recent 90 days ≥ 75% of last year," which was far too loose for cars. Comparing each part with its own vehicle cut 56 flags to 11.
- **Missing data is reported as unknown, never as safe.** NHTSA's live API returned zero complaints for a car that has dozens in NHTSA's bulk file. My report first showed it as "✅ Quiet"; now it says "❓ can't assess."
- **Sources aren't equal.** The agent counted car blogs and forums as news, so the prompt now defines credible news (AP, Reuters, Consumer Reports, major outlets).
- **Regression testing:** after each change, I re-ran a case with a known answer (an official CPSC warning) to make sure the fix didn't break it.
- **Data leakage:** my first backtest could "see the future." Fixed by filtering by date and using publication date (when reports became public).
- **False matches:** matching recalls by brand name alone flagged old recalls of *different* products. The agent now judges whether an official action is about the same product.
- **Real-world constraints:** saferproducts.gov blocks GitHub's servers (HTTP 403), so Colab downloads baby data weekly into `data/` and the daily job reads that copy, warning me if it's over 14 days old.

## Predictions log (open cases, Oct 3, 2026)
| Product | Agent verdict | Main hazard | Status |
|---|---|---|---|
| Smart crib (brand C) | Unclear: one hazard, weak evidence | Loose hardware (choking) | Watching |
| Activity centers (brand D) | Unclear: several hazards | Mixed (neck entrapment, springs, tipping) | Watching |

## Limitations
- Complaint counts show that reports exist, not that a product causes harm. The agent reports signals, not verdicts on safety. A human should review flags before anything is published.
- 4 confirmed baby-product cases so far; car flags have not yet been backtested against later recalls.
- NHTSA's API groups problems more coarsely than its bulk file (e.g. "STRUCTURE" instead of "door handle"), so the daily car check is less precise than the notebook.
- LLM output varies between runs; verdicts were mostly stable, but report wording and searches differ.
- `count_mentions` matches text inside words (e.g. "lead" also matches "leading").

## Next steps
- Monthly "Radar Report" to build a public track record
- Backtest car flags against NHTSA recalls issued afterward
- More categories (FDA medical devices, food)

## Run it
1. Click **Open in Colab** above
2. Add your `ANTHROPIC_API_KEY` in Colab Secrets (🔑 icon)
3. Runtime → Run all

For the daily alerts: add `ANTHROPIC_API_KEY`, `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` as GitHub repository secrets, and set your brands and cars in `WATCHLIST` and `CAR_WATCHLIST` in `radar.py`.

## Tech
Python · pandas · Claude API (Haiku 4.5, tool use, web search) · Google Colab · GitHub Actions · Telegram Bot API · NHTSA API

## Sources
- Data: U.S. Consumer Product Safety Commission, SaferProducts.gov public database and CPSC recall/warning listings
- Data: NHTSA vehicle complaints (bulk files and API) and recalls API
- [CPSC warning: infant bouncers (Sep 10, 2026)](https://www.cpsc.gov/Warnings/2026/CPSC-Warns-Consumers-to-Stop-Using-Flyboss-Infant-Bouncers-Immediately-Due-to-Risk-of-Collapse-and-Impact-Injury-to-Infants)
- [CPSC warning: infant walkers (Aug 6, 2026)](https://www.cpsc.gov/Warnings/2026/CPSC-Warns-Consumers-to-Stop-Using-CiuseiAnx-Infant-Walkers-Immediately-Due-to-Risk-of-Serious-Injury-or-Death-from-Fall-Hazard-Violate-Mandatory-Standard-for-Infant-Walkers)
- [News coverage of diaper complaints (Sep 2026)](https://www.wcpo.com/money/consumer/dont-waste-your-money/millie-moon-says-it-wont-recall-diapers-despite-reports-of-chemical-burns)
- [NHTSA datasets and APIs](https://www.nhtsa.gov/nhtsa-datasets-and-apis)
