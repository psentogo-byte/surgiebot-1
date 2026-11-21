import html as html_lib
import re
from typing import Dict, List, Tuple

# --- Categorization & Transmission Channels (Bilingual EN + DE) ---

CHANNEL_RULES = {
    "dax_bluechips": {
        "label": "DAX Blue Chips & Earnings",
        "impact_type": "direct",
        "keywords": [
            "sap", "siemens", "allianz", "airbus", "deutsche telekom", "munich re", "münchener rück",
            "volkswagen", "vw ", "mercedes", "bmw", "porsche", "basf", "bayer",
            "deutsche bank", "commerzbank", "infineon", "rheinmetall", "adidas",
            "rwe", "e.on", "eon", "beiersdorf", "henkel", "continental", "fresenius",
            "hannover re", "hannover rück", "symrise", "zalando", "vonovia",
            "heidelberg materials", "daimler", "mtu aero", "qiagen", "sartorius",
            "brenntag", "merck kgaa", "dax 40", "dax40", "dax index", "dax ",
            "frankfurt stocks", "gdaxi", "leitindex", "aktie", "aktien", "quartalszahlen",
            "geschäftszahlen", "gewinnwarnung", "dividende", "börse frankfurt"
        ],
    },
    "german_macro": {
        "label": "German Macro & Politics",
        "impact_type": "direct",
        "keywords": [
            "germany", "german ", "deutschland", "deutsche ", "deutschen ", "bundesbank",
            "ifo ", "ifo-", "zew ", "zew-", "destatis", "statistisches bundesamt",
            "berlin", "bundestag", "bundesrat", "scholz", "merz", "debt brake", "schuldenbremse",
            "bund ", "bunds", "bundesanleihe", "german gdp", "bip ", "konjunktur",
            "wirtschaftswachstum", "german inflation", "verbraucherpreise", "german pmi",
            "einkaufsmanagerindex", "factory orders", "auftragseingang", "industrial production",
            "industrieproduktion", "german exports", "exporte", "german retail",
            "arbeitsmarkt", "arbeitslos", "kiel institute", "ifw ", "diw ", "sachverständigenrat"
        ],
    },
    "ecb_rates": {
        "label": "ECB & Eurozone Rates",
        "impact_type": "indirect",
        "keywords": [
            "ecb", "ezb", "european central bank", "europäische zentralbank", "lagarde",
            "eurozone", "euro area", "euroraum", "eur/usd", "eurusd", "euro falls",
            "euro rises", "euro gains", "euro weakens", "euro-kurs", "deposit rate",
            "leitzins", "zinssatz", "zinssenkung", "zinswende", "zinspause", "monetary policy",
            "geldpolitik", "governing council", "ezb-rat", "eu inflation", "hicp",
            "teuerung", "schnabel", "nagel", "lane ", "villeroy"
        ],
    },
    "trade_tariffs": {
        "label": "Trade, Tariffs & Autos",
        "impact_type": "indirect",
        "keywords": [
            "tariff", "tariffs", "zoll", "zölle", "strafzölle", "trade war", "handelskrieg",
            "trade dispute", "handelsstreit", "export", "import duty", "eu-china", "us-eu",
            "china economy", "chinas wirtschaft", "chinese demand", "ev tariffs",
            "electric vehicle", "elektroauto", "auto sector", "autobauer", "autoindustrie",
            "carmaker", "automaker", "wto", "sanctions", "sanktionen", "supply chain", "lieferketten"
        ],
    },
    "energy_commodities": {
        "label": "Energy & Commodities",
        "impact_type": "indirect",
        "keywords": [
            "natural gas", "erdgas", "gaspreis", "ttf", "oil price", "ölpreis", "brent",
            "wti", "crude oil", "rohöl", "opec", "energy crisis", "energiekrise",
            "gas storage", "gasspeicher", "electricity price", "strompreis", "energiepreise",
            "lng", "nord stream", "pipeline", "energy costs", "energiekosten"
        ],
    },
    "global_us": {
        "label": "US Fed & Global Markets",
        "impact_type": "indirect",
        "keywords": [
            "fed", "federal reserve", "powell", "fomc", "wall street", "s&p 500",
            "nasdaq", "dow jones", "us-börse", "us-börsen", "us cpi", "us-inflation",
            "nonfarm payrolls", "us-arbeitsmarkt", "treasury yield", "us-rendite",
            "global growth", "weltwirtschaft", "imf", "iwf", "world bank", "geopolitical",
            "geopolitik", "middle east", "nahost", "ukraine", "risk-off", "risk appetite",
            "tech rout", "goldpreis", "abverkauf"
        ],
    },
}

SECTOR_KEYWORDS = {
    "Autos": ["volkswagen", "vw ", "mercedes", "bmw", "porsche", "auto", "autobauer", "carmaker", "automaker", "ev ", "tariff", "zölle"],
    "Tech & Semis": ["sap", "infineon", "ai ", "ki ", "tech", "software", "chip", "semiconductor", "halbleiter", "nasdaq"],
    "Industrials & Defense": ["siemens", "airbus", "rheinmetall", "thyssenkrupp", "rüstung", "manufacturing", "pmi", "factory orders", "defense", "industrial", "maschinenbau"],
    "Financials": ["allianz", "munich re", "münchener rück", "deutsche bank", "commerzbank", "hannover re", "bank", "banken", "insurer", "versicherung", "yield", "ecb", "ezb", "zins"],
    "Chemicals & Energy": ["basf", "bayer", "brenntag", "rwe", "e.on", "chemie", "natural gas", "erdgas", "oil", "öl", "crude", "energy", "energie"],
    "Consumer & Healthcare": ["adidas", "zalando", "henkel", "beiersdorf", "fresenius", "merck", "retail", "einzelhandel", "consumer", "konsum", "pharma"],
}

# --- Bilingual DAX-Specific Financial Lexicon ---
BULLISH_PHRASES: Dict[str, float] = {
    # English Monetary / Macro
    "rate cut": 0.72, "cuts interest rates": 0.80, "cut interest rates": 0.80,
    "cut rates": 0.75, "cuts rates": 0.75, "rate cuts": 0.70, "dovish": 0.65,
    "easing cycle": 0.65, "stimulus": 0.65, "fiscal stimulus": 0.72,
    "stimulus package": 0.72, "debt brake reform": 0.65, "spending boost": 0.62,
    "defense spending": 0.55, "rate cut expectations": 0.65, "signals rate cut": 0.72,
    "inflation cools": 0.68, "inflation slows": 0.65, "inflation eases": 0.68,
    "cooling inflation": 0.68, "disinflation": 0.55, "inflation falls": 0.65,
    "inflation drops": 0.65, "soft landing": 0.60, "avoid recession": 0.55,
    # English Corporate / Market
    "beats expectations": 0.75, "beat expectations": 0.75, "top estimates": 0.72,
    "beats estimates": 0.72, "earnings beat": 0.75, "stronger than expected": 0.70,
    "better than expected": 0.70, "raises guidance": 0.80, "raised guidance": 0.80,
    "raises outlook": 0.75, "upgrades outlook": 0.75, "lifts outlook": 0.74,
    "profit jump": 0.70, "record high": 0.68, "all-time high": 0.70,
    "rebound": 0.55, "rebounds": 0.55, "rallies": 0.65, "rally": 0.60,
    "surges": 0.58, "soars": 0.60, "jumps": 0.55, "gains": 0.45,
    "climbs": 0.48, "advances": 0.45, "recovery": 0.55, "recovers": 0.55,
    "stabilizes": 0.40, "growth accelerates": 0.65, "strong orders": 0.62,
    "buyback": 0.55, "share buyback": 0.60, "dividend hike": 0.60,
    "trade deal": 0.70, "tariff pause": 0.72, "tariff relief": 0.75,
    "ceasefire": 0.65, "oil drops": 0.48, "oil falls": 0.45,
    "gas prices fall": 0.65, "energy prices fall": 0.65,
    "confidence rises": 0.62, "ifo rises": 0.72, "zew rises": 0.70,
    "pmi rises": 0.68, "improving eurozone": 0.58,
    # German Bullish Phrases
    "zinssenkung": 0.75, "leitzins sinkt": 0.75, "konjunkturpaket": 0.72,
    "inflation sinkt": 0.68, "inflation geht zurück": 0.68, "teuerung lässt nach": 0.68,
    "besser als erwartet": 0.72, "übertrifft erwartungen": 0.75, "erwartungen übertroffen": 0.75,
    "prognose angehoben": 0.80, "hebt ausblick": 0.78, "ausblick angehoben": 0.78,
    "gewinnsprung": 0.72, "rekordhoch": 0.70, "allzeithoch": 0.72,
    "erholt sich": 0.55, "erholung": 0.55, "kursrally": 0.65, "rallye": 0.62,
    "im plus": 0.48, "legt zu": 0.48, "legen zu": 0.48, "klettert": 0.48,
    "steigt über": 0.50, "aufwärts": 0.45, "starke zahlen": 0.68,
    "aktienrückkauf": 0.60, "dividende erhöht": 0.60, "kaufempfehlung": 0.58,
    "ifo steigt": 0.72, "zew steigt": 0.70, "wirtschaft wächst": 0.65,
    "aufschwung": 0.62, "rüstungsausgaben": 0.52, "gaspreis sinkt": 0.62,
}

BEARISH_PHRASES: Dict[str, float] = {
    # English Monetary / Macro
    "rate hike": -0.75, "raises interest rates": -0.80, "raise interest rates": -0.80,
    "hike rates": -0.75, "hikes rates": -0.75, "hawkish": -0.65,
    "higher for longer": -0.62, "inflation surges": -0.72,
    "inflation accelerates": -0.70, "inflation jumps": -0.70,
    "inflation pressures": -0.65, "energy inflation": -0.68,
    "stay elevated": -0.58, "stays elevated": -0.58, "remains elevated": -0.58,
    "pause rate cuts": -0.65, "delay rate cuts": -0.65, "yields surge": -0.60,
    "hotter inflation": -0.68, "sticky inflation": -0.60, "stagflation": -0.85,
    "recession": -0.82, "contraction": -0.72, "contracts": -0.65, "shrinks": -0.65,
    # English Corporate / Market
    "earnings miss": -0.75, "guidance cut": -0.80, "misses expectations": -0.75,
    "missed expectations": -0.75, "misses estimates": -0.72,
    "weaker than expected": -0.70, "worse than expected": -0.72,
    "profit warning": -0.88, "cuts guidance": -0.82, "slashes outlook": -0.82,
    "lowers forecast": -0.72, "downgrades": -0.60, "downgrade": -0.58,
    "layoffs": -0.60, "job cuts": -0.62, "plant closure": -0.72, "strikes": -0.50,
    "tariff": -0.55, "tariffs": -0.60, "trade war": -0.78, "import duties": -0.62,
    "retaliatory": -0.65, "sanctions": -0.55, "oil surges": -0.62,
    "oil spikes": -0.65, "gas prices surge": -0.75, "energy crisis": -0.80,
    "sell-off": -0.72, "selloff": -0.72, "rout": -0.75, "plunge": -0.72,
    "plunges": -0.72, "slumps": -0.68, "tumbles": -0.68, "drops": -0.48,
    "falls": -0.45, "slides": -0.52, "steepest weekly drop": -0.75,
    "declines": -0.48, "retreats": -0.45, "losses": -0.52,
    "turmoil": -0.68, "crisis": -0.72, "scandal": -0.65, "default": -0.75,
    "slowdown": -0.60, "sluggish": -0.55, "stagnation": -0.68, "headwinds": -0.55,
    "weak demand": -0.68, "china slowdown": -0.70, "bearish": -0.65,
    "ifo falls": -0.72, "zew falls": -0.70, "pmi falls": -0.68,
    "geopolitical tension": -0.60, "escalation": -0.65, "supply disruption": -0.62,
    # German Bearish Phrases
    "zinserhöhung": -0.78, "zinsen steigen": -0.68, "inflation steigt": -0.70,
    "teuerung zieht an": -0.68, "rezession": -0.82, "wirtschaft schrumpft": -0.75,
    "konjunkturschwäche": -0.68, "abschwung": -0.65, "stagnation": -0.65,
    "gewinnwarnung": -0.88, "prognose gesenkt": -0.82, "senkt ausblick": -0.80,
    "ausblick gesenkt": -0.80, "gewinn bricht ein": -0.78, "umsatzrückgang": -0.65,
    "schlechter als erwartet": -0.72, "enttäuscht": -0.62, "verfehlt erwartungen": -0.74,
    "stellenabbau": -0.65, "streicht stellen": -0.65, "werksschließung": -0.72,
    "kurssturz": -0.78, "stürzt ab": -0.75, "bricht ein": -0.75, "abverkauf": -0.75,
    "im minus": -0.48, "unter druck": -0.52, "rutscht ab": -0.58, "verliert": -0.45,
    "talfahrt": -0.70, "schlusslicht": -0.45, "handelskrieg": -0.78, "strafzölle": -0.68,
    "zölle": -0.55, "energiekrise": -0.80, "ölpreis steigt": -0.58,
    "gaspreis steigt": -0.70, "ifo fällt": -0.72, "zew fällt": -0.70,
}

SINGLE_BULLISH_WORDS = {
    "rally": 0.45, "bullish": 0.55, "surge": 0.42, "soar": 0.45, "boom": 0.45,
    "strong": 0.30, "resilient": 0.38, "outperforms": 0.45, "upbeat": 0.45,
    "optimistic": 0.42, "tailwind": 0.45, "tailwinds": 0.45, "growth": 0.25,
    "profit": 0.25, "profits": 0.25, "beats": 0.48, "easing": 0.38, "stimulus": 0.50,
    "rebound": 0.42, "recovery": 0.40, "boost": 0.40, "boosts": 0.40,
    "positively": 0.48, "positive": 0.35, "optimism": 0.45, "improves": 0.42, "improving": 0.38,
    # German singles
    "stark": 0.32, "wachstum": 0.30, "gewinn": 0.28, "gewinne": 0.32, "zuversicht": 0.45,
    "optimismus": 0.45, "aufschwung": 0.50, "steigt": 0.25, "positiv": 0.35, "rückenwind": 0.45,
}

SINGLE_BEARISH_WORDS = {
    "slump": -0.50, "plunge": -0.55, "crash": -0.65, "rout": -0.58, "tumble": -0.52,
    "weak": -0.35, "weakness": -0.38, "slowing": -0.38, "slows": -0.35, "shrink": -0.48,
    "threat": -0.38, "risk": -0.25, "risks": -0.25, "deficit": -0.32, "debt": -0.22,
    "cut": -0.20, "cuts": -0.25, "loss": -0.40, "warning": -0.50, "trouble": -0.45,
    "troubled": -0.45, "concern": -0.32, "concerns": -0.35, "pressure": -0.32,
    "strain": -0.38, "drag": -0.40, "drags": -0.40, "fades": -0.38, "pain": -0.45,
    "warns": -0.38, "warned": -0.35, "elevated": -0.25, "fear": -0.42, "fears": -0.45,
    # German singles
    "schwach": -0.42, "schwäche": -0.42, "verlust": -0.45, "verluste": -0.48,
    "warnung": -0.50, "warnt": -0.40, "krise": -0.60, "druck": -0.32, "sorge": -0.38,
    "sorgen": -0.40, "rückgang": -0.45, "einbruch": -0.62, "flaute": -0.52,
    "risiko": -0.28, "risiken": -0.28, "gegenwind": -0.45, "schrumpft": -0.55,
}

NEGATIONS = {
    "not", "no", "never", "unlikely", "fails", "failed", "without", "less", "avoids", "avoid",
    "nicht", "kein", "keine", "ohne", "kaum", "vermeidet",
}

CONTRAST_MARKERS = re.compile(
    r"\b(?:despite|even as|although|though|while|trotz|obwohl|obgleich)\b",
    re.IGNORECASE,
)

GERMAN_HINT_WORDS = {
    "der", "die", "das", "und", "mit", "für", "auf", "bei", "nach", "von",
    "aus", "aktie", "aktien", "börse", "ezb", "zinsen", "wirtschaft", "kurssturz",
    "unter", "über", "steigt", "fällt", "sinkt", "deutschland"
}


def _clean_text(text: str) -> str:
    text = html_lib.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_language(title: str, summary: str = "") -> str:
    tokens = set(re.findall(r"[a-zäöüß]+", f"{title} {summary}".lower()))
    de_hits = len(tokens & GERMAN_HINT_WORDS)
    has_umlaut = any(ch in f"{title}{summary}".lower() for ch in "äöüß")
    return "DE" if (de_hits >= 2 or (has_umlaut and de_hits >= 1)) else "EN"


def is_relevant_to_dax(title: str, summary: str = "") -> bool:
    combined = f" {title.lower()} {summary.lower()} "
    for cfg in CHANNEL_RULES.values():
        if any(kw in combined for kw in cfg["keywords"]):
            return True
    broad_macro_terms = [
        "europe", "european", "europa", "europäisch", "frankfurt", "stoxx", "euro",
        "inflation", "gdp", "bip", "interest rate", "leitzins", "central bank",
        "zentralbank", "bond", "anleihe", "yield", "rendite", "stock market",
        "aktienmarkt", "equities", "tariff", "zölle", "trade", "handel", "oil",
        "öl", "gas", "energy", "energie", "recession", "rezession", "economy",
        "wirtschaft", "pmi", "earnings", "quartalszahlen", "manufacturing", "exports"
    ]
    return any(t in combined for t in broad_macro_terms)


def classify_channel_and_sectors(title: str, summary: str, feed_category: str = "") -> Tuple[str, str, str, List[str]]:
    combined = f" {title.lower()} {summary.lower()} "
    scores: Dict[str, int] = {}
    for key, cfg in CHANNEL_RULES.items():
        hits = sum(1 for kw in cfg["keywords"] if kw in combined)
        if hits > 0:
            scores[key] = hits
    if scores:
        best_key = max(
            scores.keys(),
            key=lambda k: (scores[k], 1 if CHANNEL_RULES[k]["impact_type"] == "direct" else 0)
        )
    elif feed_category in CHANNEL_RULES:
        best_key = feed_category
    else:
        best_key = "global_us"

    cfg = CHANNEL_RULES[best_key]
    sectors = [sec for sec, kws in SECTOR_KEYWORDS.items() if any(kw in combined for kw in kws)]
    if not sectors:
        sectors = ["Broad DAX 40"]
    return best_key, cfg["label"], cfg["impact_type"], sectors[:3]


def _build_transmission_note(
    channel_key: str, sentiment_label: str, sectors: List[str], combined_lower: str, lang: str
) -> str:
    sector_str = ", ".join(sectors)
    lang_tag = "[DE Primary] " if lang == "DE" else ""
    if channel_key == "dax_bluechips":
        if "Bullish" in sentiment_label:
            return f"{lang_tag}Direct equity catalyst for {sector_str}, lifting heavyweight DAX 40 earnings expectations."
        if "Bearish" in sentiment_label:
            return f"{lang_tag}Direct fundamental drag on {sector_str}, weighing on Frankfurt benchmark sentiment."
        return f"{lang_tag}Direct corporate/index update affecting {sector_str} constituents inside the DAX 40."
    if channel_key == "german_macro":
        if ("inflation" in combined_lower or "teuerung" in combined_lower) and any(
            x in combined_lower for x in ["accelerate", "rise", "hot", "steigt", "zieht an"]
        ):
            return f"{lang_tag}Direct German macro signal: hotter domestic inflation complicates ECB easing and pressures rate-sensitive equities."
        if "Bullish" in sentiment_label:
            return f"{lang_tag}Direct German macro tailwind: stronger domestic activity supports DAX cyclical revenues and confidence."
        if "Bearish" in sentiment_label:
            return f"{lang_tag}Direct German macro headwind: sluggish domestic growth data dampens earnings outlook for German equities."
        return f"{lang_tag}Direct German macroeconomic development influencing domestic growth and fiscal expectations."
    if channel_key == "ecb_rates":
        if any(x in combined_lower for x in ["cut", "dovish", "cooling", "zinssenkung", "sinkt"]):
            return f"{lang_tag}Indirect monetary tailwind: looser ECB rate expectations lower discount rates and support European valuations."
        if any(x in combined_lower for x in ["hike", "hawkish", "surge", "zinserhöhung", "elevated", "steigt"]):
            return f"{lang_tag}Indirect monetary headwind: tighter ECB policy or sticky Eurozone inflation pressures DAX valuation multiples."
        if "eur" in combined_lower and ("weak" in combined_lower or "falls" in combined_lower or "drops" in combined_lower):
            return f"{lang_tag}Indirect FX channel: a softer Euro enhances overseas revenue translation for export-heavy DAX multinationals."
        return f"{lang_tag}Indirect Eurozone monetary/FX channel shaping borrowing costs and DAX exporter competitiveness."
    if channel_key == "trade_tariffs":
        if "Bearish" in sentiment_label or "tariff" in combined_lower or "zöll" in combined_lower:
            return f"{lang_tag}Indirect trade spillover: tariff or external demand friction hits export-reliant DAX sectors ({sector_str})."
        return f"{lang_tag}Indirect trade catalyst: global trade and external demand developments drive earnings for {sector_str}."
    if channel_key == "energy_commodities":
        if "Bearish" in sentiment_label:
            return f"{lang_tag}Indirect cost shock: elevated oil/gas prices squeeze margins across energy-intensive German industrials and chemicals."
        return f"{lang_tag}Indirect input-cost driver: calmer energy prices ease industrial cost pressures and domestic inflation."
    if "Bullish" in sentiment_label:
        return f"{lang_tag}Indirect global risk-on spillover: supportive US/global macro cues boost cross-border equity flows into Frankfurt."
    if "Bearish" in sentiment_label:
        return f"{lang_tag}Indirect global risk-off spillover: Wall Street/Fed or geopolitical stress triggers global de-risking across the DAX."
    return f"{lang_tag}Indirect global macro signal influencing cross-asset risk appetite and institutional flows into European equities."


def _score_clause(clause: str, weight_mult: float, matched_signals: List[str]) -> float:
    padded = f" {clause.lower()} "
    s = 0.0
    for phrase, w in BULLISH_PHRASES.items():
        if phrase in padded:
            s += w * weight_mult
            matched_signals.append(f"+{phrase}")
    for phrase, w in BEARISH_PHRASES.items():
        if phrase in padded:
            s += w * weight_mult
            matched_signals.append(phrase)

    words = re.findall(r"[a-zäöüß]+", padded)
    for idx, w in enumerate(words):
        negated = bool(set(words[max(0, idx - 2):idx]) & NEGATIONS)
        if w in SINGLE_BULLISH_WORDS:
            val = SINGLE_BULLISH_WORDS[w] * weight_mult * 0.75
            s += (-val * 0.6) if negated else val
        elif w in SINGLE_BEARISH_WORDS:
            val = SINGLE_BEARISH_WORDS[w] * weight_mult * 0.75
            s += (-val * 0.6) if negated else val
    return s


def analyze_dax_news(title: str, summary: str = "", feed_category: str = "") -> Dict:
    """
    Clause-aware bilingual (EN + DE) DAX fundamental sentiment & transmission analyzer.
    """
    clean_title = _clean_text(title)
    clean_summary = _clean_text(summary)
    lang = detect_language(clean_title, clean_summary)
    combined = f"{clean_title}. {clean_summary}".strip()
    combined_lower = f" {combined.lower()} "

    channel_key, channel_label, impact_type, sectors = classify_channel_and_sectors(
        clean_title, clean_summary, feed_category
    )

    matched_signals: List[str] = []
    score = 0.0

    # Clause-contrast weighting on headline: outcome clause gets 1.45x, conceded clause after despite/trotz gets 0.55x
    parts = CONTRAST_MARKERS.split(clean_title, maxsplit=1)
    if len(parts) == 2:
        score += _score_clause(parts[0], 1.45, matched_signals)
        score += _score_clause(parts[1], 0.55, matched_signals)
    else:
        score += _score_clause(clean_title, 1.35, matched_signals)

    if clean_summary:
        score += _score_clause(clean_summary, 0.80, matched_signals)

    # Contextual macro overrides
    if ("inflation" in combined_lower or "teuerung" in combined_lower) and (
        "accelerate" in combined_lower or "rebound" in combined_lower or "zieht an" in combined_lower
    ):
        score -= 0.15 if ("growth" in combined_lower or "wachstum" in combined_lower) else 0.45

    if ("eur/usd" in combined_lower or "euro" in combined_lower) and ("weak" in combined_lower or "falls" in combined_lower):
        if "export" in combined_lower or "improving" in combined_lower:
            score += 0.25

    if any(x in combined_lower for x in ["tech rout", "rout", "kurssturz", "abverkauf"]):
        score -= 0.40

    normalized = int(round(100 * (score / (abs(score) + 1.15)))) if score != 0 else 0
    normalized = max(-98, min(98, normalized))

    if normalized >= 32:
        sentiment_label = "Bullish"
    elif normalized >= 12:
        sentiment_label = "Slightly Bullish"
    elif normalized <= -32:
        sentiment_label = "Bearish"
    elif normalized <= -12:
        sentiment_label = "Slightly Bearish"
    else:
        sentiment_label = "Neutral"

    abs_score = abs(normalized)
    high_impact_terms = [
        "ecb", "ezb", "lagarde", "bundesbank", "ifo", "zew", "cpi", "inflation", "gdp", "bip",
        "tariff", "zölle", "fed", "powell", "dax", "sap", "siemens", "allianz", "volkswagen",
        "airbus", "deutsche bank", "rate cut", "zinssenkung", "rate hike", "zinserhöhung",
        "profit warning", "gewinnwarnung", "recession", "rezession", "kurssturz"
    ]
    term_hits = sum(1 for t in high_impact_terms if t in combined_lower)

    if (impact_type == "direct" and (abs_score >= 28 or term_hits >= 2)) or (abs_score >= 45 and term_hits >= 1):
        impact_level = "High"
    elif abs_score >= 15 or term_hits >= 1 or impact_type == "direct":
        impact_level = "Medium"
    else:
        impact_level = "Low"

    # Deduplicate matched signals preserving order
    unique_signals = list(dict.fromkeys(matched_signals))[:5]

    return {
        "lang": lang,
        "sentiment_score": normalized,
        "sentiment_label": sentiment_label,
        "channel_key": channel_key,
        "channel_label": channel_label,
        "impact_type": impact_type,
        "impact_level": impact_level,
        "sectors": sectors,
        "transmission_note": _build_transmission_note(channel_key, sentiment_label, sectors, combined_lower, lang),
        "signals": unique_signals,
    }


# ==============================================================================
# GOLD (XAU / GC=F) BILINGUAL FUNDAMENTAL SENTIMENT ENGINE
# ==============================================================================

GOLD_CHANNEL_RULES = {
    "gold_fed_yields": {
        "label": "Fed Policy & Real Yields",
        "impact_type": "direct",
        "keywords": [
            "fed", "fomc", "powell", "real yield", "realzins", "treasury", "10-year", "rate cut",
            "rate hike", "zinssenkung", "zinserhöhung", "dovish", "hawkish", "yields", "anleiherenditen",
        ],
    },
    "gold_usd_dxy": {
        "label": "US Dollar (DXY) & FX",
        "impact_type": "direct",
        "keywords": [
            "dollar", "dxy", "greenback", "us-dollar", "currency", "fx", "dollar index",
        ],
    },
    "gold_geopolitics": {
        "label": "Safe-Haven & Geopolitics",
        "impact_type": "indirect",
        "keywords": [
            "safe haven", "safe-haven", "sicherer hafen", "geopolit", "war", "krieg", "conflict",
            "missile", "tariff", "zölle", "crisis", "krise", "uncertainty", "unsicherheit",
        ],
    },
    "gold_central_banks": {
        "label": "Central Bank & ETF Demand",
        "impact_type": "direct",
        "keywords": [
            "central bank", "notenbank", "zentralbank", "pboc", "reserve", "reserven", "etf",
            "inflow", "outflow", "zuflüsse", "abflüsse", "physical demand", "bullion", "wgc",
        ],
    },
    "gold_inflation_macro": {
        "label": "Inflation, CPI & Macro Risk",
        "impact_type": "indirect",
        "keywords": [
            "inflation", "cpi", "pce", "stagflation", "jobs", "payroll", "nfp", "recession",
            "rezession", "debt", "schuld", "deficit", "goldpreis", "xau",
        ],
    },
}

GOLD_BULLISH_PHRASES = {
    "gold rises": 0.9, "gold rallies": 1.0, "gold surges": 1.15, "gold climbs": 0.85, "gold gains": 0.85,
    "gold jumps": 1.0, "gold rebounds": 0.85, "record high": 1.1, "all-time high": 1.15,
    "goldpreis steigt": 0.9, "gold legt zu": 0.85, "rekordhoch": 1.1,
    "safe haven": 0.85, "safe-haven demand": 1.0, "sicherer hafen": 0.85,
    "rate cut": 0.95, "rate cuts": 0.95, "zinssenkung": 0.95, "dovish": 0.85,
    "yields fall": 0.9, "yields drop": 0.9, "dollar weakens": 0.9, "dollar falls": 0.9,
    "weak dollar": 0.85, "schwacher dollar": 0.85, "central bank buying": 1.05,
    "etf inflows": 0.9, "geopolitical tension": 0.8, "stagflation": 0.75,
}

GOLD_BEARISH_PHRASES = {
    "gold falls": -0.9, "gold drops": -0.95, "gold slides": -1.0, "gold tumbles": -1.1, "gold slumps": -1.1,
    "longest slump": -1.1, "gold extends slump": -1.1, "gold retreats": -0.8, "gold sinks": -1.0,
    "goldpreis fällt": -0.9, "gold unter druck": -0.9, "gold verliert": -0.85,
    "rate hike": -0.95, "rate hikes": -0.95, "zinserhöhung": -0.95, "hawkish": -0.85,
    "higher for longer": -0.85, "yields surge": -0.95, "yields rise": -0.8, "realzins": -0.6,
    "dollar surges": -0.95, "strong dollar": -0.85, "starker dollar": -0.85,
    "etf outflows": -0.9, "profit taking": -0.65, "gewinnmitnahmen": -0.65,
}


def analyze_gold_news(title: str, summary: str = "", feed_category: str = "") -> Dict:
    clean_title = _clean_text(title)
    clean_summary = _clean_text(summary)
    lang = detect_language(clean_title, clean_summary)
    combined = f"{clean_title}. {clean_summary}".strip()
    combined_lower = f" {combined.lower()} "

    # Channel classification
    best_key, best_hits = "gold_inflation_macro", 0
    for ck, cfg in GOLD_CHANNEL_RULES.items():
        hits = sum(1 for kw in cfg["keywords"] if kw in combined_lower)
        if hits > best_hits:
            best_hits = hits
            best_key = ck
    ch_cfg = GOLD_CHANNEL_RULES[best_key]

    matched_signals: List[str] = []
    score = 0.0

    def _score_gold_clause(clause: str, mult: float) -> float:
        pad = f" {clause.lower()} "
        s = 0.0
        for p, w in GOLD_BULLISH_PHRASES.items():
            if p in pad:
                s += w * mult
                matched_signals.append(f"+{p}")
        for p, w in GOLD_BEARISH_PHRASES.items():
            if p in pad:
                s += w * mult
                matched_signals.append(p)
        return s

    parts = CONTRAST_MARKERS.split(clean_title, maxsplit=1)
    if len(parts) == 2:
        score += _score_gold_clause(parts[0], 1.45)
        score += _score_gold_clause(parts[1], 0.55)
    else:
        score += _score_gold_clause(clean_title, 1.35)
    if clean_summary:
        score += _score_gold_clause(clean_summary, 0.80)

    normalized = int(round(100 * (score / (abs(score) + 1.05)))) if score != 0 else 0
    normalized = max(-98, min(98, normalized))

    if normalized >= 30:
        sentiment_label = "Bullish"
    elif normalized >= 10:
        sentiment_label = "Slightly Bullish"
    elif normalized <= -30:
        sentiment_label = "Bearish"
    elif normalized <= -10:
        sentiment_label = "Slightly Bearish"
    else:
        sentiment_label = "Neutral"

    abs_score = abs(normalized)
    hi_terms = ["fed", "fomc", "powell", "cpi", "nfp", "rate cut", "rate hike", "zinserhöhung", "zinssenkung", "dxy", "real yield", "record", "crash", "slump", "central bank"]
    hits = sum(1 for t in hi_terms if t in combined_lower)
    impact_level = "High" if (abs_score >= 28 or hits >= 2) else ("Medium" if abs_score >= 12 or hits >= 1 else "Low")

    lang_tag = "[DE] " if lang == "DE" else ""
    if best_key == "gold_fed_yields":
        note = f"{lang_tag}Direct Gold rates channel: Fed policy & US real yield expectations directly reprice non-yielding bullion."
    elif best_key == "gold_usd_dxy":
        note = f"{lang_tag}Direct Gold FX channel: US Dollar Index (DXY) direction inversely drives XAU/USD institutional flows."
    elif best_key == "gold_central_banks":
        note = f"{lang_tag}Direct physical/ETF flow: sovereign central-bank reserve demand & ETF positioning steer structural Gold trend."
    elif best_key == "gold_geopolitics":
        note = f"{lang_tag}Indirect safe-haven bid: geopolitical/tariff uncertainty triggers institutional defensive rotation into Gold."
    else:
        note = f"{lang_tag}Indirect macro/inflation signal affecting real-rate hedges and COMEX Gold positioning."

    return {
        "lang": lang,
        "sentiment_score": normalized,
        "sentiment_label": sentiment_label,
        "channel_key": best_key,
        "channel_label": ch_cfg["label"],
        "impact_type": ch_cfg["impact_type"],
        "impact_level": impact_level,
        "sectors": ["Precious Metals", "USD / Real Yields"],
        "transmission_note": note,
        "signals": list(dict.fromkeys(matched_signals))[:5],
    }


# ==============================================================================
# BITCOIN (BTC / BTC-USD) BILINGUAL FUNDAMENTAL SENTIMENT ENGINE
# ==============================================================================

BTC_CHANNEL_RULES = {
    "btc_etf_institutional": {
        "label": "Spot ETF & Institutional Flows",
        "impact_type": "direct",
        "keywords": [
            "etf", "blackrock", "ibit", "fidelity", "fbtc", "grayscale", "gbtc", "inflow", "outflow",
            "zuflüsse", "abflüsse", "microstrategy", "strategy", "corporate treasury", "sovereign wealth",
            "institutional", "institutionell", "custody", "spot bitcoin",
        ],
    },
    "btc_fed_liquidity": {
        "label": "Fed Liquidity, Macro & DXY",
        "impact_type": "direct",
        "keywords": [
            "fed", "fomc", "powell", "liquidity", "liquidität", "rate cut", "rate hike", "zinssenkung",
            "zinserhöhung", "cpi", "inflation", "pce", "dollar", "dxy", "treasury", "yield", "m2", "nasdaq",
        ],
    },
    "btc_regulation": {
        "label": "Regulation, SEC & MiCA Policy",
        "impact_type": "direct",
        "keywords": [
            "sec", "cftc", "mica", "bafin", "lawsuit", "klage", "approval", "zulassung", "ban", "verbot",
            "congress", "senate", "strategic bitcoin reserve", "executive order", "regulation", "regulierung",
            "tax", "steuer", "compliance",
        ],
    },
    "btc_onchain_miners": {
        "label": "On-Chain, Whales & Miners",
        "impact_type": "indirect",
        "keywords": [
            "whale", "wal", "miner", "mining", "hashrate", "halving", "exchange reserve", "börsenbestand",
            "liquidation", "liquidierung", "open interest", "funding rate", "short squeeze", "long squeeze",
            "dormant", "cold storage", "on-chain",
        ],
    },
    "btc_market_sentiment": {
        "label": "Crypto Market & Risk Sentiment",
        "impact_type": "indirect",
        "keywords": [
            "bitcoin", "btc", "crypto", "krypto", "ethereum", "eth", "altcoin", "stablecoin", "tether",
            "usdt", "coinbase", "binance", "bitcoinkurs", "kryptowährung", "hack", "exploit",
        ],
    },
}

BTC_BULLISH_PHRASES = {
    "bitcoin surges": 1.1, "bitcoin rallies": 1.0, "bitcoin jumps": 1.0, "bitcoin climbs": 0.9,
    "bitcoin rises": 0.85, "bitcoin breaks": 0.95, "bitcoin rebounds": 0.9, "btc surges": 1.1,
    "all-time high": 1.15, "record high": 1.1, "rekordhoch": 1.1, "bitcoin steigt": 0.9,
    "bitcoin legt zu": 0.85, "krypto-rally": 1.0, "etf inflows": 1.1, "net inflows": 1.0,
    "record inflows": 1.15, "blackrock buys": 1.0, "microstrategy buys": 0.9, "buys bitcoin": 0.9,
    "strategic reserve": 1.1, "short squeeze": 0.9, "whale accumulation": 0.95, "accumulation": 0.75,
    "rate cut": 0.9, "dovish": 0.8, "liquidity expansion": 0.9, "sec approves": 1.05, "adoption": 0.75,
}

BTC_BEARISH_PHRASES = {
    "bitcoin falls": -0.9, "bitcoin drops": -0.95, "bitcoin slides": -1.0, "bitcoin plunges": -1.15,
    "bitcoin crashes": -1.2, "bitcoin tumbles": -1.1, "bitcoin sinks": -1.0, "btc drops": -0.95,
    "bitcoin fällt": -0.9, "bitcoin verliert": -0.85, "krypto-crash": -1.15, "kurssturz": -1.1,
    "etf outflows": -1.05, "net outflows": -0.95, "massive liquidations": -1.0, "long squeeze": -0.85,
    "sec sues": -0.95, "lawsuit": -0.8, "crackdown": -0.9, "crypto ban": -1.05, "verbot": -0.95,
    "hack": -0.95, "exploit": -0.9, "bankruptcy": -1.0, "insolvenz": -1.0,
    "rate hike": -0.9, "hawkish": -0.85, "dollar surges": -0.85, "miner capitulation": -0.85,
    "sell-off": -0.9, "abverkauf": -0.9, "profit taking": -0.6, "gewinnmitnahmen": -0.6,
}


def analyze_btc_news(title: str, summary: str = "", feed_category: str = "") -> Dict:
    clean_title = _clean_text(title)
    clean_summary = _clean_text(summary)
    lang = detect_language(clean_title, clean_summary)
    combined = f"{clean_title}. {clean_summary}".strip()
    combined_lower = f" {combined.lower()} "

    best_key, best_hits = "btc_market_sentiment", 0
    for ck, cfg in BTC_CHANNEL_RULES.items():
        hits = sum(1 for kw in cfg["keywords"] if kw in combined_lower)
        if hits > best_hits:
            best_hits = hits
            best_key = ck
    ch_cfg = BTC_CHANNEL_RULES[best_key]

    matched_signals: List[str] = []
    score = 0.0

    def _score_btc_clause(clause: str, mult: float) -> float:
        pad = f" {clause.lower()} "
        s = 0.0
        for p, w in BTC_BULLISH_PHRASES.items():
            if p in pad:
                s += w * mult
                matched_signals.append(f"+{p}")
        for p, w in BTC_BEARISH_PHRASES.items():
            if p in pad:
                s += w * mult
                matched_signals.append(p)
        words = re.findall(r"[a-zäöüß]+", pad)
        for idx, w in enumerate(words):
            negated = bool(set(words[max(0, idx - 2):idx]) & NEGATIONS)
            if w in SINGLE_BULLISH_WORDS:
                val = SINGLE_BULLISH_WORDS[w] * mult * 0.65
                s += (-val * 0.6) if negated else val
            elif w in SINGLE_BEARISH_WORDS:
                val = SINGLE_BEARISH_WORDS[w] * mult * 0.65
                s += (-val * 0.6) if negated else val
        return s

    parts = CONTRAST_MARKERS.split(clean_title, maxsplit=1)
    if len(parts) == 2:
        score += _score_btc_clause(parts[0], 1.45)
        score += _score_btc_clause(parts[1], 0.55)
    else:
        score += _score_btc_clause(clean_title, 1.35)
    if clean_summary:
        score += _score_btc_clause(clean_summary, 0.80)

    normalized = int(round(100 * (score / (abs(score) + 1.15)))) if score != 0 else 0
    normalized = max(-98, min(98, normalized))

    if normalized >= 30:
        sentiment_label = "Bullish"
    elif normalized >= 10:
        sentiment_label = "Slightly Bullish"
    elif normalized <= -30:
        sentiment_label = "Bearish"
    elif normalized <= -10:
        sentiment_label = "Slightly Bearish"
    else:
        sentiment_label = "Neutral"

    abs_score = abs(normalized)
    hi_terms = ["etf", "blackrock", "sec", "fed", "fomc", "powell", "cpi", "liquidation", "hack", "halving", "record", "crash", "surge", "inflow", "outflow", "reserve"]
    hits = sum(1 for t in hi_terms if t in combined_lower)
    impact_level = "High" if (abs_score >= 28 or hits >= 2) else ("Medium" if abs_score >= 12 or hits >= 1 else "Low")

    lang_tag = "[DE] " if lang == "DE" else ""
    if best_key == "btc_etf_institutional":
        note = f"{lang_tag}Direct BTC ETF/institutional flow: Spot ETF creations/redemptions & treasury buys directly absorb or release BTC supply."
    elif best_key == "btc_fed_liquidity":
        note = f"{lang_tag}Direct BTC liquidity channel: Fed rate expectations, global M2 & DXY drive high-beta risk appetite for Bitcoin."
    elif best_key == "btc_regulation":
        note = f"{lang_tag}Direct regulatory catalyst: SEC/MiCA/sovereign policy shifts reprice institutional Bitcoin access."
    elif best_key == "btc_onchain_miners":
        note = f"{lang_tag}Indirect on-chain & derivatives flow: whale positioning, open interest & liquidation sweeps steer short-term BTC volatility."
    else:
        note = f"{lang_tag}Indirect crypto market sentiment signal influencing BTC spot/perp momentum."

    return {
        "lang": lang,
        "sentiment_score": normalized,
        "sentiment_label": sentiment_label,
        "channel_key": best_key,
        "channel_label": ch_cfg["label"],
        "impact_type": ch_cfg["impact_type"],
        "impact_level": impact_level,
        "sectors": ["Bitcoin Spot/Perps", "Crypto Liquidity"],
        "transmission_note": note,
        "signals": list(dict.fromkeys(matched_signals))[:5],
    }

