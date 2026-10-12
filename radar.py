"""Pre-Recall Radar: daily watchlist check.

Runs on GitHub Actions every morning and sends the result to Telegram.
Same logic as the notebook (v2 Steps 1-4), collected into one script.

Data comes from the data/ folder, which the weekly refresh cell in the
Colab notebook updates (saferproducts.gov blocks GitHub's servers).
"""
import gzip
import json
import os
import re

import anthropic
import pandas as pd
import requests

# ---- Settings ---------------------------------------------------------------
WATCHLIST = ["Millie Moon", "Flyboss", "Cradlewise", "Graco"]   # brands you own
MODEL = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
DATA = "data"
STALE_DAYS = 14


# ---- Telegram ---------------------------------------------------------------
def send_telegram(text):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": text[:4000]})
    return r.json().get("ok")


# ---- Load the data saved by the weekly Colab refresh --------------------------
def norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


def load_baby():
    baby = pd.read_csv(f"{DATA}/baby.csv.gz", low_memory=False)
    baby["Report Date"] = pd.to_datetime(baby["Report Date"], errors="coerce")
    baby["Publication Date"] = pd.to_datetime(baby["Publication Date"], errors="coerce")
    baby["brand_key"] = baby["Brand"].astype(str).map(norm)
    return baby


def load_official():
    rows = []
    for fname, kind in [("warnings.csv.gz", "WARNING"), ("recalls_cpsc.csv.gz", "RECALL")]:
        with gzip.open(f"{DATA}/{fname}", "rt", encoding="latin-1") as f:
            for line in f:
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
    age = (pd.Timestamp.now().normalize() - newest).days
    if age > STALE_DAYS:
        lines.append(f"⚠️ Data is {age} days old. Run the weekly refresh cell in Colab.")
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

    return lines


# =================================================================================
# CARS (NHTSA) - checks each car on CAR_WATCHLIST through NHTSA's free API
# =================================================================================
CAR_WATCHLIST = [            # (make, model, model year) - put YOUR car(s) here
    ("Toyota", "Tacoma", "2025"),
    ("Tesla", "Model Y", "2026"),
    ("Honda", "CR-V", "2020"),
]
NHTSA = "https://api.nhtsa.gov"
cars = pd.DataFrame()        # filled per car; the investigator tools read it


def fetch_car_complaints(make, model, year):
    r = requests.get(f"{NHTSA}/complaints/complaintsByVehicle",
                     params={"make": make, "model": model, "modelYear": year}, timeout=60)
    r.raise_for_status()
    rows = [{"MAKETXT": make.upper(), "MODELTXT": model.upper(), "YEARTXT": str(year),
             "COMPDESC": str(c.get("components") or "UNKNOWN OR OTHER").upper(),
             "DATEA": pd.to_datetime(c.get("dateComplaintFiled"), format="%m/%d/%Y", errors="coerce"),
             "CRASH": "Y" if c.get("crash") else "N",
             "FIRE": "Y" if c.get("fire") else "N",
             "INJURED": int(c.get("numberOfInjuries") or 0),
             "DEATHS": int(c.get("numberOfDeaths") or 0),
             "CDESCR": str(c.get("summary") or "")}
            for c in r.json().get("results", [])]
    return pd.DataFrame(rows, columns=["MAKETXT", "MODELTXT", "YEARTXT", "COMPDESC", "DATEA",
                                       "CRASH", "FIRE", "INJURED", "DEATHS", "CDESCR"])


def car_recalls(make, model, year):
    try:
        r = requests.get(f"{NHTSA}/recalls/recallsByVehicle",
                         params={"make": make, "model": model, "modelYear": year}, timeout=60)
        return r.json().get("results", [])
    except Exception as e:
        print("  recall API error:", e)
        return []


def car_spikes(df, today):
    """Same rule as the notebook: a component is flagged when it grows 3x faster than its own car."""
    rs = today - pd.Timedelta(days=90)
    bs = rs - pd.Timedelta(days=365)
    d = df[df["COMPDESC"] != "UNKNOWN OR OTHER"].copy()
    d["recent"] = (d["DATEA"] > rs) & (d["DATEA"] <= today)
    d["before"] = (d["DATEA"] > bs) & (d["DATEA"] <= rs)
    d["r_crash"] = d["recent"] & (d["CRASH"] == "Y")
    d["r_deaths"] = d["DEATHS"].where(d["recent"], 0)
    g = d.groupby("COMPDESC")[["recent", "before", "r_crash", "r_deaths"]].sum()
    g.columns = ["recent_90d", "prior_365d", "crashes", "deaths"]
    veh_recent, veh_prior = g["recent_90d"].sum(), g["prior_365d"].sum()
    g["growth_vs_car"] = (g["recent_90d"] / ((g["prior_365d"] + 1) * (veh_recent + 1) / (veh_prior + 1))).round(1)
    spike = (veh_prior >= 20) & (g["recent_90d"] >= 10) & (g["growth_vs_car"] >= 3)
    new_hot = (veh_prior < 20) & (g["recent_90d"] >= 20)
    return g[spike | new_hot].sort_values("growth_vs_car", ascending=False), int(veh_recent), int(d["r_crash"].sum())


# ---- Car investigator tools (same as notebook v3 Step 4) ----
def car_rows(make, model, year, component=None):
    m = (cars["MAKETXT"] == make.upper()) & (cars["MODELTXT"] == model.upper()) & (cars["YEARTXT"] == str(year))
    if component:
        m &= cars["COMPDESC"].str.contains(component.upper(), regex=False, na=False)
    return cars[m]


def get_car_complaints(make, model, year, component=None):
    rows = car_rows(make, model, year, component)
    if rows.empty:
        return "No complaints found."
    monthly = rows.groupby(rows["DATEA"].dt.to_period("M")).size().tail(12)
    texts = rows.sort_values("DATEA", ascending=False)["CDESCR"].dropna().astype(str).str[:300].head(8)
    return (f"Total complaints: {len(rows)} | crashes: {(rows['CRASH']=='Y').sum()} | fires: {(rows['FIRE']=='Y').sum()} "
            f"| injured: {rows['INJURED'].sum()} | deaths: {rows['DEATHS'].sum()}\n"
            f"Components: {rows['COMPDESC'].value_counts().head(3).to_dict()}\n"
            f"Complaints per month: {dict((str(p), int(n)) for p, n in monthly.items())}\n"
            "Most recent complaints:\n" + "\n".join(f"- {t}" for t in texts))


def count_car_mentions(make, model, year, keyword, component=None):
    rows = car_rows(make, model, year, component)
    hits = rows["CDESCR"].astype(str).str.contains(keyword, case=False, regex=False).sum()
    return f"{hits} of {len(rows)} complaints mention '{keyword}'."


def check_car_recalls(make, model, year):
    recalls = car_recalls(make, model, year)
    if not recalls:
        return "No NHTSA recalls for this vehicle."
    return "\n".join(f"- {r.get('NHTSACampaignNumber')} ({r.get('ReportReceivedDate')}): "
                     f"{r.get('Component')} | {str(r.get('Summary', ''))[:200]}" for r in recalls[:10])


car_input = {"make": {"type": "string"}, "model": {"type": "string"}, "year": {"type": "string"},
             "component": {"type": "string", "description": "Optional. Part of the component name, e.g. 'STEERING'"}}

CAR_TOOLS = [
    {"name": "get_car_complaints",
     "description": "NHTSA complaints for one vehicle (optionally one component): totals, crashes/fires/injuries/deaths, monthly trend, recent complaint texts.",
     "input_schema": {"type": "object", "properties": car_input, "required": ["make", "model", "year"]}},
    {"name": "count_car_mentions",
     "description": "Count how many of the vehicle's complaints mention a keyword, across ALL complaints, not just samples.",
     "input_schema": {"type": "object", "properties": {**car_input, "keyword": {"type": "string"}},
                      "required": ["make", "model", "year", "keyword"]}},
    {"name": "check_car_recalls",
     "description": "All NHTSA recalls listed for this exact make/model/year, with dates, component and summary. Judge yourself whether any covers the SAME part and hazard.",
     "input_schema": {"type": "object", "properties": {k: car_input[k] for k in ["make", "model", "year"]},
                      "required": ["make", "model", "year"]}},
    {"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
]
CAR_FUNCTIONS = {"get_car_complaints": get_car_complaints,
                 "count_car_mentions": count_car_mentions,
                 "check_car_recalls": check_car_recalls}

CAR_SYSTEM = """You are a vehicle-safety investigator. Our spike detector flagged one component of one vehicle
because its complaints grew much faster than the rest of that vehicle's complaints.

Investigate with your tools:
1. Read the complaints for that component. Do they describe the same specific failure?
2. Check NHTSA recalls. Does one cover the SAME part and hazard? Note its date.
   Does that recall cover THIS exact model year, or only other years?
   If it covers this vehicle: are complaints continuing AFTER the recall date?
3. Search the web for news (max 3 searches).

Write a short report:
HAZARD: one line
EVIDENCE: 3 bullets with numbers, each labeled [NHTSA complaints], [recall], [news], or [blog/forum - unverified]
RECALL STATUS: campaign number + date + whether it covers this model year, or none
NEWS: one line with source names
CONFIDENCE: low / medium / high, and why

Rules:
- Say "complaints describe", never "the vehicle causes". Never invent facts.
- In [NHTSA complaints] lines, ONLY use numbers returned by a tool. You see only a SAMPLE of complaint
  texts, so never count the samples yourself. Use count_car_mentions to count across ALL complaints.
- credible_news = true ONLY for established outlets (e.g. AP, Reuters, Consumer Reports, major newspapers or TV stations).
  Car blogs, forums, aggregators, parts sellers, law-firm sites and social media do NOT count.
  Label them [blog/forum - unverified].
- Never repeat claims that cite unnamed or "internal" sources.

End with ONE line exactly in this format (plain text, no bold, JSON true/false only):
FACTS: {"one_main_hazard": true, "recall_same_part": false, "recall_covers_this_vehicle": false, "complaints_after_recall": false, "credible_news": false}
- one_main_hazard: false if your own report describes two or more different problems
- recall_same_part: a recall covers the same part AND the MAIN hazard (for any model year).
  A recall for a different problem in the same system does NOT count.
- recall_covers_this_vehicle: that recall explicitly includes THIS make, model AND model year
- complaints_after_recall: complaints continue after that recall's date
Do NOT write a verdict. Our code decides it."""


def investigate_car(prompt, max_steps=10):
    messages = [{"role": "user", "content": prompt}]
    for step in range(1, max_steps + 1):
        resp = client.messages.create(model=MODEL, max_tokens=2000,
                                      system=CAR_SYSTEM, tools=CAR_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    print(f"  Step {step}: {block.name}({block.input})")
                    output = CAR_FUNCTIONS[block.name](**block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            messages.append({"role": "user", "content": results})
        elif resp.stop_reason == "pause_turn":
            continue
        else:
            return "".join(b.text for b in resp.content if b.type == "text")
    return "Stopped: reached the step limit."


def decide_car(flag, report):
    m = re.search(r"FACTS:\**\s*(\{.*?\})", report, re.S)
    if not m:
        return "UNCLEAR (agent gave no FACTS line)"
    f = json.loads(m.group(1))
    if not f.get("one_main_hazard"):
        return "UNCLEAR: several different problems"
    if f.get("recall_same_part"):
        if not f.get("recall_covers_this_vehicle"):
            return "⚠️ RECALL GAP: same defect recalled, but NOT for this model year"
        return ("⚠️ RECALLED, BUT COMPLAINTS CONTINUE (check whether the fix works)"
                if f.get("complaints_after_recall") else "KNOWN ISSUE: already recalled")
    if f.get("credible_news") or flag["recent_90d"] >= 20 or flag["crashes"] >= 3 or flag["deaths"] > 0:
        return "🚨 LIKELY REAL ISSUE: no recall yet"
    return "👀 UNCLEAR: one hazard, but weak evidence so far"


def run_car_watchlist(deep=True):
    global cars
    today = pd.Timestamp.now().normalize()
    lines = ["\n🚗 CARS (NHTSA, live)"]
    for make, model, year in CAR_WATCHLIST:
        name = f"{make} {model} {year}"
        print(f"Checking {name}...")
        try:
            cars = fetch_car_complaints(make, model, year)
        except Exception as e:
            lines.append(f"\n{name}: ⚠️ NHTSA unavailable ({type(e).__name__})")
            continue
        flags, recent, crashes = car_spikes(cars, today)
        level = "🚨 Alert" if len(flags) else "✅ Quiet"
        lines.append(f"\n{name}: {level}\n  Last 90 days: {recent} complaints, {crashes} crashes")

        recalls = car_recalls(make, model, year)
        dates = pd.to_datetime([r.get("ReportReceivedDate") for r in recalls], dayfirst=True, errors="coerce")
        new = int((dates >= today - pd.Timedelta(days=365)).sum())
        if new:
            lines.append(f"  🔧 {new} recall(s) in the past year: check your VIN at nhtsa.gov/recalls")

        for comp, f in flags.head(2).iterrows():        # at most 2 investigations per car per day
            line = f"  ⚠️ {comp.title()}: {int(f['recent_90d'])} complaints, {f['growth_vs_car']}x faster than rest of car"
            if deep:
                report = investigate_car(
                    f"Investigate: make={make}, model={model}, year={year}, component={comp}. "
                    f"Last 90 days: {int(f['recent_90d'])} complaints, {int(f['crashes'])} crashes. "
                    f"Growth vs. rest of vehicle: {f['growth_vs_car']}x.")
                line += f"\n    Verdict: {decide_car(f, report)}"
            lines.append(line)
    return lines


# ---- Run ------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        baby = load_baby()
        official = load_official()
        lines = run_watchlist()
    except Exception as e:
        send_telegram(f"⚠️ Pre-Recall Radar failed today: {type(e).__name__}: {e}")
        raise

    try:
        lines += run_car_watchlist()
    except Exception as e:                               # cars must never block the baby report
        lines.append(f"\n🚗 Car check failed: {type(e).__name__}: {e}")

    msg = "\n".join(lines)
    print(msg)
    print("Sent to Telegram:", send_telegram(msg))
