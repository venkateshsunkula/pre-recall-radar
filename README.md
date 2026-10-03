# Pre-Recall Radar
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/venkateshsunkula/pre-recall-radar/blob/main/pre_recall_radar.ipynb)
An AI agent that detects emerging consumer product-safety issues from public complaint data — before official recalls or warnings.

## Result
Backtested on the public CPSC complaint database (5,286 baby-product complaints, Jan–Sep 2026), using only data that was public at the time:

| Signal | Agent alert | Compared against | Lead time |
|---|---|---|---|
| Infant walkers (fall hazard) | Jul 5, 2026 | Official CPSC safety warning (Aug 6, 2026) | **32 days** |
| Diapers (chemical-burn and rash reports) | May 24, 2026 | National news coverage (Sep 2026) | **~4 months** |

The high-confidence alert level raised **2 alerts in 9 months, and both matched real, later-confirmed safety issues**. In both cases, the company declined to issue a recall.

| Alert level | Rule | Brands flagged (Jan–Sep 2026) |
|---|---|---|
| Watch | 3+ complaints in 90 days, 3x usual rate | 14 |
| Alert | 10+ complaints in 90 days, 3x usual rate | 2 |

## How it works
1. **Data:** downloads the full public SaferProducts.gov database (CPSC)
2. **Spike detector (Python):** compares each product's last 90 days of complaints to the prior year
3. **AI judge (Claude):** reads complaint texts, decides whether they describe the same hazard, rates severity, and merges brand-name spellings
4. **Recall check:** marks each signal as "already recalled" or "early signal"
5. **Backtest:** replays history week by week to measure lead time and false alarms

Design choice: plain code does the counting (fast, cheap, exact); the LLM does the judgment (reading messy text).

## What I learned
- **LLM hallucination:** the judge invented a brand name in 1 of 4 outputs. I caught it by checking the output against the raw data, and fixed it with prompt constraints.
- **Overconfidence:** the model gave high severity to 3 unrelated complaints, so I added rules that tie confidence to evidence volume.
- **Data leakage:** my first backtest could "see the future." I fixed it by filtering by date, and by using publication date (when reports became public) instead of filing date.
- **Thresholds are product decisions:** a lower threshold catches issues earlier but raises more false alarms.
- **Messy real-world data:** the CSV had a disclaimer line above the header, and one brand was spelled 4 different ways.
- - **False recall match:** the recall check matched by brand name only, so it reported a past recall of a *different* product from the same brand. Fixed by flagging "same brand, verify product" instead of claiming a recall.

## Limitations
- Complaint counts show that reports exist, not that a product causes harm. The agent reports signals, not verdicts.
- Validated on 2 confirmed cases so far; more backtesting on past recalls is needed.
- The recall check only searched official recalls. Both real cases had safety *warnings* or news coverage without recalls, so v2 adds CPSC Product Safety Warnings data.

## Next steps
- Add CPSC Product Safety Warnings as a data source
- Watchlist + Telegram alerts for products you own
- Web-search tool so the agent checks news and recalls on its own
- More categories (cars via NHTSA complaints, electronics)

## Run it
1. Open `pre-recall-radar.ipynb` in Google Colab
2. Add your `ANTHROPIC_API_KEY` in Colab Secrets (🔑 icon)
3. Runtime → Run all

## Tech
Python · pandas · Claude API (Haiku) · Google Colab

## Sources
- Data: U.S. Consumer Product Safety Commission, SaferProducts.gov public database
- [CPSC safety warning on infant walkers (Aug 6, 2026)](https://www.cpsc.gov/Warnings/2026/CPSC-Warns-Consumers-to-Stop-Using-CiuseiAnx-Infant-Walkers-Immediately-Due-to-Risk-of-Serious-Injury-or-Death-from-Fall-Hazard-Violate-Mandatory-Standard-for-Infant-Walkers)
- [News coverage of diaper complaints (Sep 2026)](https://www.wcpo.com/money/consumer/dont-waste-your-money/millie-moon-says-it-wont-recall-diapers-despite-reports-of-chemical-burns)
