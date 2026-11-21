import asyncio
import email.utils
import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

from sentiment import (
    analyze_dax_news,
    analyze_gold_news,
    analyze_btc_news,
    is_relevant_to_dax,
    CHANNEL_RULES,
    GOLD_CHANNEL_RULES,
    BTC_CHANNEL_RULES,
)
from smc import analyze_smc_suite, classify_event_killzone

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

HISTORY_FILE = Path(__file__).resolve().parent / "dax_history.json"
GOLD_HISTORY_FILE = Path(__file__).resolve().parent / "gold_history.json"
BTC_HISTORY_FILE = Path(__file__).resolve().parent / "btc_history.json"

NEWS_FEEDS = [
    # English Direct & Indirect Feeds
    {
        "id": "dax_direct",
        "name": "DAX 40 & Frankfurt Equities",
        "category": "dax_bluechips",
        "url": "https://news.google.com/rss/search?q=%22DAX%22+OR+%22DAX+40%22+Frankfurt+stocks&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "yahoo_gdaxi",
        "name": "Yahoo Finance DAX",
        "category": "dax_bluechips",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGDAXI&region=US&lang=en-US",
    },
    {
        "id": "german_macro",
        "name": "German Economy & Macro",
        "category": "german_macro",
        "url": "https://news.google.com/rss/search?q=Germany+economy+OR+Bundesbank+OR+Ifo+OR+ZEW+OR+German+PMI+OR+German+inflation+OR+Destatis&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "dw_business",
        "name": "DW Business Germany",
        "category": "german_macro",
        "url": "https://rss.dw.com/xml/rss-en-bus",
    },
    {
        "id": "ecb_official",
        "name": "ECB Official Press",
        "category": "ecb_rates",
        "url": "https://www.ecb.europa.eu/rss/press.html",
    },
    {
        "id": "ecb_eurozone",
        "name": "ECB & Eurozone Policy",
        "category": "ecb_rates",
        "url": "https://news.google.com/rss/search?q=ECB+interest+rates+OR+Lagarde+OR+Eurozone+inflation+OR+EUR+USD&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "dax_bluechips",
        "name": "DAX Heavyweights",
        "category": "dax_bluechips",
        "url": "https://news.google.com/rss/search?q=(SAP+OR+Siemens+OR+Allianz+OR+Airbus+OR+Volkswagen+OR+Mercedes+OR+BASF+OR+Deutsche+Bank+OR+Rheinmetall)+stock+OR+earnings&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "trade_tariffs",
        "name": "Global Trade & Tariffs",
        "category": "trade_tariffs",
        "url": "https://news.google.com/rss/search?q=(EU+OR+Germany+OR+China)+tariffs+OR+trade+war+OR+autos+exports&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "energy_europe",
        "name": "European Energy & Oil",
        "category": "energy_commodities",
        "url": "https://news.google.com/rss/search?q=European+natural+gas+TTF+OR+oil+price+OPEC+Germany+energy&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "cnbc_europe",
        "name": "CNBC Europe Markets",
        "category": "global_us",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19794221",
    },
    {
        "id": "global_spillover",
        "name": "US Fed & Global Macro",
        "category": "global_us",
        "url": "https://news.google.com/rss/search?q=(Federal+Reserve+OR+US+tariffs+OR+S%26P+500+OR+Wall+Street+OR+US+CPI)+markets+Europe&hl=en-US&gl=US&ceid=US:en",
    },
    # German Primary Financial & Official Feeds
    {
        "id": "gnews_de_dax",
        "name": "Google News DE (DAX/EZB)",
        "category": "dax_bluechips",
        "url": "https://news.google.com/rss/search?q=DAX+OR+EZB+OR+Bundesbank+OR+Ifo+OR+Konjunktur&hl=de&gl=DE&ceid=DE:de",
    },
    {
        "id": "tagesschau_wirt",
        "name": "tagesschau Wirtschaft",
        "category": "german_macro",
        "url": "https://www.tagesschau.de/wirtschaft/index~rss2.xml",
    },
    {
        "id": "handelsblatt_de",
        "name": "Handelsblatt Wirtschaft",
        "category": "dax_bluechips",
        "url": "https://www.handelsblatt.com/contentexport/feed/wirtschaft",
    },
    {
        "id": "finanzen_de",
        "name": "finanzen.net News",
        "category": "dax_bluechips",
        "url": "https://www.finanzen.net/rss/news",
    },
]

GOLD_NEWS_FEEDS = [
    {
        "id": "gold_xau_en",
        "name": "Gold & Bullion (EN)",
        "category": "gold_fed_yields",
        "url": "https://news.google.com/rss/search?q=%22gold+price%22+OR+XAUUSD+OR+bullion+OR+%22Federal+Reserve%22+gold&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "gold_macro_en",
        "name": "Gold Rates, DXY & Central Banks",
        "category": "gold_central_banks",
        "url": "https://news.google.com/rss/search?q=(gold+price+DXY+OR+%22real+yields%22+gold+OR+central+bank+gold+reserves+OR+gold+ETF)&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "gold_de",
        "name": "Goldpreis & Edelmetalle (DE)",
        "category": "gold_inflation_macro",
        "url": "https://news.google.com/rss/search?q=Goldpreis+OR+%22Gold+Kurs%22+OR+Edelmetall+Fed+Zinsen&hl=de&gl=DE&ceid=DE:de",
    },
]

BTC_NEWS_FEEDS = [
    {
        "id": "btc_coindesk",
        "name": "CoinDesk Bitcoin",
        "category": "btc_market_sentiment",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    },
    {
        "id": "btc_cointelegraph",
        "name": "Cointelegraph",
        "category": "btc_market_sentiment",
        "url": "https://cointelegraph.com/rss",
    },
    {
        "id": "btc_echo_de",
        "name": "BTC-ECHO (DE)",
        "category": "btc_etf_institutional",
        "url": "https://www.btc-echo.de/feed/",
    },
    {
        "id": "btc_gnews_en",
        "name": "Bitcoin ETF & Macro (EN)",
        "category": "btc_etf_institutional",
        "url": "https://news.google.com/rss/search?q=Bitcoin+OR+BTC+ETF+OR+crypto+macro&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "id": "btc_gnews_de",
        "name": "Bitcoin & Krypto Kurs (DE)",
        "category": "btc_fed_liquidity",
        "url": "https://news.google.com/rss/search?q=Bitcoin+OR+Krypto+Kurs&hl=de&gl=DE&ceid=DE:de",
    },
]

MARKET_SYMBOLS = [
    {"symbol": "^GDAXI", "name": "DAX 40", "role": "Primary Index", "unit": "pts"},
    {"symbol": "GC=F", "name": "Gold (GC=F)", "role": "Second Tracked Instrument", "unit": "$"},
    {"symbol": "BTC-USD", "name": "Bitcoin (BTC-USD)", "role": "Third Tracked Instrument", "unit": "$"},
    {"symbol": "ETH-USD", "name": "Ethereum (ETH-USD)", "role": "BTC SMT Peer", "unit": "$"},
    {"symbol": "EURUSD=X", "name": "EUR / USD", "role": "FX / Exporter Driver", "unit": ""},
    {"symbol": "DX-Y.NYB", "name": "US Dollar (DXY)", "role": "Gold Inverse Anchor", "unit": ""},
    {"symbol": "SI=F", "name": "Silver (SI=F)", "role": "Gold SMT Peer", "unit": "$"},
    {"symbol": "^STOXX50E", "name": "Euro Stoxx 50", "role": "Eurozone Peer", "unit": "pts"},
    {"symbol": "^GSPC", "name": "S&P 500", "role": "US Risk Spillover", "unit": "pts"},
    {"symbol": "TTF=F", "name": "EU Nat Gas (TTF)", "role": "Industrial Energy", "unit": "€"},
    {"symbol": "BZ=F", "name": "Brent Crude", "role": "Oil / Inflation", "unit": "$"},
    {"symbol": "^HSI", "name": "Hang Seng (China)", "role": "DAX Export Demand", "unit": "pts"},
    {"symbol": "^VIX", "name": "CBOE VIX", "role": "Global Volatility", "unit": ""},
    {"symbol": "^TNX", "name": "US 10Y Yield", "role": "Global Rate Anchor", "unit": "%"},
]

DAX_CONSTITUENTS = [
    {"symbol": "SAP.DE", "name": "SAP SE", "sector": "Tech & Semis"},
    {"symbol": "IFX.DE", "name": "Infineon", "sector": "Tech & Semis"},
    {"symbol": "SIE.DE", "name": "Siemens AG", "sector": "Industrials & Defense"},
    {"symbol": "AIR.DE", "name": "Airbus SE", "sector": "Industrials & Defense"},
    {"symbol": "RHM.DE", "name": "Rheinmetall", "sector": "Industrials & Defense"},
    {"symbol": "ALV.DE", "name": "Allianz SE", "sector": "Financials"},
    {"symbol": "MUV2.DE", "name": "Munich Re", "sector": "Financials"},
    {"symbol": "DBK.DE", "name": "Deutsche Bank", "sector": "Financials"},
    {"symbol": "CBK.DE", "name": "Commerzbank", "sector": "Financials"},
    {"symbol": "VOW3.DE", "name": "Volkswagen", "sector": "Autos"},
    {"symbol": "MBG.DE", "name": "Mercedes-Benz", "sector": "Autos"},
    {"symbol": "BMW.DE", "name": "BMW AG", "sector": "Autos"},
    {"symbol": "BAS.DE", "name": "BASF SE", "sector": "Chemicals & Energy"},
    {"symbol": "BAYN.DE", "name": "Bayer AG", "sector": "Chemicals & Energy"},
    {"symbol": "RWE.DE", "name": "RWE AG", "sector": "Chemicals & Energy"},
    {"symbol": "EOAN.DE", "name": "E.ON SE", "sector": "Chemicals & Energy"},
    {"symbol": "DTE.DE", "name": "Deutsche Telekom", "sector": "Consumer & Healthcare"},
    {"symbol": "ADS.DE", "name": "Adidas AG", "sector": "Consumer & Healthcare"},
    {"symbol": "MRK.DE", "name": "Merck KGaA", "sector": "Consumer & Healthcare"},
    {"symbol": "HEN3.DE", "name": "Henkel AG", "sector": "Consumer & Healthcare"},
]

CATALYST_SCHEDULE = [
    {
        "date": "2026-11-24",
        "time": "10:00 CET",
        "event": "Germany Ifo Business Climate Index (Nov)",
        "impact_type": "direct",
        "importance": "High",
        "query": "Germany Ifo Business Climate",
        "note": "Key domestic cyclical gauge for Siemens, BASF, and German industrials (prior: 90.2).",
    },
    {
        "date": "2026-11-26",
        "time": "13:30 CET",
        "event": "ECB Monetary Policy Meeting Accounts",
        "impact_type": "indirect",
        "importance": "Medium",
        "query": "ECB monetary policy accounts",
        "note": "Reveals Governing Council split on rate path and inflation persistence.",
    },
    {
        "date": "2026-11-30",
        "time": "14:00 CET",
        "event": "Germany CPI Flash Inflation (Nov)",
        "impact_type": "direct",
        "importance": "High",
        "query": "Germany inflation CPI Destatis",
        "note": "Direct driver of Bund yields and ECB rate expectations.",
    },
    {
        "date": "2026-12-01",
        "time": "11:00 CET",
        "event": "Eurozone HICP Flash Inflation & German PMI",
        "impact_type": "indirect",
        "importance": "High",
        "query": "Eurozone inflation HICP PMI",
        "note": "Sets tone for December ECB Governing Council rate decision.",
    },
    {
        "date": "2026-12-04",
        "time": "14:30 CET",
        "event": "US Nonfarm Payrolls (Nov BLS Jobs Report)",
        "impact_type": "indirect",
        "importance": "High",
        "query": "US nonfarm payrolls jobs report",
        "note": "Major global risk-appetite & US Treasury yield catalyst affecting DAX afternoon trade.",
    },
    {
        "date": "2026-12-09",
        "time": "20:00 CET",
        "event": "US Federal Reserve FOMC Rate Decision & Dot Plot",
        "impact_type": "indirect",
        "importance": "High",
        "query": "FOMC Federal Reserve rate decision",
        "note": "Drives EUR/USD, global equity multiples, and Wall Street spillover.",
    },
    {
        "date": "2026-12-15",
        "time": "11:00 CET",
        "event": "Germany ZEW Economic Sentiment (Dec)",
        "impact_type": "direct",
        "importance": "High",
        "query": "Germany ZEW economic sentiment",
        "note": "Institutional analyst expectations gauge (Nov beat at 35.6).",
    },
    {
        "date": "2026-12-17",
        "time": "10:00 CET",
        "event": "Germany Ifo Business Climate Index (Dec)",
        "impact_type": "direct",
        "importance": "High",
        "query": "Germany Ifo Business Climate",
        "note": "Year-end corporate sentiment check for DAX manufacturing & services.",
    },
    {
        "date": "2026-12-17",
        "time": "14:15 CET",
        "event": "ECB Governing Council Rate Decision & Macro Projections",
        "impact_type": "indirect",
        "importance": "High",
        "query": "ECB interest rate decision Lagarde",
        "note": "Primary Eurozone monetary policy catalyst + new ECB staff GDP/CPI forecasts.",
    },
    {
        "date": "2027-01-14",
        "time": "13:30 CET",
        "event": "ECB Monetary Policy Accounts Release",
        "impact_type": "indirect",
        "importance": "Medium",
        "query": "ECB monetary policy accounts",
        "note": "Minutes from the December 17 ECB policy meeting.",
    },
    {
        "date": "2027-01-27",
        "time": "20:00 CET",
        "event": "US FOMC Rate Decision",
        "impact_type": "indirect",
        "importance": "High",
        "query": "FOMC rate decision",
        "note": "First 2027 Fed policy decision.",
    },
    {
        "date": "2027-02-04",
        "time": "14:15 CET",
        "event": "ECB Governing Council Rate Decision",
        "impact_type": "indirect",
        "importance": "High",
        "query": "ECB Governing Council rate decision",
        "note": "First 2027 ECB rate-setting decision.",
    },
]


def get_upcoming_catalysts() -> List[Dict]:
    today_dt = datetime.now(tz=timezone.utc).date()
    upcoming = []
    for item in CATALYST_SCHEDULE:
        ev_date = datetime.strptime(item["date"], "%Y-%m-%d").date()
        delta = (ev_date - today_dt).days
        if delta >= -1:
            upcoming.append({
                **item,
                "days_away": delta,
                "killzone_note": classify_event_killzone(item.get("time", "")),
            })
    return upcoming[:8]


def _load_history(history_path: Path = HISTORY_FILE) -> List[Dict]:
    try:
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-500:]
    except Exception:
        pass
    return []


def _record_history_point(
    overall_score: int,
    direct_score: int,
    indirect_score: int,
    dax_price: Optional[float],
    history_path: Path = HISTORY_FILE,
) -> List[Dict]:
    history = _load_history(history_path)
    now_ts = int(time.time())
    bucket_ts = (now_ts // 300) * 300  # 5-minute resolution bucket
    point = {
        "ts": now_ts,
        "bucket": bucket_ts,
        "iso": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
        "overall_score": overall_score,
        "direct_score": direct_score,
        "indirect_score": indirect_score,
        "dax_price": dax_price,
    }
    if history and history[-1].get("bucket") == bucket_ts:
        history[-1] = point
    else:
        history.append(point)
    history = history[-500:]
    try:
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass
    return history


def _parse_pub_date(date_str: Optional[str]) -> Tuple[float, str]:
    if not date_str:
        now = time.time()
        return now, datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    date_str = date_str.strip()
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp(), dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp(), dt.astimezone(timezone.utc).isoformat()
    except Exception:
        now = time.time()
        return now, datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


def _clean_html_summary(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if len(text) > 340:
        text = text[:337].rsplit(" ", 1)[0] + "..."
    return text


def _split_google_source(title: str, default_source: str) -> Tuple[str, str]:
    if " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts[1]) <= 45 and len(parts[0]) > 15:
            return parts[0].strip(), parts[1].strip()
    return title.strip(), default_source


async def _fetch_rss(
    session: aiohttp.ClientSession,
    feed_cfg: Dict,
    limit: int = 16,
    instrument: str = "DAX",
) -> List[Dict]:
    url = feed_cfg["url"]
    articles: List[Dict] = []
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            raw_bytes = await resp.read()
    except Exception:
        return []

    try:
        root = ET.fromstring(raw_bytes)
    except Exception:
        return []

    items = (
        root.findall(".//item")
        or root.findall(".//{http://purl.org/rss/1.0/}item")
        or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    )

    for item in items[:limit]:
        def find_text(*tags):
            for t in tags:
                el = item.find(t)
                if el is not None and el.text:
                    return el.text.strip()
            return ""

        raw_title = find_text("title", "{http://purl.org/rss/1.0/}title", "{http://www.w3.org/2005/Atom}title")
        if not raw_title:
            continue

        link = find_text("link", "{http://purl.org/rss/1.0/}link")
        if not link:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
            if link_el is not None:
                link = link_el.attrib.get("href", "")

        pub_raw = find_text(
            "pubDate", "{http://purl.org/dc/elements/1.1/}date",
            "{http://www.w3.org/2005/Atom}updated", "{http://www.w3.org/2005/Atom}published",
        )
        ts, iso_dt = _parse_pub_date(pub_raw)
        desc_raw = find_text("description", "{http://purl.org/rss/1.0/}description", "{http://www.w3.org/2005/Atom}summary")
        summary = _clean_html_summary(desc_raw)

        source_el = item.find("source")
        explicit_source = source_el.text.strip() if (source_el is not None and source_el.text) else ""
        clean_title, parsed_source = _split_google_source(raw_title, feed_cfg["name"])
        source = explicit_source or parsed_source

        if summary and clean_title[:35].lower() in summary.lower() and len(summary) < len(clean_title) + 45:
            summary = ""

        if instrument == "DAX" and feed_cfg["id"] in ("cnbc_europe", "yahoo_gdaxi", "dw_business", "tagesschau_wirt", "handelsblatt_de", "finanzen_de"):
            if not is_relevant_to_dax(clean_title, summary):
                continue

        if instrument == "GOLD":
            analysis = analyze_gold_news(clean_title, summary, feed_cfg["category"])
        elif instrument == "BTC":
            analysis = analyze_btc_news(clean_title, summary, feed_cfg["category"])
        else:
            analysis = analyze_dax_news(clean_title, summary, feed_cfg["category"])
        article_id = hashlib.md5(f"{clean_title.lower()}|{link}".encode("utf-8")).hexdigest()[:12]

        articles.append({
            "id": article_id, "title": clean_title, "summary": summary,
            "url": link, "source": source, "feed_name": feed_cfg["name"],
            "published_ts": ts, "published_at": iso_dt, **analysis,
        })

    return articles


async def _fetch_yahoo_quote(
    session: aiohttp.ClientSession,
    item: Dict,
    include_series: bool = False,
    sem: Optional[asyncio.Semaphore] = None,
) -> Optional[Dict]:
    sym = item["symbol"]
    rng = "5d" if include_series else "2d"
    interval = "1h" if include_series else "1d"
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={interval}"

    async def _do_fetch():
        try:
            async with session.get(url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            return None

    if sem is not None:
        async with sem:
            data = await _do_fetch()
            await asyncio.sleep(0.06)
    else:
        data = await _do_fetch()

    if not data:
        return None

    try:
        res = data["chart"]["result"][0]
        meta = res["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None:
            return None
        change = (price - prev) if prev else 0.0
        change_pct = ((change / prev) * 100.0) if prev else 0.0

        out = {
            **item,
            "price": round(float(price), 4 if sym == "EURUSD=X" else 2),
            "prev_close": round(float(prev), 4 if sym == "EURUSD=X" else 2) if prev else None,
            "change": round(float(change), 4 if sym == "EURUSD=X" else 2),
            "change_pct": round(float(change_pct), 2),
            "market_state": meta.get("marketState", ""),
        }
        if include_series:
            timestamps = res.get("timestamp") or []
            closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
            out["series"] = [{"t": t, "v": round(float(c), 2)} for t, c in zip(timestamps, closes) if c is not None]
        return out
    except Exception:
        return None


async def _fetch_yahoo_ohlc(
    session: aiohttp.ClientSession,
    symbol: str,
    rng: str,
    interval: str,
    sem: Optional[asyncio.Semaphore] = None,
) -> List[Dict]:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={rng}&interval={interval}"

    async def _do():
        try:
            async with session.get(url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            return None

    if sem is not None:
        async with sem:
            data = await _do()
            await asyncio.sleep(0.06)
    else:
        data = await _do()

    if not data:
        return []
    try:
        res = data["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = (res.get("indicators", {}).get("quote") or [{}])[0]
        opens = q.get("open") or []
        highs = q.get("high") or []
        lows = q.get("low") or []
        closes = q.get("close") or []
        candles = []
        for t, o, h, l, c in zip(ts, opens, highs, lows, closes):
            if None not in (o, h, l, c):
                candles.append({
                    "t": int(t),
                    "o": round(float(o), 2),
                    "h": round(float(h), 2),
                    "l": round(float(l), 2),
                    "c": round(float(c), 2),
                })
        return candles
    except Exception:
        return []


def _deduplicate_articles(articles: List[Dict]) -> List[Dict]:
    seen_keys = set()
    unique: List[Dict] = []
    for art in sorted(articles, key=lambda x: x["published_ts"], reverse=True):
        norm = re.sub(r"[^a-z0-9äöüß]", "", art["title"].lower())[:48]
        if not norm or norm in seen_keys:
            continue
        seen_keys.add(norm)
        unique.append(art)
    return unique


def _compute_sector_heatmap(articles: List[Dict], constituents: List[Dict]) -> List[Dict]:
    sectors_order = [
        "Tech & Semis",
        "Industrials & Defense",
        "Financials",
        "Autos",
        "Chemicals & Energy",
        "Consumer & Healthcare",
    ]
    heatmap = []
    for sec in sectors_order:
        stocks = [c for c in constituents if c.get("sector") == sec]
        avg_chg = round(sum(s["change_pct"] for s in stocks) / len(stocks), 2) if stocks else 0.0
        sec_arts = [a for a in articles if sec in (a.get("sectors") or [])]
        avg_sent = int(round(sum(a["sentiment_score"] for a in sec_arts) / len(sec_arts))) if sec_arts else 0
        heatmap.append({
            "sector": sec,
            "avg_change_pct": avg_chg,
            "avg_sentiment": avg_sent,
            "news_count": len(sec_arts),
            "stocks": stocks,
        })
    return heatmap


def _compute_dashboard_analytics(
    articles: List[Dict],
    channels_cfg: Optional[Dict] = None,
    asset_name: str = "DAX 40",
) -> Dict:
    channels_cfg = channels_cfg or CHANNEL_RULES
    if not articles:
        return {
            "overall_score": 0, "overall_label": "Neutral", "total_articles": 0,
            "bullish_count": 0, "neutral_count": 0, "bearish_count": 0,
            "direct_score": 0, "direct_count": 0, "indirect_score": 0, "indirect_count": 0,
            "en_count": 0, "de_count": 0,
            "channels": [],
            "briefing": {"headline": "Awaiting live fundamental feed data.", "bullish_drivers": [], "bearish_drivers": []},
        }

    now = time.time()
    weighted_sum = 0.0
    weight_total = 0.0
    bullish_count = neutral_count = bearish_count = 0
    en_count = de_count = 0
    direct_scores: List[float] = []
    indirect_scores: List[float] = []
    channel_buckets: Dict[str, List[Dict]] = {k: [] for k in channels_cfg.keys()}

    for art in articles:
        sc = art["sentiment_score"]
        if sc >= 12:
            bullish_count += 1
        elif sc <= -12:
            bearish_count += 1
        else:
            neutral_count += 1

        if art.get("lang") == "DE":
            de_count += 1
        else:
            en_count += 1

        (direct_scores if art["impact_type"] == "direct" else indirect_scores).append(sc)
        if art["channel_key"] in channel_buckets:
            channel_buckets[art["channel_key"]].append(art)

        age_hours = max(0.0, (now - art["published_ts"]) / 3600.0)
        recency_w = 1.0 / (1.0 + age_hours / 36.0)
        impact_w = {"High": 1.6, "Medium": 1.15, "Low": 0.75}.get(art["impact_level"], 1.0)
        direct_w = 1.25 if art["impact_type"] == "direct" else 1.0
        w = recency_w * impact_w * direct_w
        weighted_sum += sc * w
        weight_total += w

    overall_score = int(round(weighted_sum / weight_total)) if weight_total > 0 else 0
    if overall_score >= 25:
        overall_label = "Bullish"
    elif overall_score >= 8:
        overall_label = "Slightly Bullish"
    elif overall_score <= -25:
        overall_label = "Bearish"
    elif overall_score <= -8:
        overall_label = "Slightly Bearish"
    else:
        overall_label = "Neutral"

    direct_score = int(round(sum(direct_scores) / len(direct_scores))) if direct_scores else 0
    indirect_score = int(round(sum(indirect_scores) / len(indirect_scores))) if indirect_scores else 0

    channels_summary = []
    for k, cfg in channels_cfg.items():
        items = channel_buckets[k]
        avg = int(round(sum(x["sentiment_score"] for x in items) / len(items))) if items else 0
        channels_summary.append({
            "key": k, "label": cfg["label"], "impact_type": cfg["impact_type"],
            "count": len(items), "avg_score": avg,
        })

    top_bullish = sorted(
        [a for a in articles if a["sentiment_score"] >= 12],
        key=lambda x: x["sentiment_score"] * (1.3 if x["impact_type"] == "direct" else 1.0),
        reverse=True,
    )[:3]
    top_bearish = sorted(
        [a for a in articles if a["sentiment_score"] <= -12],
        key=lambda x: abs(x["sentiment_score"]) * (1.3 if x["impact_type"] == "direct" else 1.0),
        reverse=True,
    )[:3]

    if overall_score >= 12:
        stance_line = (
            f"{asset_name} fundamental sentiment is {overall_label.lower()} ({overall_score:+d}), "
            f"supported by {bullish_count} positive vs. {bearish_count} negative catalysts across EN & DE feeds."
        )
    elif overall_score <= -12:
        stance_line = (
            f"{asset_name} fundamental sentiment leans {overall_label.lower()} ({overall_score:+d}), "
            f"with {bearish_count} headwinds outweighing {bullish_count} positive catalysts across tracked EN & DE feeds."
        )
    else:
        stance_line = (
            f"{asset_name} fundamental sentiment is balanced/mixed ({overall_score:+d}), "
            f"with {bullish_count} bullish and {bearish_count} bearish signals competing across macro drivers."
        )

    return {
        "overall_score": overall_score, "overall_label": overall_label,
        "total_articles": len(articles), "bullish_count": bullish_count,
        "neutral_count": neutral_count, "bearish_count": bearish_count,
        "direct_score": direct_score, "direct_count": len(direct_scores),
        "indirect_score": indirect_score, "indirect_count": len(indirect_scores),
        "en_count": en_count, "de_count": de_count,
        "channels": channels_summary,
        "briefing": {
            "headline": stance_line,
            "bullish_drivers": [{"title": a["title"], "source": a["source"], "score": a["sentiment_score"], "lang": a.get("lang", "EN")} for a in top_bullish],
            "bearish_drivers": [{"title": a["title"], "source": a["source"], "score": a["sentiment_score"], "lang": a.get("lang", "EN")} for a in top_bearish],
        },
    }


async def fetch_full_dashboard() -> Dict:
    connector = aiohttp.TCPConnector(limit=28)
    yahoo_sem = asyncio.Semaphore(3)
    async with aiohttp.ClientSession(connector=connector) as session:
        feed_tasks = [_fetch_rss(session, f, limit=15, instrument="DAX") for f in NEWS_FEEDS]
        gold_feed_tasks = [_fetch_rss(session, f, limit=18, instrument="GOLD") for f in GOLD_NEWS_FEEDS]
        btc_feed_tasks = [_fetch_rss(session, f, limit=15, instrument="BTC") for f in BTC_NEWS_FEEDS]
        macro_tasks = [
            _fetch_yahoo_quote(session, sym, include_series=(sym["symbol"] in ("^GDAXI", "GC=F", "BTC-USD")), sem=yahoo_sem)
            for sym in MARKET_SYMBOLS
        ]
        stock_tasks = [
            _fetch_yahoo_quote(session, st, include_series=False, sem=yahoo_sem)
            for st in DAX_CONSTITUENTS
        ]
        ohlc_tasks = [
            _fetch_yahoo_ohlc(session, "^GDAXI", "5d", "15m", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "^GDAXI", "1mo", "1h", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "^GDAXI", "6mo", "1d", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "^STOXX50E", "5d", "15m", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "^GSPC", "5d", "15m", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "GC=F", "5d", "15m", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "GC=F", "1mo", "1h", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "GC=F", "6mo", "1d", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "SI=F", "5d", "15m", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "BTC-USD", "5d", "15m", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "BTC-USD", "1mo", "1h", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "BTC-USD", "6mo", "1d", sem=yahoo_sem),
            _fetch_yahoo_ohlc(session, "ETH-USD", "5d", "15m", sem=yahoo_sem),
        ]

        feed_results, gold_feed_results, btc_feed_results, macro_results, stock_results, ohlc_results = await asyncio.gather(
            asyncio.gather(*feed_tasks),
            asyncio.gather(*gold_feed_tasks),
            asyncio.gather(*btc_feed_tasks),
            asyncio.gather(*macro_tasks),
            asyncio.gather(*stock_tasks),
            asyncio.gather(*ohlc_tasks),
        )

    raw_articles = [item for sublist in feed_results for item in sublist]
    articles = _deduplicate_articles(raw_articles)[:160]
    analytics = _compute_dashboard_analytics(articles, channels_cfg=CHANNEL_RULES, asset_name="DAX 40")

    raw_gold_articles = [item for sublist in gold_feed_results for item in sublist]
    gold_articles = _deduplicate_articles(raw_gold_articles)[:80]
    gold_analytics = _compute_dashboard_analytics(gold_articles, channels_cfg=GOLD_CHANNEL_RULES, asset_name="Gold (XAU)")

    raw_btc_articles = [item for sublist in btc_feed_results for item in sublist]
    btc_articles = _deduplicate_articles(raw_btc_articles)[:80]
    btc_analytics = _compute_dashboard_analytics(btc_articles, channels_cfg=BTC_CHANNEL_RULES, asset_name="Bitcoin (BTC-USD)")

    macro_quotes = [m for m in macro_results if m is not None]
    stock_quotes = [s for s in stock_results if s is not None]
    dax_q = next((m for m in macro_quotes if m["symbol"] == "^GDAXI"), None)
    dax_price = dax_q["price"] if dax_q else None
    gold_q = next((m for m in macro_quotes if m["symbol"] == "GC=F"), None)
    gold_price = gold_q["price"] if gold_q else None
    btc_q = next((m for m in macro_quotes if m["symbol"] == "BTC-USD"), None)
    btc_price = btc_q["price"] if btc_q else None

    history = _record_history_point(
        analytics["overall_score"], analytics["direct_score"], analytics["indirect_score"], dax_price, HISTORY_FILE
    )
    gold_history = _record_history_point(
        gold_analytics["overall_score"], gold_analytics["direct_score"], gold_analytics["indirect_score"], gold_price, GOLD_HISTORY_FILE
    )
    btc_history = _record_history_point(
        btc_analytics["overall_score"], btc_analytics["direct_score"], btc_analytics["indirect_score"], btc_price, BTC_HISTORY_FILE
    )
    sector_heatmap = _compute_sector_heatmap(articles, stock_quotes)
    catalysts = get_upcoming_catalysts()

    dax_15m, dax_1h, dax_1d, stoxx_15m, spx_15m, gold_15m, gold_1h, gold_1d, silver_15m, btc_15m, btc_1h, btc_1d, eth_15m = ohlc_results
    smc_data = analyze_smc_suite(
        dax_15m, dax_1d, stoxx_15m, spx_15m,
        analytics["overall_score"], analytics["overall_label"],
        macro_quotes=macro_quotes, candles_1h=dax_1h,
        dax_constituents=stock_quotes, catalysts=catalysts,
        instrument="DAX",
    )
    gold_smc = analyze_smc_suite(
        gold_15m, gold_1d, silver_15m, spx_15m,
        gold_analytics["overall_score"], gold_analytics["overall_label"],
        macro_quotes=macro_quotes, candles_1h=gold_1h,
        dax_constituents=None, catalysts=catalysts,
        ledger_path=Path(__file__).resolve().parent / "gold_signal_history.json",
        instrument="GOLD",
    )
    btc_smc = analyze_smc_suite(
        btc_15m, btc_1d, eth_15m, spx_15m,
        btc_analytics["overall_score"], btc_analytics["overall_label"],
        macro_quotes=macro_quotes, candles_1h=btc_1h,
        dax_constituents=None, catalysts=catalysts,
        ledger_path=Path(__file__).resolve().parent / "btc_signal_history.json",
        instrument="BTC",
    )

    return {
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "updated_ts": time.time(),
        "analytics": analytics,
        "macro_quotes": macro_quotes,
        "dax_constituents": stock_quotes,
        "sector_heatmap": sector_heatmap,
        "catalysts": catalysts,
        "history": history,
        "smc": smc_data,
        "articles": articles,
        "gold": {
            "analytics": gold_analytics,
            "smc": gold_smc,
            "articles": gold_articles,
            "history": gold_history,
        },
        "btc": {
            "analytics": btc_analytics,
            "smc": btc_smc,
            "articles": btc_articles,
            "history": btc_history,
        },
    }


async def search_internet_for_dax(query: str, instrument: str = "DAX") -> Dict:
    clean_q = query.strip()
    if instrument == "BTC":
        encoded_en = urllib.parse.quote(f"{clean_q} (Bitcoin OR BTC OR crypto ETF OR Fed OR SEC OR liquidity)")
        encoded_de = urllib.parse.quote(f"{clean_q} (Bitcoin OR BTC OR Krypto OR ETF OR Zinsen)")
        search_feeds = [
            {"id": "live_btc_en", "name": f"Bitcoin Web Search EN: {clean_q}", "category": "btc_etf_institutional",
             "url": f"https://news.google.com/rss/search?q={encoded_en}&hl=en-US&gl=US&ceid=US:en"},
            {"id": "live_btc_de", "name": f"Bitcoin Web Search DE: {clean_q}", "category": "btc_fed_liquidity",
             "url": f"https://news.google.com/rss/search?q={encoded_de}&hl=de&gl=DE&ceid=DE:de"},
        ]
        async with aiohttp.ClientSession() as session:
            res = await asyncio.gather(*[_fetch_rss(session, f, limit=16, instrument="BTC") for f in search_feeds])
        articles = _deduplicate_articles([item for sub in res for item in sub])[:50]
        return {
            "query": clean_q,
            "instrument": "BTC",
            "searched_at": datetime.now(tz=timezone.utc).isoformat(),
            "analytics": _compute_dashboard_analytics(articles, channels_cfg=BTC_CHANNEL_RULES, asset_name="Bitcoin (BTC-USD)"),
            "articles": articles,
        }

    if instrument == "GOLD":
        encoded_en = urllib.parse.quote(f"{clean_q} (gold price OR XAUUSD OR bullion OR Fed OR yields OR DXY)")
        encoded_de = urllib.parse.quote(f"{clean_q} (Goldpreis OR Gold OR Edelmetall OR Fed OR Zinsen)")
        search_feeds = [
            {"id": "live_gold_en", "name": f"Gold Web Search EN: {clean_q}", "category": "gold_fed_yields",
             "url": f"https://news.google.com/rss/search?q={encoded_en}&hl=en-US&gl=US&ceid=US:en"},
            {"id": "live_gold_de", "name": f"Gold Web Search DE: {clean_q}", "category": "gold_inflation_macro",
             "url": f"https://news.google.com/rss/search?q={encoded_de}&hl=de&gl=DE&ceid=DE:de"},
        ]
        async with aiohttp.ClientSession() as session:
            res = await asyncio.gather(*[_fetch_rss(session, f, limit=16, instrument="GOLD") for f in search_feeds])
        articles = _deduplicate_articles([item for sub in res for item in sub])[:50]
        return {
            "query": clean_q,
            "instrument": "GOLD",
            "searched_at": datetime.now(tz=timezone.utc).isoformat(),
            "analytics": _compute_dashboard_analytics(articles, channels_cfg=GOLD_CHANNEL_RULES, asset_name="Gold (XAU)"),
            "articles": articles,
        }

    encoded_en = urllib.parse.quote(f"{clean_q} (DAX OR Germany OR ECB OR Eurozone OR markets OR economy)")
    encoded_de = urllib.parse.quote(f"{clean_q} (DAX OR Deutschland OR EZB OR Wirtschaft OR Börse)")
    encoded_exact = urllib.parse.quote(f"{clean_q} finance OR economy OR stocks")

    search_feeds = [
        {"id": "live_search_en", "name": f"Web Search EN: {clean_q}", "category": "dax_bluechips",
         "url": f"https://news.google.com/rss/search?q={encoded_en}&hl=en-US&gl=US&ceid=US:en"},
        {"id": "live_search_de", "name": f"Web Search DE: {clean_q}", "category": "dax_bluechips",
         "url": f"https://news.google.com/rss/search?q={encoded_de}&hl=de&gl=DE&ceid=DE:de"},
        {"id": "live_search_broad", "name": f"Web Search: {clean_q}", "category": "global_us",
         "url": f"https://news.google.com/rss/search?q={encoded_exact}&hl=en-US&gl=US&ceid=US:en"},
    ]

    async with aiohttp.ClientSession() as session:
        res = await asyncio.gather(*[_fetch_rss(session, f, limit=16, instrument="DAX") for f in search_feeds])

    raw = _deduplicate_articles([item for sub in res for item in sub])
    relevant = [a for a in raw if is_relevant_to_dax(a["title"], a.get("summary", ""))]
    articles = (relevant if len(relevant) >= 3 else raw)[:50]
    return {
        "query": clean_q,
        "instrument": "DAX",
        "searched_at": datetime.now(tz=timezone.utc).isoformat(),
        "analytics": _compute_dashboard_analytics(articles, channels_cfg=CHANNEL_RULES, asset_name="DAX 40"),
        "articles": articles,
    }


async def fetch_article_deep_read(url: str, fallback_title: str = "", fallback_summary: str = "") -> Dict:
    paragraphs: List[str] = []
    final_url = url
    fetched_ok = False

    if url and url.startswith("http"):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    final_url = str(resp.url)
                    if resp.status == 200:
                        html = await resp.text(errors="ignore")
                        soup = BeautifulSoup(html, "html.parser")
                        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                            tag.decompose()
                        for p in soup.find_all("p"):
                            txt = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
                            if len(txt) > 55 and not any(
                                skip in txt.lower()
                                for skip in ["cookie", "subscribe", "sign in", "javascript", "all rights reserved"]
                            ):
                                paragraphs.append(txt)
                        if paragraphs:
                            fetched_ok = True
        except Exception:
            pass

    excerpt_text = " ".join(paragraphs[:8]) if paragraphs else fallback_summary
    deep_analysis = analyze_dax_news(fallback_title, excerpt_text)

    return {
        "url": final_url,
        "fetched_ok": fetched_ok,
        "paragraphs": paragraphs[:8],
        "deep_analysis": deep_analysis,
    }


async def run_ai_fundamental_thesis(
    title: str,
    text: str,
    api_url: str,
    api_key: str,
    model: str,
) -> Dict:
    """
    Optional user-configured OpenAI-compatible or local Ollama endpoint for deep DAX fundamental thesis.
    """
    endpoint = api_url.strip().rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        if endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/chat/completions"
        else:
            endpoint = f"{endpoint}/v1/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    prompt = (
        "You are an institutional German equities & DAX 40 macro analyst. "
        "Given the headline and text below (in English or German), provide a concise 4-bullet fundamental brief in English:\n"
        "1. Sentiment & Conviction (Bullish / Bearish / Neutral)\n"
        "2. Direct vs Indirect Transmission to DAX 40\n"
        "3. Affected DAX Sectors / Constituents\n"
        "4. Key Upside / Downside Risk to Watch\n\n"
        f"Headline: {title}\n\nText: {text[:2400]}"
    )

    payload = {
        "model": model.strip() or "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 350,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                data = await resp.json()
                if resp.status != 200:
                    return {"ok": False, "error": data.get("error", {}).get("message", f"HTTP {resp.status}")}
                content = data["choices"][0]["message"]["content"]
                return {"ok": True, "thesis": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def fetch_fast_spot_quotes() -> Dict[str, Optional[float]]:
    async with aiohttp.ClientSession() as session:
        dax_q, gold_q, btc_q = await asyncio.gather(
            _fetch_yahoo_quote(session, {"symbol": "^GDAXI", "name": "DAX 40"}, include_series=False),
            _fetch_yahoo_quote(session, {"symbol": "GC=F", "name": "Gold"}, include_series=False),
            _fetch_yahoo_quote(session, {"symbol": "BTC-USD", "name": "Bitcoin"}, include_series=False),
        )
    return {
        "DAX": dax_q["price"] if dax_q else None,
        "GOLD": gold_q["price"] if gold_q else None,
        "BTC": btc_q["price"] if btc_q else None,
    }

