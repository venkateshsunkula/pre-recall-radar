"""Pre-Recall Radar: daily watchlist check.

Runs on GitHub Actions every morning and sends the result to Telegram.
Same logic as the notebook (v2 Steps 1-4), collected into one script.
"""
import io
import json
import os
import re
import time
import zipfile

import anthropic
import pandas as pd
import requests

# ---- Settings ---------------------------------------------------------------
WATCHLIST = ["Millie Moon", "Flyboss", "Cradlewise", "Graco"]   # brands you own
MODEL = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.saferproducts.gov/",
}


# ---- Telegram ---------------------------------------------------------------
def send_telegram(text):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": text[:4000]})
    return r.json().get("ok")


# ---- Step 1: download fresh data -------------------------------------------
def fetch(url, tries=4):
    """Download a URL like a normal browser, retrying if the site blocks us."""
    session = requests.Session()
    session.headers.update(HEADERS)
    for attempt in range(1, tries + 1):
        r = session.get(url, timeout=300)
        if r.status_code == 200:
            return r.content
        print(f"  {url} -> {r.status_code} (attempt {attempt}/{tries})")
        time.sleep(15 * attempt)
    r.raise_for_status()


def download_data():
    zipfile.ZipFile(io.BytesIO(fetch("https://www.saferproducts.gov/SPDB.zip"))).extractall(".")

    for url, name in [
        ("https://www.cpsc.gov/s3fs-public/recall-data/product_safety_warning_listing.csv", "warnings.csv"),
        ("https://www.cpsc.gov/s3fs-public/recall-data/recalls_recall_listing.csv", "recalls_cpsc.csv"),
    ]:
        with open(name, "wb") as f:
            f.write(fetch(url))


# ---- Step 2: load baby-product complaints ----------------------------------
def norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


def load_baby():
    with open("IncidentReports.csv", encoding="latin-1") as f:
        for i, line in enumerate(f):
            if "Report No." in line:
                header_row = i
                break

    df = pd.read_csv("IncidentReports.csv", skiprows=header_row,
                     low_memory=False, encoding="latin-1")
    df.columns = df.columns.str.strip()

    baby = df[
        df["Product Category"].str.contains("nursery|infant|baby", case=False, na=False)
        | df["Product Sub Category"].str.contains("nursery|infant|baby|crib|stroller|car seat",
                                                  case=False, na=False)
    ].copy()
    baby["Report Date"] = pd.to_datetime(baby["Report Date"], errors="coerce")
    baby["Publication Date"] = pd.to_datetime(baby["Publication Date"], errors="coerce")
    baby["brand_key"] = baby["Brand"].astype(str).map(norm)
    return baby


def load_official():
    rows = []
    for fname, kind in [("warnings.csv", "WARNING"), ("recalls_cpsc.csv", "RECALL")]:
        for line in open(fname, encoding="latin-1"):
            rows.append((kind, norm(line), line.strip()[:150]))
    return rows


# ---- Agent tools -------------------------------------------------------------
def get_complaints(brand):
    rows = baby[baby["brand_key"].str.contains(norm(brand), na=False)]
    if rows.empty:
        return "No complaints found for this brand."
    monthly = rows.groupby(rows["Publication Date"].dt.to_period("M")).size().tail(12)
    texts = (rows.sort_values("Publication Date", ascending=False)["Incident Description"]
             .dropna().astype(str).str[:300].head(8))
    return (f"Total complaints: {len(rows)}\n"
            f"Product types: {rows['Product Type'].value_counts().head(3).to_dict()}\n"
            f"Complaints per month: {{{', '.join(f'{p}: {n}' for p, n in monthly.items())}}}\n"
            "Most recent complaints:\n" + "\n".join(f"- {t}" for t in texts))


def check_official_actions(brand):
    b = norm(brand)
    hits = [f"{kind}: {text}" for kind, n, text in official if len(b) >= 4 and b in n]
    return "\n".join(hits[:6]) if hits else "No official CPSC recalls or warnings found for this brand."


def count_mentions(brand, keyword):
    rows = baby[baby["brand_key"].str.contains(norm(brand), na=False)]
    hits = rows["Incident Description"].astype(str).str.contains(keyword, case=False).sum()
    return f"{hits} of {len(rows)} complaints mention '{keyword}'."


brand_input = {"type": "object",
               "properties": {"brand": {"type": "string", "description": "Brand name, e.g. 'Flyboss'"}},
               "required": ["brand"]}

TOOLS = [
    {"name": "get_complaints",
     "description": "Get CPSC consumer complaints for a brand: total count, product types, complaints per month, and recent complaint texts.",
     "input_schema": brand_input},
    {"name": "check_official_actions",
     "description": "Search official CPSC recalls and product safety warnings for a brand. Returns titles with dates. Matches may be old or about a DIFFERENT product from the same brand, so judge relevance yourself.",
     "input_schema": brand_input},
    {"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
    {"name": "count_mentions",
     "description": "Count how many of a brand's complaints mention a keyword (e.g. 'collapse', 'strangle', 'bolt'). Use this to count hazards across ALL complaints, not just the samples.",
     "input_schema": {"type": "object",
                      "properties": {"brand": {"type": "string"}, "keyword": {"type": "string"}},
                      "required": ["brand", "keyword"]}},
]

TOOL_FUNCTIONS = {"get_complaints": get_complaints,
                  "check_official_actions": check_official_actions,
                  "count_mentions": count_mentions}

SYSTEM = """You are a product-safety investigator. Our spike detector flagged a brand because consumer complaints suddenly increased.

Investigate with your tools:
1. Read the complaints. Do they describe the same hazard?
2. Check official CPSC actions. Only count an action if it is about the SAME product and hazard. Note its date.
3. Search the web for news or other reports (max 3 searches).

Then write a short report:
HAZARD: one line
EVIDENCE: 3 bullets with numbers
OFFICIAL STATUS: action + date, or none
NEWS: one line, with source names
CONFIDENCE: low / medium / high, and why

Rules:
- Say "reports describe", never "the product causes". Never invent facts. If a tool returns nothing, say so.
- Only state numbers that came directly from a tool. You only see a SAMPLE of complaint texts; use the TOTAL from get_complaints, and use count_mentions to count hazards across all complaints.
- When count_mentions gives a number, report THAT number (e.g. "34 of 41 complaints mention collapse"), not the sample count.
- Label each piece of evidence by WHERE the number came from:
  [CPSC complaints] = only numbers returned by get_complaints or count_mentions
  [official action] = numbers from CPSC warnings/recalls (even if found via web search)
  [news] / [social media - unverified]

At the very end of your report, add ONE line exactly in this format (JSON, true/false only):
FACTS: {"one_main_hazard": true, "official_action_same_product": false, "credible_news": false}
- one_main_hazard: most complaints describe the SAME specific hazard
- official_action_same_product: a CPSC recall/warning about this exact product and hazard
- credible_news: real news outlets (not social media, not law-firm websites)
Do NOT write a verdict. Our code decides it from these facts."""


# ---- The investigator agent ---------------------------------------------------
def investigate(brand, max_steps=10):
    messages = [{"role": "user", "content": f"Investigate this flagged brand: {brand}"}]
    for step in range(1, max_steps + 1):
        resp = client.messages.create(model=MODEL, max_tokens=2000,
                                      system=SYSTEM, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    print(f"  Step {step}: {block.name}({block.input})")
                    output = TOOL_FUNCTIONS[block.name](**block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            messages.append({"role": "user", "content": results})
        elif resp.stop_reason == "pause_turn":
            continue
        else:
            return "".join(b.text for b in resp.content if b.type == "text")
    return "Stopped: reached the step limit."


# ---- Code-based verdict --------------------------------------------------------
def complaint_count(brand):
    return int(baby["brand_key"].str.contains(norm(brand), na=False).sum())


def decide(brand, report):
    m = re.search(r"FACTS:\s*(\{.*?\})", report, re.S)
    if not m:
        return "UNCLEAR (agent gave no FACTS line)"
    f = json.loads(m.group(1))
    n = complaint_count(brand)
    if not f.get("one_main_hazard"):
        return "UNCLEAR: several different hazards"
    if f.get("official_action_same_product") or f.get("credible_news") or n >= 10:
        return "LIKELY REAL ISSUE"
    return "UNCLEAR: one hazard, but weak evidence so far"


# ---- Watchlist ----------------------------------------------------------------
def spike_status(brand, col="Publication Date"):
    d = baby[col]
    day = d.max()
    rs = day - pd.Timedelta(days=90)
    bs = rs - pd.Timedelta(days=365)
    mine = baby["brand_key"].str.contains(norm(brand), na=False)
    r = int((mine & (d > rs) & (d <= day)).sum())
    b = int((mine & (d > bs) & (d <= rs)).sum())
    spiking = r >= 3 and r / 3 >= 3 * b / 12
    if spiking and r >= 10:
        level = "🚨 Alert"
    elif spiking:
        level = "👀 Watch"
    else:
        level = "✅ Quiet"
    return level, r, b


def latest_official_date(brand):
    hits = check_official_actions(brand)
    dates = re.findall(r'"([A-Z][a-z]+ \d{1,2}, \d{4})"', hits)
    return max(pd.to_datetime(dates)) if dates else None


def run_watchlist(deep=True):
    newest = baby["Publication Date"].max()
    lines = [f"Pre-Recall Radar: daily check (data up to {newest.date()})"]
    for brand in WATCHLIST:
        print(f"Checking {brand}...")
        level, r, b = spike_status(brand)
        lines.append(f"\n{brand}: {level}\n  Last 90 days: {r} complaints (prior year: {b})")

        last = latest_official_date(brand)
        if last is not None and last >= newest - pd.Timedelta(days=365):
            level = "⛔ OFFICIAL WARNING/RECALL - stop using, check cpsc.gov"
            lines[-1] = f"\n{brand}: {level}\n  Last 90 days: {r} complaints (prior year: {b})"
        elif last is not None:
            lines.append(f"  Past official action: {last.date()} (may be a different product)")

        if deep and level != "✅ Quiet":
            report = investigate(brand)
            lines.append(f"  Verdict: {decide(brand, report)}")

    msg = "\n".join(lines)
    print(msg)
    print("Sent to Telegram:", send_telegram(msg))


# ---- Run ------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        download_data()
        baby = load_baby()
        official = load_official()
        run_watchlist()
    except Exception as e:
        send_telegram(f"⚠️ Pre-Recall Radar failed today: {type(e).__name__}: {e}")
        raise
