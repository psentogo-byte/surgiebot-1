import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# --- Pure-Stdlib Frankfurt CET/CEST Timezone Helper (Works on All OSes) ---

def _last_sunday(year: int, month: int) -> datetime:
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    d = nxt - timedelta(days=1)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def to_frankfurt_dt(utc_ts: Optional[float] = None) -> Tuple[datetime, str]:
    dt_utc = datetime.fromtimestamp(utc_ts, tz=timezone.utc) if utc_ts is not None else datetime.now(tz=timezone.utc)
    dst_start = _last_sunday(dt_utc.year, 3).replace(hour=1, minute=0, second=0)
    dst_end = _last_sunday(dt_utc.year, 10).replace(hour=1, minute=0, second=0)
    if dst_start <= dt_utc < dst_end:
        return dt_utc + timedelta(hours=2), "CEST"
    return dt_utc + timedelta(hours=1), "CET"


def get_killzone_status(utc_ts: Optional[float] = None, instrument: str = "DAX") -> Dict:
    dt_de, tz_abbr = to_frankfurt_dt(utc_ts)
    hm = dt_de.hour * 60 + dt_de.minute
    weekday = dt_de.weekday()

    if instrument == "BTC":
        if 1 * 60 <= hm < 7 * 60:
            phase = "Asia Crypto Accumulation / Range"
            tag = "BTC ASIA KZ"
            guidance = "24/7 Crypto Asia session. Watch for stop-hunts of PDH/PDL or Asia Range highs/lows before London handoff."
        elif 8 * 60 <= hm < 12 * 60:
            phase = "London Institutional Crypto Killzone"
            tag = "BTC LONDON KZ"
            guidance = "European institutional desk open. High probability for Judas sweep and 15m FVG/OB displacement."
        elif 13 * 60 + 30 <= hm < 22 * 60:
            phase = "NY Spot ETF / US Equities Overlap KZ"
            tag = "BTC NY ETF KZ"
            guidance = "Peak Bitcoin Spot ETF & CME/Perp liquidity window. Watch SMT vs ETH-USD & DXY/S&P 500 correlation."
        else:
            phase = "24/7 Global Crypto Overnight Flow"
            tag = "BTC 24/7 ACTIVE"
            guidance = "Continuous global BTC liquidity. Execute strictly on confirmed 1H+15m sweeps and FVG/OTE confluences."
        return {
            "frankfurt_time": dt_de.strftime("%H:%M"),
            "frankfurt_date": dt_de.strftime("%Y-%m-%d"),
            "tz": tz_abbr,
            "phase": phase,
            "tag": tag,
            "is_killzone": True,
            "is_deadzone": False,
            "guidance": guidance,
        }

    if weekday >= 5:
        phase = "Weekend Market Closed"
        tag = "CLOSED"
        guidance = "Cash Xetra closed. Review IPDA 20/40/60D Dealing Ranges, Weekly Open, and next week's Catalyst Calendar."
        active = False
    elif hm < 8 * 60:
        phase = "Asian / Overnight Accumulation"
        tag = "ASIAN"
        guidance = "AMD Accumulation phase. Wait for Frankfurt/London Open to engineer a Judas sweep before entering."
        active = False
    elif 8 * 60 <= hm < 9 * 60:
        phase = "Frankfurt Pre-Xetra / Judas Swing"
        tag = "FRANKFURT PRE"
        guidance = "High-manipulation window. Watch for fake directional sweep above/below Weekly or Midnight Open before 09:00 Xetra."
        active = True
    elif 9 * 60 <= hm < 11 * 60 + 30:
        phase = "London / Xetra Open Killzone"
        tag = "LONDON KZ"
        guidance = "Primary AM expansion window (Ifo 10:00 / ZEW 11:00). Look for OTE / FVG / Breaker entry after Opening sweep."
        active = True
    elif 11 * 60 + 30 <= hm < 13 * 60 + 45:
        phase = "EU Midday Deadzone / OTE Pullback"
        tag = "LUNCH DEADZONE"
        guidance = "Lower institutional volume (11:30-13:45 CET); wait for 13:45 NY/Xetra overlap sweep into AM OTE/FVGs."
        active = False
    elif 13 * 60 + 45 <= hm < 17 * 60 + 30:
        phase = "NY Open / Xetra Close Overlap Killzone"
        tag = "NY OVERLAP KZ"
        guidance = "Peak cross-asset liquidity (ECB 14:15, US NFP/CPI 14:30, NY open 15:30). Watch SMT vs S&P 500 & SD targets."
        active = True
    else:
        phase = "Post-Xetra / Futures Drift"
        tag = "AFTER HOURS"
        guidance = "Xetra cash closed. Mark today's PDH/PDL, IFVGs, and 20D/60D IPDA levels for tomorrow's London Open."
        active = False

    return {
        "frankfurt_time": dt_de.strftime("%H:%M"),
        "frankfurt_date": dt_de.strftime("%Y-%m-%d"),
        "tz": tz_abbr,
        "phase": phase,
        "tag": tag,
        "is_killzone": active,
        "is_deadzone": not active,
        "guidance": guidance,
    }


def classify_event_killzone(time_str: str) -> str:
    m = None
    for part in (time_str or "").split(":"):
        if part.strip().isdigit():
            m = int(part.strip())
            break
    if m is None:
        return "Session Event"
    if 9 <= m < 12:
        return "London / Xetra Open KZ — Expect Judas sweep of ORH/ORL or PDH/PDL before displacement"
    if 13 <= m < 18:
        return "NY Overlap KZ — High-volatility news injection; watch SMT, IFVG & SD terminus targets"
    return "Off-Killzone Release"


# --- Swings, FVGs, Inverse FVGs, Order Blocks, Breaker Blocks ---

def _find_swings(candles: List[Dict], left: int = 3, right: int = 3) -> Tuple[List[Dict], List[Dict]]:
    swing_highs: List[Dict] = []
    swing_lows: List[Dict] = []
    n = len(candles)
    for i in range(left, n - right):
        hi = candles[i]["h"]
        lo = candles[i]["l"]
        if all(hi >= candles[j]["h"] for j in range(i - left, i + right + 1) if j != i):
            if not swing_highs or abs(i - swing_highs[-1]["idx"]) >= 3:
                swing_highs.append({"idx": i, "t": candles[i]["t"], "price": hi})
        if all(lo <= candles[j]["l"] for j in range(i - left, i + right + 1) if j != i):
            if not swing_lows or abs(i - swing_lows[-1]["idx"]) >= 3:
                swing_lows.append({"idx": i, "t": candles[i]["t"], "price": lo})
    return swing_highs, swing_lows


def _detect_fvgs_and_ifvgs(candles: List[Dict], min_rel: float = 0.0004) -> Tuple[List[Dict], List[Dict]]:
    active_fvgs: List[Dict] = []
    ifvgs: List[Dict] = []
    n = len(candles)

    for i in range(2, n):
        c0 = candles[i - 2]
        c1 = candles[i - 1]
        c2 = candles[i]

        # Original Bullish FVG
        if c2["l"] > c0["h"] and (c2["l"] - c0["h"]) >= max(2.0, c1["c"] * min_rel):
            bottom = round(c0["h"], 2)
            top = round(c2["l"], 2)
            ce = round((top + bottom) / 2.0, 2)
            # Check if invalidated by a close below bottom (becomes Bearish IFVG!)
            inv_idx = next((k for k in range(i + 1, n) if candles[k]["c"] < bottom), None)
            if inv_idx is None:
                touched = any(candles[k]["l"] < top for k in range(i + 1, n))
                active_fvgs.append({
                    "type": "bullish", "idx": i - 1, "t": c1["t"],
                    "top": top, "bottom": bottom, "ce": ce, "partially_filled": touched,
                })
            else:
                # Bearish IFVG remains valid as long as no subsequent close reclaims above top
                re_broken = any(candles[k]["c"] > top for k in range(inv_idx + 1, n))
                if not re_broken and inv_idx >= n - 40:
                    ifvgs.append({
                        "type": "bearish_ifvg", "idx": inv_idx, "t": candles[inv_idx]["t"],
                        "top": top, "bottom": bottom, "ce": ce,
                        "note": "Broken Bullish FVG flipped Bearish IFVG",
                    })

        # Original Bearish FVG
        elif c2["h"] < c0["l"] and (c0["l"] - c2["h"]) >= max(2.0, c1["c"] * min_rel):
            top = round(c0["l"], 2)
            bottom = round(c2["h"], 2)
            ce = round((top + bottom) / 2.0, 2)
            inv_idx = next((k for k in range(i + 1, n) if candles[k]["c"] > top), None)
            if inv_idx is None:
                touched = any(candles[k]["h"] > bottom for k in range(i + 1, n))
                active_fvgs.append({
                    "type": "bearish", "idx": i - 1, "t": c1["t"],
                    "top": top, "bottom": bottom, "ce": ce, "partially_filled": touched,
                })
            else:
                re_broken = any(candles[k]["c"] < bottom for k in range(inv_idx + 1, n))
                if not re_broken and inv_idx >= n - 40:
                    ifvgs.append({
                        "type": "bullish_ifvg", "idx": inv_idx, "t": candles[inv_idx]["t"],
                        "top": top, "bottom": bottom, "ce": ce,
                        "note": "Broken Bearish FVG flipped Bullish IFVG",
                    })

    return active_fvgs[-8:], ifvgs[-4:]


def _detect_structure_obs_and_breakers(
    candles: List[Dict],
    swing_highs: List[Dict],
    swing_lows: List[Dict],
    active_fvgs: List[Dict],
) -> Tuple[str, List[Dict], List[Dict], List[Dict]]:
    events: List[Dict] = []
    obs: List[Dict] = []
    breakers: List[Dict] = []
    trend = "Neutral"

    if not swing_highs or not swing_lows:
        return trend, events, obs, breakers

    n = len(candles)
    sh_ptr = sl_ptr = 0
    active_sh = active_sl = None
    broken_sh = set()
    broken_sl = set()

    for i, c in enumerate(candles):
        while sh_ptr < len(swing_highs) and swing_highs[sh_ptr]["idx"] <= i - 3:
            active_sh = swing_highs[sh_ptr]
            sh_ptr += 1
        while sl_ptr < len(swing_lows) and swing_lows[sl_ptr]["idx"] <= i - 3:
            active_sl = swing_lows[sl_ptr]
            sl_ptr += 1

        if active_sh and active_sh["idx"] not in broken_sh and c["c"] > active_sh["price"]:
            broken_sh.add(active_sh["idx"])
            ev_type = "CHoCH" if trend == "Bearish" else "BOS"
            trend = "Bullish"
            events.append({"idx": i, "t": c["t"], "type": ev_type, "dir": "bullish", "price": round(active_sh["price"], 2)})
            for j in range(i - 1, max(-1, i - 12), -1):
                if candles[j]["c"] < candles[j]["o"]:
                    ob_top, ob_bot = round(candles[j]["h"], 2), round(candles[j]["l"], 2)
                    break_idx = next((k for k in range(i + 1, n) if candles[k]["c"] < ob_bot), None)
                    if break_idx is None:
                        obs.append({"type": "bullish", "idx": j, "t": candles[j]["t"], "top": ob_top, "bottom": ob_bot})
                    else:
                        # Failed Bullish OB -> Bearish Breaker Block
                        reclaimed = any(candles[k]["c"] > ob_top for k in range(break_idx + 1, n))
                        if not reclaimed and break_idx >= n - 45:
                            unicorn = any(f["type"] == "bearish" and not (f["bottom"] > ob_top or f["top"] < ob_bot) for f in active_fvgs)
                            breakers.append({"type": "bearish_breaker", "idx": break_idx, "t": candles[break_idx]["t"], "top": ob_top, "bottom": ob_bot, "unicorn": unicorn})
                    break

        if active_sl and active_sl["idx"] not in broken_sl and c["c"] < active_sl["price"]:
            broken_sl.add(active_sl["idx"])
            ev_type = "CHoCH" if trend == "Bullish" else "BOS"
            trend = "Bearish"
            events.append({"idx": i, "t": c["t"], "type": ev_type, "dir": "bearish", "price": round(active_sl["price"], 2)})
            for j in range(i - 1, max(-1, i - 12), -1):
                if candles[j]["c"] > candles[j]["o"]:
                    ob_top, ob_bot = round(candles[j]["h"], 2), round(candles[j]["l"], 2)
                    break_idx = next((k for k in range(i + 1, n) if candles[k]["c"] > ob_top), None)
                    if break_idx is None:
                        obs.append({"type": "bearish", "idx": j, "t": candles[j]["t"], "top": ob_top, "bottom": ob_bot})
                    else:
                        # Failed Bearish OB -> Bullish Breaker Block
                        reclaimed = any(candles[k]["c"] < ob_bot for k in range(break_idx + 1, n))
                        if not reclaimed and break_idx >= n - 45:
                            unicorn = any(f["type"] == "bullish" and not (f["bottom"] > ob_top or f["top"] < ob_bot) for f in active_fvgs)
                            breakers.append({"type": "bullish_breaker", "idx": break_idx, "t": candles[break_idx]["t"], "top": ob_top, "bottom": ob_bot, "unicorn": unicorn})
                    break

    return trend, events[-8:], obs[-4:], breakers[-4:]


# --- IPDA 20/40/60-Day Lookbacks & Daily FVGs ---

def compute_ipda_lookbacks(candles_daily: List[Dict], current_price: float) -> Dict:
    if len(candles_daily) < 5:
        return {}

    def _rng(bars: List[Dict]) -> Dict:
        hi = round(max(b["h"] for b in bars), 2)
        lo = round(min(b["l"] for b in bars), 2)
        span = hi - lo
        pct = round(((current_price - lo) / span) * 100.0, 1) if span > 0 else 50.0
        zone = "Premium" if pct >= 62 else ("Discount" if pct <= 38 else "Equilibrium")
        return {"high": hi, "low": lo, "eq": round((hi + lo) / 2.0, 2), "pct": pct, "zone": zone}

    d20 = _rng(candles_daily[-20:])
    d40 = _rng(candles_daily[-40:]) if len(candles_daily) >= 25 else d20
    d60 = _rng(candles_daily[-60:]) if len(candles_daily) >= 45 else d40

    daily_fvgs, _ = _detect_fvgs_and_ifvgs(candles_daily[-45:], min_rel=0.001)

    return {
        "d20": d20,
        "d40": d40,
        "d60": d60,
        "daily_fvgs": daily_fvgs[-4:],
    }


# --- Power of 3 (AMD) & True Opens ---

def compute_power_of_three(
    candles_15m: List[Dict],
    candles_daily: List[Dict],
    overall_score: int,
    instrument: str = "DAX",
) -> Dict:
    if not candles_15m:
        return {}

    cur = round(candles_15m[-1]["c"], 2)
    last_day = to_frankfurt_dt(candles_15m[-1]["t"])[0].date()
    today_bars = [c for c in candles_15m if to_frankfurt_dt(c["t"])[0].date() == last_day]
    open_label = "COMEX/LDN Open" if instrument == "GOLD" else ("UTC Daily Open" if instrument == "BTC" else "Xetra Open")
    if instrument == "GOLD" and today_bars:
        ny_bars = [c for c in today_bars if to_frankfurt_dt(c["t"])[0].hour >= 14]
        ldn_bars = [c for c in today_bars if to_frankfurt_dt(c["t"])[0].hour >= 8]
        ref_bars = ny_bars or ldn_bars or today_bars
        cash_open = round(ref_bars[0]["o"], 2)
    elif instrument == "BTC" and today_bars:
        utc_midnight = [c for c in today_bars if to_frankfurt_dt(c["t"])[0].hour >= 1]
        cash_open = round((utc_midnight or today_bars)[0]["o"], 2)
    else:
        cash_open = round(today_bars[0]["o"], 2) if today_bars else round(candles_15m[-1]["o"], 2)
    day_high = round(max(c["h"] for c in today_bars), 2) if today_bars else cur
    day_low = round(min(c["l"] for c in today_bars), 2) if today_bars else cur

    # Monday Weekly Open & Monthly Open from daily candles
    now_dt, _ = to_frankfurt_dt()
    cur_week = now_dt.isocalendar()[:2]
    cur_month = (now_dt.year, now_dt.month)

    wk_bars = [c for c in candles_daily if to_frankfurt_dt(c["t"])[0].isocalendar()[:2] == cur_week]
    weekly_open = round(wk_bars[0]["o"], 2) if wk_bars else (round(candles_daily[-1]["o"], 2) if candles_daily else cash_open)

    mo_bars = [c for c in candles_daily if (to_frankfurt_dt(c["t"])[0].year, to_frankfurt_dt(c["t"])[0].month) == cur_month]
    monthly_open = round(mo_bars[0]["o"], 2) if mo_bars else weekly_open

    above_cash = cur >= cash_open
    above_week = cur >= weekly_open
    sweep_buf = max(cur * 0.0005, 1.5)
    swept_above_open = day_high > cash_open + sweep_buf
    swept_below_open = day_low < cash_open - sweep_buf

    if overall_score <= -10:
        if not above_cash and swept_above_open:
            amd_phase = "DISTRIBUTION SHORT"
            amd_tone = "bear"
            amd_note = f"Price manipulated above {open_label} ({cash_open}) to {day_high}, then displaced below open — textbook bearish AMD."
        elif above_cash:
            amd_phase = "MANIPULATION (JUDAS ABOVE OPEN)"
            amd_tone = "neut"
            amd_note = f"Price is trading above {open_label} ({cash_open}) against Bearish fundamentals — watch for bearish CHoCH/IFVG short back under open."
        else:
            amd_phase = "EXPANSION BELOW OPEN"
            amd_tone = "bear"
            amd_note = f"Price expanding below {open_label} ({cash_open}) and {'below' if not above_week else 'near'} Weekly Open ({weekly_open})."
    elif overall_score >= 10:
        if above_cash and swept_below_open:
            amd_phase = "DISTRIBUTION LONG"
            amd_tone = "bull"
            amd_note = f"Price manipulated below {open_label} ({cash_open}) to {day_low}, then reclaimed above open — textbook bullish AMD."
        elif not above_cash:
            amd_phase = "MANIPULATION (JUDAS BELOW OPEN)"
            amd_tone = "neut"
            amd_note = f"Price is trading below {open_label} ({cash_open}) against Bullish fundamentals — watch for bullish CHoCH/IFVG long back above open."
        else:
            amd_phase = "EXPANSION ABOVE OPEN"
            amd_tone = "bull"
            amd_note = f"Price expanding above {open_label} ({cash_open}) and {'above' if above_week else 'near'} Weekly Open ({weekly_open})."
    else:
        amd_phase = "ACCUMULATION / TWO-WAY"
        amd_tone = "neut"
        amd_note = f"Mixed macro bias around {open_label} ({cash_open}) and Weekly Open ({weekly_open}); wait for clean sweep + IFVG."

    return {
        "cash_open": cash_open,
        "weekly_open": weekly_open,
        "monthly_open": monthly_open,
        "open_label": open_label,
        "above_cash_open": above_cash,
        "above_weekly_open": above_week,
        "amd_phase": amd_phase,
        "amd_tone": amd_tone,
        "amd_note": amd_note,
    }


# --- OTE (61.8% - 78.6% / 70.5%) & Standard Deviation Projections ---

def compute_ote_and_sd(
    candles_15m: List[Dict],
    swing_highs: List[Dict],
    swing_lows: List[Dict],
    trend: str,
    fvgs: List[Dict],
) -> Tuple[Dict, Dict]:
    if not candles_15m or not swing_highs or not swing_lows:
        return {}, {}

    cur = round(candles_15m[-1]["c"], 2)
    sh = swing_highs[-1]
    sl = swing_lows[-1]

    # Use most recent leg direction (or trend)
    if trend == "Bearish" or (trend == "Neutral" and sh["idx"] < sl["idx"]):
        hi_p = sh["price"]
        lo_p = sl["price"]
        leg = max(1.0, hi_p - lo_p)
        ote_618 = round(lo_p + leg * 0.618, 2)
        ote_705 = round(lo_p + leg * 0.705, 2)
        ote_786 = round(lo_p + leg * 0.786, 2)
        in_ote = ote_618 <= cur <= ote_786
        fvg_confluence = any(f["type"] == "bearish" and not (f["bottom"] > ote_786 or f["top"] < ote_618) for f in fvgs)
        ote = {
            "direction": "Short Pullback OTE",
            "anchor_high": round(hi_p, 2), "anchor_low": round(lo_p, 2),
            "fib_618": ote_618, "fib_705": ote_705, "fib_786": ote_786,
            "in_ote": in_ote, "fvg_confluence": fvg_confluence,
        }
        # Standard deviation targets from the prior bullish manipulation leg (if prev swing low exists)
        manip_leg = max(15.0, abs(hi_p - swing_lows[-2]["price"]) if len(swing_lows) >= 2 else leg)
        sd = {
            "direction": "Bearish Expansion Targets",
            "anchor": round(hi_p, 2),
            "sd_15": round(hi_p - manip_leg * 1.5, 2),
            "sd_20": round(hi_p - manip_leg * 2.0, 2),
            "sd_25": round(hi_p - manip_leg * 2.5, 2),
        }
    else:
        hi_p = sh["price"]
        lo_p = sl["price"]
        leg = max(1.0, hi_p - lo_p)
        ote_618 = round(hi_p - leg * 0.618, 2)
        ote_705 = round(hi_p - leg * 0.705, 2)
        ote_786 = round(hi_p - leg * 0.786, 2)
        in_ote = ote_786 <= cur <= ote_618
        fvg_confluence = any(f["type"] == "bullish" and not (f["bottom"] > ote_618 or f["top"] < ote_786) for f in fvgs)
        ote = {
            "direction": "Long Pullback OTE",
            "anchor_high": round(hi_p, 2), "anchor_low": round(lo_p, 2),
            "fib_618": ote_618, "fib_705": ote_705, "fib_786": ote_786,
            "in_ote": in_ote, "fvg_confluence": fvg_confluence,
        }
        manip_leg = max(15.0, abs(swing_highs[-2]["price"] - lo_p) if len(swing_highs) >= 2 else leg)
        sd = {
            "direction": "Bullish Expansion Targets",
            "anchor": round(lo_p, 2),
            "sd_15": round(lo_p + manip_leg * 1.5, 2),
            "sd_20": round(lo_p + manip_leg * 2.0, 2),
            "sd_25": round(lo_p + manip_leg * 2.5, 2),
        }

    return ote, sd


def compute_intermarket_triad(macro_quotes: List[Dict], instrument: str = "DAX") -> Dict:
    by_sym = {q["symbol"]: q for q in (macro_quotes or [])}
    dax = by_sym.get("^GDAXI", {})
    gold = by_sym.get("GC=F", {})
    vix = by_sym.get("^VIX", {})
    eur = by_sym.get("EURUSD=X", {})
    dxy = by_sym.get("DX-Y.NYB", {})
    tnx = by_sym.get("^TNX", {})

    spx = by_sym.get("^GSPC", {})
    btc = by_sym.get("BTC-USD", {})

    dax_chg = dax.get("change_pct", 0.0)
    gold_chg = gold.get("change_pct", 0.0)
    vix_chg = vix.get("change_pct", 0.0)
    eur_chg = eur.get("change_pct", 0.0)
    dxy_chg = dxy.get("change_pct", 0.0)
    tnx_chg = tnx.get("change_pct", 0.0)
    spx_chg = spx.get("change_pct", 0.0)
    btc_chg = btc.get("change_pct", 0.0)

    if instrument == "BTC":
        if dxy_chg < -0.15 and (spx_chg > 0.15 or tnx_chg < -0.4):
            regime = "CRYPTO LIQUIDITY TAILWIND (RISK-ON)"
            tone = "bull"
            detail = f"DXY ({dxy_chg:+.2f}%) weakening while S&P 500 ({spx_chg:+.2f}%) / yields ({tnx_chg:+.2f}%) support high-beta BTC inflows ({btc_chg:+.2f}%)."
        elif dxy_chg > 0.2 and (vix_chg > 2.0 or tnx_chg > 0.6):
            regime = "LIQUIDITY TIGHTENING (DXY / VIX HEADWIND)"
            tone = "bear"
            detail = f"DXY ({dxy_chg:+.2f}%) & VIX ({vix_chg:+.2f}%) / 10Y ({tnx_chg:+.2f}%) rising — tightening global risk appetite for BTC ({btc_chg:+.2f}%)."
        elif vix_chg < -2.0 and spx_chg > 0.25:
            regime = "RISK-ON CRYPTO EXPANSION"
            tone = "bull"
            detail = f"VIX compressing ({vix_chg:+.2f}%) & equities bidding ({spx_chg:+.2f}%) supports BTC upside momentum."
        else:
            regime = "BALANCED CRYPTO MACRO"
            tone = "neut"
            detail = f"DXY ({dxy_chg:+.2f}%), S&P 500 ({spx_chg:+.2f}%), VIX ({vix_chg:+.2f}%), 10Y ({tnx_chg:+.2f}%) in neutral balance."
        return {
            "regime": regime, "tone": tone, "detail": detail,
            "eur_chg": dxy_chg, "fx_label": "DXY", "vix_chg": vix_chg, "tnx_chg": tnx_chg,
        }

    if instrument == "GOLD":
        if dxy_chg < -0.15 and tnx_chg < -0.5:
            regime = "GOLD TAILWIND (WEAK USD + LOWER YIELDS)"
            tone = "bull"
            detail = f"DXY ({dxy_chg:+.2f}%) & US 10Y ({tnx_chg:+.2f}%) falling together — classic institutional Gold tailwind."
        elif dxy_chg > 0.15 and tnx_chg > 0.5:
            regime = "GOLD HEADWIND (STRONG USD + RISING YIELDS)"
            tone = "bear"
            detail = f"DXY ({dxy_chg:+.2f}%) & US 10Y ({tnx_chg:+.2f}%) climbing together — pressures non-yielding Gold ({gold_chg:+.2f}%)."
        elif vix_chg > 2.5:
            regime = "SAFE-HAVEN VOLATILITY BID"
            tone = "bull"
            detail = f"VIX spiking ({vix_chg:+.2f}%) triggers defensive safe-haven demand; DXY ({dxy_chg:+.2f}%), 10Y ({tnx_chg:+.2f}%)."
        else:
            regime = "BALANCED GOLD INTERMARKET"
            tone = "neut"
            detail = f"DXY ({dxy_chg:+.2f}%), US 10Y ({tnx_chg:+.2f}%), VIX ({vix_chg:+.2f}%) showing orderly macro cross-flow."
        return {
            "regime": regime, "tone": tone, "detail": detail,
            "eur_chg": dxy_chg, "fx_label": "DXY", "vix_chg": vix_chg, "tnx_chg": tnx_chg,
        }

    if vix_chg > 2.0 and dax_chg < -0.2:
        regime = "RISK-OFF DE-LEVERAGING"
        tone = "bear"
        detail = f"VIX surging ({vix_chg:+.2f}%) while DAX weakens ({dax_chg:+.2f}%) — confirms institutional risk reduction."
    elif vix_chg > 1.5 and dax_chg >= 0:
        regime = "HIDDEN VOLATILITY WARNING"
        tone = "neut"
        detail = f"VIX climbing ({vix_chg:+.2f}%) even as DAX holds steady ({dax_chg:+.2f}%) — classic distribution warning."
    elif vix_chg < -2.0 and dax_chg > 0.2:
        regime = "RISK-ON EXPANSION"
        tone = "bull"
        detail = f"VIX compressing ({vix_chg:+.2f}%) alongside DAX strength ({dax_chg:+.2f}%) — supports trend continuation."
    else:
        regime = "BALANCED INTERMARKET"
        tone = "neut"
        detail = f"EUR/USD ({eur_chg:+.2f}%), VIX ({vix_chg:+.2f}%), US 10Y ({tnx_chg:+.2f}%) showing orderly cross-asset flow."

    return {
        "regime": regime,
        "tone": tone,
        "detail": detail,
        "eur_chg": eur_chg,
        "vix_chg": vix_chg,
        "tnx_chg": tnx_chg,
    }


def compute_liquidity_and_range(candles_15m: List[Dict], candles_daily: List[Dict], instrument: str = "DAX") -> Dict:
    if not candles_15m:
        return {}

    current_price = round(candles_15m[-1]["c"], 2)
    pdh = pdl = pwh = pwl = None
    if len(candles_daily) >= 2:
        last_d, _ = to_frankfurt_dt(candles_daily[-1]["t"])
        now_d, _ = to_frankfurt_dt()
        prev_day = candles_daily[-2] if last_d.date() == now_d.date() else candles_daily[-1]
        pdh = round(prev_day["h"], 2)
        pdl = round(prev_day["l"], 2)

        cur_week = now_d.isocalendar()[:2]
        prev_week_candles = [dc for dc in candles_daily if to_frankfurt_dt(dc["t"])[0].isocalendar()[:2] < cur_week]
        if prev_week_candles:
            last_wk = to_frankfurt_dt(prev_week_candles[-1]["t"])[0].isocalendar()[:2]
            wk_bars = [c for c in prev_week_candles if to_frankfurt_dt(c["t"])[0].isocalendar()[:2] == last_wk]
            if wk_bars:
                pwh = round(max(b["h"] for b in wk_bars), 2)
                pwl = round(min(b["l"] for b in wk_bars), 2)

    last_day_date = to_frankfurt_dt(candles_15m[-1]["t"])[0].date()
    today_bars = [c for c in candles_15m if to_frankfurt_dt(c["t"])[0].date() == last_day_date]
    orh = orl = None
    if today_bars:
        target_hr = 14 if instrument == "GOLD" else (15 if instrument == "BTC" else 9)
        opening_bars = [c for c in today_bars if to_frankfurt_dt(c["t"])[0].hour == target_hr] or [c for c in today_bars if to_frankfurt_dt(c["t"])[0].hour == 8] or today_bars[:4]
        orh = round(max(b["h"] for b in opening_bars), 2)
        orl = round(min(b["l"] for b in opening_bars), 2)

    range_high = round(max(c["h"] for c in candles_15m), 2)
    range_low = round(min(c["l"] for c in candles_15m), 2)
    eq_50 = round((range_high + range_low) / 2.0, 2)
    span = range_high - range_low
    range_pct = round(((current_price - range_low) / span) * 100.0, 1) if span > 0 else 50.0
    zone = "Premium" if range_pct >= 62.0 else ("Discount" if range_pct <= 38.0 else "Equilibrium")

    recent = candles_15m[-16:]
    sweeps: List[Dict] = []
    for name, lvl, side in [
        ("PDH", pdh, "BSL"), ("PDL", pdl, "SSL"),
        ("PWH", pwh, "BSL"), ("PWL", pwl, "SSL"),
        ("Frankfurt ORH", orh, "BSL"), ("Frankfurt ORL", orl, "SSL"),
    ]:
        if lvl is None:
            continue
        if side == "BSL" and any(c["h"] > lvl and c["c"] < lvl for c in recent):
            sweeps.append({"level": name, "price": lvl, "side": "BSL Swept (Bearish Raid)"})
        elif side == "SSL" and any(c["l"] < lvl and c["c"] > lvl for c in recent):
            sweeps.append({"level": name, "price": lvl, "side": "SSL Swept (Bullish Raid)"})

    return {
        "current_price": current_price,
        "pdh": pdh, "pdl": pdl, "pwh": pwh, "pwl": pwl, "orh": orh, "orl": orl,
        "dealing_range": {"high": range_high, "low": range_low, "equilibrium": eq_50, "position_pct": range_pct, "zone": zone},
        "sweeps": sweeps,
    }


def detect_smt_divergence(dax_candles: List[Dict], peer_candles: List[Dict], peer_name: str = "Euro Stoxx 50", base_name: str = "DAX 40") -> Dict:
    if len(dax_candles) < 25 or len(peer_candles) < 25:
        return {"status": "Unavailable", "type": "none", "peer": peer_name, "detail": "Insufficient aligned candles."}

    peer_by_t = {c["t"]: c for c in peer_candles}
    aligned_dax: List[Dict] = []
    aligned_peer: List[Dict] = []
    for dc in dax_candles:
        pc = peer_by_t.get(dc["t"])
        if pc is None:
            best = min(peer_candles, key=lambda x: abs(x["t"] - dc["t"]))
            if abs(best["t"] - dc["t"]) <= 600:
                pc = best
        if pc is not None:
            aligned_dax.append(dc)
            aligned_peer.append(pc)

    if len(aligned_dax) < 20:
        return {"status": "Unavailable", "type": "none", "peer": peer_name, "detail": "Timestamps not synchronized."}

    d_sh, d_sl = _find_swings(aligned_dax, left=3, right=3)
    p_sh, p_sl = _find_swings(aligned_peer, left=3, right=3)

    bearish_smt = bullish_smt = False
    detail = f"{base_name} and {peer_name} swings are moving symmetrically (no SMT divergence)."

    if len(d_sh) >= 2 and len(p_sh) >= 2:
        if (d_sh[-1]["price"] > d_sh[-2]["price"]) != (p_sh[-1]["price"] > p_sh[-2]["price"]) and abs(d_sh[-1]["idx"] - p_sh[-1]["idx"]) <= 4:
            bearish_smt = True
            leader = base_name if d_sh[-1]["price"] > d_sh[-2]["price"] else peer_name
            lagger = peer_name if leader == base_name else base_name
            detail = f"Bearish SMT: {leader} made a Higher High while {lagger} failed with a Lower High."

    if len(d_sl) >= 2 and len(p_sl) >= 2:
        if (d_sl[-1]["price"] < d_sl[-2]["price"]) != (p_sl[-1]["price"] < p_sl[-2]["price"]) and abs(d_sl[-1]["idx"] - p_sl[-1]["idx"]) <= 4:
            bullish_smt = True
            leader = base_name if d_sl[-1]["price"] < d_sl[-2]["price"] else peer_name
            lagger = peer_name if leader == base_name else base_name
            detail = f"Bullish SMT: {leader} made a Lower Low while {lagger} held a Higher Low."

    if bearish_smt and not bullish_smt:
        return {"status": "Bearish SMT", "type": "bearish", "peer": peer_name, "detail": detail}
    if bullish_smt and not bearish_smt:
        return {"status": "Bullish SMT", "type": "bullish", "peer": peer_name, "detail": detail}
    if bearish_smt and bullish_smt:
        return {"status": "Mixed SMT", "type": "neutral", "peer": peer_name, "detail": detail}
    return {"status": "No Divergence", "type": "none", "peer": peer_name, "detail": detail}


def build_smc_execution_matrix(
    overall_score: int,
    overall_label: str,
    liquidity: Dict,
    structure_trend: str,
    fvgs: List[Dict],
    ifvgs: List[Dict],
    breakers: List[Dict],
    ote: Dict,
    po3: Dict,
    smt_stoxx: Dict,
    smt_spx: Dict,
    killzone: Dict,
) -> Dict:
    if not liquidity:
        return {"verdict": "DATA PENDING", "tone": "neut", "summary": "Awaiting OHLC candle data.", "checklist": []}

    dr = liquidity.get("dealing_range", {})
    zone = dr.get("zone", "Equilibrium")
    pos_pct = dr.get("position_pct", 50.0)
    sweeps = liquidity.get("sweeps", [])
    bsl_swept = any("BSL" in s["side"] for s in sweeps)
    ssl_swept = any("SSL" in s["side"] for s in sweeps)
    fund_dir = "bullish" if overall_score >= 10 else ("bearish" if overall_score <= -10 else "neutral")
    unicorns = [b for b in breakers if b.get("unicorn")]

    if fund_dir == "bearish" and zone == "Premium":
        verdict, tone = "INSTITUTIONAL SHORT ALIGNMENT", "bear"
        next_dol = liquidity.get("pdl") or dr.get("low")
        summary = f"Bearish macro ({overall_score:+d}) aligns with Premium ({pos_pct}%). AMD: {po3.get('amd_phase', '')}. Target DOL: {next_dol}."
    elif fund_dir == "bullish" and zone == "Discount":
        verdict, tone = "INSTITUTIONAL LONG ALIGNMENT", "bull"
        next_dol = liquidity.get("pdh") or dr.get("high")
        summary = f"Bullish macro ({overall_score:+d}) aligns with Discount ({pos_pct}%). AMD: {po3.get('amd_phase', '')}. Target DOL: {next_dol}."
    elif fund_dir == "bearish" and zone == "Discount":
        verdict, tone = "RETAIL SHORT-TRAP WARNING", "neut"
        summary = (
            f"Fundamentals are bearish ({overall_score:+d}), BUT price is deep in Discount ({pos_pct}%). "
            f"Wait for retracement into OTE ({ote.get('fib_618')}–{ote.get('fib_786')}) or Bearish IFVG/Breaker before shorting."
        )
    elif fund_dir == "bullish" and zone == "Premium":
        verdict, tone = "RETAIL LONG-TRAP WARNING", "neut"
        summary = (
            f"Fundamentals are bullish ({overall_score:+d}), BUT price is extended in Premium ({pos_pct}%). "
            f"Wait for pullback into Discount/OTE ({ote.get('fib_618')}–{ote.get('fib_786')}) before longing."
        )
    else:
        verdict = f"{structure_trend.upper()} STRUCTURE · WAIT FOR SWEEP"
        tone = "bull" if structure_trend == "Bullish" and fund_dir == "bullish" else ("bear" if structure_trend == "Bearish" and fund_dir == "bearish" else "neut")
        summary = f"Macro is {overall_label} ({overall_score:+d}) at {pos_pct}% ({zone}). AMD: {po3.get('amd_phase', '--')}. Watch for PDH/PDL sweep + IFVG."

    checklist = [
        f"1. Killzone & AMD: {killzone['phase']} | {po3.get('amd_phase', '--')}",
        f"2. HTF Bias: {overall_label} ({overall_score:+d}) | 15m Structure: {structure_trend}",
        f"3. OTE Sweet Spot (70.5%): {ote.get('fib_705', '--')} ({'ACTIVE IN OTE' if ote.get('in_ote') else 'Outside OTE'}{', +FVG Confluence' if ote.get('fvg_confluence') else ''})",
        f"4. Sweeps (4h): {', '.join(s['level'] + ' ' + s['side'].split('(')[0].strip() for s in sweeps) if sweeps else 'None yet — watch PDH/PDL & ORH/ORL'}",
        f"5. IFVGs & Breakers: {len(ifvgs)} active IFVG(s) | {len(breakers)} Breaker(s){f' ({len(unicorns)} Unicorn!)' if unicorns else ''}",
        f"6. News Rule: Never chase spike candle; wait for sweep -> displacement + IFVG/Breaker.",
    ]
    return {"verdict": verdict, "tone": tone, "summary": summary, "checklist": checklist}


def _calc_atr_15m(candles: List[Dict], period: int = 14) -> float:
    if len(candles) < 2:
        return 30.0
    trs = []
    start = max(1, len(candles) - period)
    for i in range(start, len(candles)):
        h = candles[i]["h"]
        l = candles[i]["l"]
        pc = candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(trs) / len(trs), 2) if trs else 30.0


# ==============================================================================
# v6.0 HIGH-WIN-RATE INSTITUTIONAL ENGINES
# ==============================================================================

def compute_adr_metrics(candles_daily: List[Dict], candles_15m: List[Dict]) -> Dict:
    if not candles_daily or len(candles_daily) < 5:
        return {"available": False}
    hist = candles_daily[:-1][-14:] if len(candles_daily) > 1 else candles_daily[-14:]
    ranges = [max(0.0, d["h"] - d["l"]) for d in hist]
    adr_14d = round(sum(ranges) / len(ranges), 2) if ranges else 250.0

    today_range = 0.0
    if candles_15m:
        latest_date, _ = to_frankfurt_dt(candles_15m[-1]["t"])
        today_bars = [c for c in candles_15m if to_frankfurt_dt(c["t"])[0].date() == latest_date.date()]
        if today_bars:
            today_range = round(max(c["h"] for c in today_bars) - min(c["l"] for c in today_bars), 2)
    if today_range <= 0 and candles_daily:
        today_range = round(candles_daily[-1]["h"] - candles_daily[-1]["l"], 2)

    consumed_pct = round((today_range / adr_14d) * 100.0, 1) if adr_14d > 0 else 0.0
    exhausted = consumed_pct >= 95.0
    warning = consumed_pct >= 80.0
    if exhausted:
        status = "EXHAUSTED (>=95% ADR) — NO BREAKOUT CHASING"
        tone = "bear"
    elif warning:
        status = "EXTENDED (80-94% ADR) — TIGHTEN TARGETS"
        tone = "neut"
    else:
        status = "ROOM TO EXPAND (<80% ADR)"
        tone = "bull"

    return {
        "available": True,
        "adr_14d": adr_14d,
        "today_range": today_range,
        "consumed_pct": consumed_pct,
        "exhausted": exhausted,
        "warning": warning,
        "status": status,
        "tone": tone,
    }


def check_news_blackout(catalysts: Optional[List[Dict]], utc_ts: Optional[float] = None) -> Dict:
    if not catalysts:
        return {"active": False, "upcoming_soon": False, "status": "CLEAR — NO BLACKOUT", "tone": "bull"}

    now_de, tz_abbr = to_frankfurt_dt(utc_ts)
    for cat in catalysts:
        if cat.get("importance") != "High":
            continue
        date_str = cat.get("date", "")
        time_str = cat.get("time", "")
        m = re.search(r"(\d{1,2}):(\d{2})", time_str)
        if not date_str or not m:
            continue
        try:
            hh, mm = int(m.group(1)), int(m.group(2))
            ev_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hh, minute=mm, tzinfo=now_de.tzinfo)
            delta_mins = (ev_dt - now_de).total_seconds() / 60.0
            if -15.0 <= delta_mins <= 45.0:
                return {
                    "active": True,
                    "upcoming_soon": True,
                    "event": cat.get("event", "High-Impact Macro Event"),
                    "time": f"{date_str} {time_str}",
                    "mins_to_event": round(delta_mins, 1),
                    "status": f"NEWS BLACKOUT ({cat.get('event')[:32]} in {round(delta_mins)}m)",
                    "tone": "bear",
                }
            if 45.0 < delta_mins <= 120.0:
                return {
                    "active": False,
                    "upcoming_soon": True,
                    "event": cat.get("event", "High-Impact Macro Event"),
                    "time": f"{date_str} {time_str}",
                    "mins_to_event": round(delta_mins, 1),
                    "status": f"PRE-NEWS CAUTION ({cat.get('event')[:28]} in {round(delta_mins)}m)",
                    "tone": "neut",
                }
        except Exception:
            continue

    return {"active": False, "upcoming_soon": False, "status": "CLEAR — NO HIGH-IMPACT BLACKOUT", "tone": "bull"}


def analyze_dax_breadth(dax_constituents: Optional[List[Dict]]) -> Dict:
    if not dax_constituents:
        return {"available": False, "regime": "UNAVAILABLE", "tone": "neut", "bull_pct": 50.0, "bear_pct": 50.0}

    total = len(dax_constituents)
    advancers = sum(1 for s in dax_constituents if (s.get("change_pct") or 0) > 0.05)
    decliners = sum(1 for s in dax_constituents if (s.get("change_pct") or 0) < -0.05)
    flat = total - advancers - decliners
    bull_pct = round((advancers / total) * 100.0, 1) if total else 50.0
    bear_pct = round((decliners / total) * 100.0, 1) if total else 50.0

    heavy_syms = {"SAP.DE", "SIE.DE", "ALV.DE", "AIR.DE"}
    heavies = [s for s in dax_constituents if s.get("symbol") in heavy_syms]
    heavy_bull = sum(1 for s in heavies if (s.get("change_pct") or 0) > 0.05)
    heavy_bear = sum(1 for s in heavies if (s.get("change_pct") or 0) < -0.05)

    if bull_pct >= 60.0 and heavy_bull >= 2:
        regime, tone = "BROAD BULLISH PARTICIPATION", "bull"
    elif bear_pct >= 60.0 and heavy_bear >= 2:
        regime, tone = "BROAD BEARISH DISTRIBUTION", "bear"
    elif bull_pct < 45.0 and heavy_bull >= 2:
        regime, tone = "THIN BULLISH BREADTH (FAKEOUT RISK)", "neut"
    elif bear_pct < 45.0 and heavy_bear >= 2:
        regime, tone = "THIN BEARISH BREADTH (SQUEEZE RISK)", "neut"
    else:
        regime, tone = "MIXED SECTOR BREADTH", "neut"

    return {
        "available": True,
        "total": total,
        "advancers": advancers,
        "decliners": decliners,
        "flat": flat,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "heavy_bull": heavy_bull,
        "heavy_bear": heavy_bear,
        "regime": regime,
        "tone": tone,
    }


def detect_htf_1h_context(candles_1h: Optional[List[Dict]], cur_price: float, daily_fvgs: List[Dict]) -> Dict:
    if not candles_1h or len(candles_1h) < 16:
        return {"available": False, "trend_1h": "Neutral", "fvgs_1h": [], "obs_1h": [], "bull_nested": False, "bear_nested": False}

    sh_1h, sl_1h = _find_swings(candles_1h, left=2, right=2)
    fvgs_1h, _ = _detect_fvgs_and_ifvgs(candles_1h)
    trend_1h, _, obs_1h, _ = _detect_structure_obs_and_breakers(candles_1h, sh_1h, sl_1h, fvgs_1h)

    tol = cur_price * 0.0015  # ~0.15% buffer around HTF POI
    bull_htf_pois = (
        [{"src": "1H FVG", **f} for f in fvgs_1h if f["type"] == "bullish"]
        + [{"src": "1H OB", **o} for o in obs_1h if o["type"] == "bullish"]
        + [{"src": "1D FVG", **df} for df in daily_fvgs if df["type"] == "bullish"]
    )
    bear_htf_pois = (
        [{"src": "1H FVG", **f} for f in fvgs_1h if f["type"] == "bearish"]
        + [{"src": "1H OB", **o} for o in obs_1h if o["type"] == "bearish"]
        + [{"src": "1D FVG", **df} for df in daily_fvgs if df["type"] == "bearish"]
    )

    bull_match = next((p["src"] for p in bull_htf_pois if (p["bottom"] - tol) <= cur_price <= (p["top"] + tol)), None)
    bear_match = next((p["src"] for p in bear_htf_pois if (p["bottom"] - tol) <= cur_price <= (p["top"] + tol)), None)

    return {
        "available": True,
        "trend_1h": trend_1h,
        "fvgs_1h": fvgs_1h[-4:],
        "obs_1h": obs_1h[-4:],
        "bull_nested": bull_match is not None,
        "bull_nest_src": bull_match,
        "bear_nested": bear_match is not None,
        "bear_nest_src": bear_match,
    }


def detect_eqh_eql_and_sweep_displacement(
    candles_15m: List[Dict],
    swing_highs: List[Dict],
    swing_lows: List[Dict],
    fvgs: List[Dict],
    ifvgs: List[Dict],
    liquidity: Dict,
    atr: float,
) -> Dict:
    cur = candles_15m[-1]["c"]
    cluster_tol = max(cur * 0.0005, atr * 0.45)

    # Equal Highs / Equal Lows clusters (retail stop pockets)
    eqh_levels: List[float] = []
    sh_recent = swing_highs[-8:]
    for i in range(len(sh_recent)):
        for j in range(i + 1, len(sh_recent)):
            if abs(sh_recent[i]["price"] - sh_recent[j]["price"]) <= cluster_tol:
                lvl = round(max(sh_recent[i]["price"], sh_recent[j]["price"]), 2)
                if lvl > cur:
                    eqh_levels.append(lvl)

    eql_levels: List[float] = []
    sl_recent = swing_lows[-8:]
    for i in range(len(sl_recent)):
        for j in range(i + 1, len(sl_recent)):
            if abs(sl_recent[i]["price"] - sl_recent[j]["price"]) <= cluster_tol:
                lvl = round(min(sl_recent[i]["price"], sl_recent[j]["price"]), 2)
                if lvl < cur:
                    eql_levels.append(lvl)

    eqh = min(eqh_levels) if eqh_levels else None
    eql = max(eql_levels) if eql_levels else None

    # 2-step Sweep -> Displacement confirmation in last 14 bars (~3.5h)
    recent = candles_15m[-14:]
    bear_sweep_disp = False
    bull_sweep_disp = False
    sweep_notes: List[str] = []

    high_refs = [p for p in [liquidity.get("pdh"), liquidity.get("orh"), liquidity.get("pwh")] if p is not None]
    if swing_highs:
        high_refs.extend([s["price"] for s in swing_highs[-4:]])
    low_refs = [p for p in [liquidity.get("pdl"), liquidity.get("orl"), liquidity.get("pwl")] if p is not None]
    if swing_lows:
        low_refs.extend([s["price"] for s in swing_lows[-4:]])

    for i in range(len(recent) - 1):
        bar = recent[i]
        # Bearish raid above ref followed by bearish displacement
        if any(bar["h"] > ref and bar["c"] < ref for ref in high_refs):
            for k in range(i, min(len(recent), i + 4)):
                dk = recent[k]
                if dk["c"] < dk["o"] and (dk["o"] - dk["c"]) >= atr * 1.1:
                    bear_sweep_disp = True
                    sweep_notes.append("BSL Sweep -> Bearish Displacement")
                    break
        # Bullish raid below ref followed by bullish displacement
        if any(bar["l"] < ref and bar["c"] > ref for ref in low_refs):
            for k in range(i, min(len(recent), i + 4)):
                dk = recent[k]
                if dk["c"] > dk["o"] and (dk["c"] - dk["o"]) >= atr * 1.1:
                    bull_sweep_disp = True
                    sweep_notes.append("SSL Sweep -> Bullish Displacement")
                    break

    if not bear_sweep_disp and any("BSL" in s["side"] for s in liquidity.get("sweeps", [])) and any(f["type"] == "bearish" for f in fvgs[-3:]):
        bear_sweep_disp = True
        sweep_notes.append("4h BSL Sweep + Bearish FVG")
    if not bull_sweep_disp and any("SSL" in s["side"] for s in liquidity.get("sweeps", [])) and any(f["type"] == "bullish" for f in fvgs[-3:]):
        bull_sweep_disp = True
        sweep_notes.append("4h SSL Sweep + Bullish FVG")

    # Candlestick Rejection Triggers on last 3 closed candles
    bear_candle_trig = False
    bull_candle_trig = False
    trig_note = ""
    if len(candles_15m) >= 3:
        for idx_off in (-1, -2):
            c = candles_15m[idx_off]
            prev = candles_15m[idx_off - 1]
            body = abs(c["c"] - c["o"])
            up_wick = c["h"] - max(c["o"], c["c"])
            dn_wick = min(c["o"], c["c"]) - c["l"]
            if c["c"] < c["o"] and (up_wick >= max(cur * 0.0003, body * 1.45) or (prev["c"] > prev["o"] and c["c"] < prev["o"])):
                bear_candle_trig = True
                trig_note = "Bearish Pin/Engulfing Rejection"
            if c["c"] > c["o"] and (dn_wick >= max(cur * 0.0003, body * 1.45) or (prev["c"] < prev["o"] and c["c"] > prev["o"])):
                bull_candle_trig = True
                trig_note = "Bullish Pin/Engulfing Rejection"

    return {
        "eqh": eqh,
        "eql": eql,
        "bear_sweep_disp": bear_sweep_disp,
        "bull_sweep_disp": bull_sweep_disp,
        "bear_candle_trig": bear_candle_trig,
        "bull_candle_trig": bull_candle_trig,
        "trig_note": trig_note,
        "sweep_notes": list(dict.fromkeys(sweep_notes)),
    }


def generate_smc_trade_signals(
    candles_15m: List[Dict],
    swing_highs: List[Dict],
    swing_lows: List[Dict],
    trend: str,
    fvgs: List[Dict],
    ifvgs: List[Dict],
    obs: List[Dict],
    breakers: List[Dict],
    liquidity: Dict,
    ipda: Dict,
    po3: Dict,
    ote: Dict,
    sd_targets: Dict,
    smt_stoxx: Dict,
    smt_spx: Dict,
    intermarket: Dict,
    killzone: Dict,
    overall_score: int,
    overall_label: str,
    htf_1h: Optional[Dict] = None,
    adr: Optional[Dict] = None,
    blackout: Optional[Dict] = None,
    breadth: Optional[Dict] = None,
    price_action: Optional[Dict] = None,
) -> Dict:
    if not candles_15m or not liquidity:
        return {"available": False}

    cur = liquidity["current_price"]
    atr = _calc_atr_15m(candles_15m, 14)
    sl_buf = round(max(cur * 0.0005, min(cur * 0.0022, atr * 0.45)), 2)

    htf_1h = htf_1h or {}
    adr = adr or {}
    blackout = blackout or {}
    breadth = breadth or {}
    price_action = price_action or {}

    dr = liquidity.get("dealing_range", {})
    zone = dr.get("zone", "Equilibrium")
    sweeps = liquidity.get("sweeps", [])
    bsl_swept = any("BSL" in s["side"] for s in sweeps)
    ssl_swept = any("SSL" in s["side"] for s in sweeps)
    smt_bear = smt_stoxx.get("type") == "bearish" or smt_spx.get("type") == "bearish"
    smt_bull = smt_stoxx.get("type") == "bullish" or smt_spx.get("type") == "bullish"

    short_reasons: List[str] = []
    long_reasons: List[str] = []
    short_pts = 0
    long_pts = 0

    # 1. Macro Fundamentals (up to 18)
    if overall_score <= -20:
        short_pts += 18
        short_reasons.append(f"Bearish Fundamentals ({overall_score:+d} {overall_label})")
    elif overall_score <= -8:
        short_pts += 12
        short_reasons.append(f"Mildly Bearish Fundamentals ({overall_score:+d})")
    elif overall_score >= 20:
        long_pts += 18
        long_reasons.append(f"Bullish Fundamentals ({overall_score:+d} {overall_label})")
    elif overall_score >= 8:
        long_pts += 12
        long_reasons.append(f"Mildly Bullish Fundamentals ({overall_score:+d})")

    # 2. 15m Structure + 1H HTF Structure & Nesting (up to 28)
    if trend == "Bearish":
        short_pts += 14
        short_reasons.append("15m Market Structure Bearish (BOS/CHoCH)")
    elif trend == "Bullish":
        long_pts += 14
        long_reasons.append("15m Market Structure Bullish (BOS/CHoCH)")

    if htf_1h.get("trend_1h") == "Bearish":
        short_pts += 12
        short_reasons.append("1H HTF Trend Aligned Bearish")
    elif htf_1h.get("trend_1h") == "Bullish":
        long_pts += 12
        long_reasons.append("1H HTF Trend Aligned Bullish")

    if htf_1h.get("bear_nested"):
        short_pts += 8
        short_reasons.append(f"Nested inside {htf_1h.get('bear_nest_src')}")
    if htf_1h.get("bull_nested"):
        long_pts += 8
        long_reasons.append(f"Nested inside {htf_1h.get('bull_nest_src')}")

    # 3. Sweep + Displacement Gate (up to 16)
    if price_action.get("bear_sweep_disp"):
        short_pts += 16
        short_reasons.append("Confirmed BSL Sweep + Bearish Displacement")
    elif bsl_swept:
        short_pts += 8
        short_reasons.append("Recent BSL Sweep (await displacement)")

    if price_action.get("bull_sweep_disp"):
        long_pts += 16
        long_reasons.append("Confirmed SSL Sweep + Bullish Displacement")
    elif ssl_swept:
        long_pts += 8
        long_reasons.append("Recent SSL Sweep (await displacement)")

    # 4. Candlestick Trigger inside POI (+8)
    if price_action.get("bear_candle_trig"):
        short_pts += 8
        short_reasons.append("15m Bearish Pin/Engulfing Trigger")
    if price_action.get("bull_candle_trig"):
        long_pts += 8
        long_reasons.append("15m Bullish Pin/Engulfing Trigger")

    # 5. Power of 3 Open, Intermarket, SMT, Breadth
    if po3 and not po3.get("above_cash_open", True):
        short_pts += 10
        short_reasons.append(f"Below {po3.get('open_label', 'Xetra Open')} ({po3.get('cash_open')})")
    elif po3 and po3.get("above_cash_open", False):
        long_pts += 10
        long_reasons.append(f"Above {po3.get('open_label', 'Xetra Open')} ({po3.get('cash_open')})")

    if smt_bear:
        short_pts += 8
        short_reasons.append("Bearish SMT Divergence")
    if smt_bull:
        long_pts += 8
        long_reasons.append("Bullish SMT Divergence")

    if intermarket.get("tone") == "bear":
        short_pts += 6
        short_reasons.append(f"Intermarket {intermarket.get('regime')}")
    elif intermarket.get("tone") == "bull":
        long_pts += 6
        long_reasons.append(f"Intermarket {intermarket.get('regime')}")

    if breadth.get("available"):
        if breadth.get("bear_pct", 0) >= 60.0:
            short_pts += 8
            short_reasons.append(f"DAX Breadth Bearish ({breadth['decliners']}/{breadth['total']} red)")
        elif breadth.get("bull_pct", 0) >= 60.0:
            long_pts += 8
            long_reasons.append(f"DAX Breadth Bullish ({breadth['advancers']}/{breadth['total']} green)")

    # 6. Premium/Discount & 15m Supply/Demand Zones
    bear_pois = (
        [f for f in fvgs if f["type"] == "bearish" and f["top"] > cur - atr * 0.5]
        + [iv for iv in ifvgs if iv["type"] == "bearish_ifvg" and iv["top"] > cur - atr * 0.5]
        + [b for b in breakers if b["type"] == "bearish_breaker" and b["top"] > cur - atr * 0.5]
        + [o for o in obs if o["type"] == "bearish" and o["top"] > cur - atr * 0.5]
    )
    bull_pois = (
        [f for f in fvgs if f["type"] == "bullish" and f["bottom"] < cur + atr * 0.5]
        + [iv for iv in ifvgs if iv["type"] == "bullish_ifvg" and iv["bottom"] < cur + atr * 0.5]
        + [b for b in breakers if b["type"] == "bullish_breaker" and b["bottom"] < cur + atr * 0.5]
        + [o for o in obs if o["type"] == "bullish" and o["bottom"] < cur + atr * 0.5]
    )

    if zone == "Premium":
        short_pts += 8
        short_reasons.append(f"Price in Premium ({dr.get('position_pct')}%)")
    elif zone == "Discount":
        long_pts += 8
        long_reasons.append(f"Price in Discount ({dr.get('position_pct')}%)")

    if bear_pois:
        short_pts += 6
        short_reasons.append("Bearish 15m FVG/IFVG/OB Supply")
    if bull_pois:
        long_pts += 6
        long_reasons.append("Bullish 15m FVG/IFVG/OB Demand")

    if killzone.get("is_killzone"):
        short_pts += 4
        long_pts += 4

    # Penalties for Thin Breadth Fakeout or Exhausted ADR
    if breadth.get("regime") == "THIN BULLISH BREADTH (FAKEOUT RISK)":
        long_pts = max(0, long_pts - 15)
        long_reasons.append("WARNING: Thin Bullish Breadth (Fakeout Risk)")
    elif breadth.get("regime") == "THIN BEARISH BREADTH (SQUEEZE RISK)":
        short_pts = max(0, short_pts - 15)
        short_reasons.append("WARNING: Thin Bearish Breadth (Squeeze Risk)")

    short_conf = min(98, short_pts)
    long_conf = min(98, long_pts)

    def _build_short_plan() -> Dict:
        candidates = sorted(bear_pois, key=lambda x: abs(((x["top"] + x["bottom"]) / 2.0) - cur))
        if candidates:
            poi = candidates[0]
            entry_low = round(poi["bottom"], 2)
            entry_high = round(poi["top"], 2)
            entry_mid = round((entry_low + entry_high) / 2.0, 2)
            entry_src = poi.get("note") or ("Bearish FVG CE" if "partially_filled" in poi else "Bearish OB/Breaker")
        elif ote and ote.get("direction", "").startswith("Short") and ote.get("fib_618"):
            entry_low = ote["fib_618"]
            entry_high = ote["fib_786"]
            entry_mid = ote["fib_705"]
            entry_src = "Short OTE (61.8% - 78.6%)"
        else:
            entry_low = round(cur, 2)
            entry_high = round(cur + atr * 0.5, 2)
            entry_mid = round(cur + atr * 0.2, 2)
            entry_src = "Market / Minor Retrace"

        in_zone = (entry_low - sl_buf * 0.45) <= cur <= (entry_high + sl_buf * 0.45)
        recent_sh = max([s["price"] for s in swing_highs[-3:] if s["price"] > entry_mid] or [entry_high + atr])
        raw_sl = max(entry_high + sl_buf, min(recent_sh + sl_buf, entry_mid + max(cur * 0.0018, atr * 2.2)))

        # Wick-Protected SL: if EQH or un-swept PDH sits just above raw_sl, shield SL beyond it
        eqh = price_action.get("eqh")
        shield_notes: List[str] = []
        for pool_name, pool_val in [("EQH", eqh), ("PDH", liquidity.get("pdh")), ("ORH", liquidity.get("orh"))]:
            if pool_val is not None and entry_mid < pool_val <= raw_sl + atr * 0.65:
                if pool_val + sl_buf * 0.8 > raw_sl:
                    raw_sl = pool_val + sl_buf * 0.8
                    shield_notes.append(f"SL shielded above {pool_name} ({pool_val})")

        sl = round(max(raw_sl, entry_mid + max(cur * 0.0012, atr * 0.75)), 2)
        risk = round(sl - entry_mid, 2)

        low_pools = sorted(
            set(
                p for p in [
                    liquidity.get("orl"), liquidity.get("pdl"), liquidity.get("pwl"),
                    dr.get("low"), (ipda.get("d20") or {}).get("low"),
                    (sd_targets or {}).get("sd_15") if (sd_targets or {}).get("direction", "").startswith("Bearish") else None,
                    (sd_targets or {}).get("sd_20") if (sd_targets or {}).get("direction", "").startswith("Bearish") else None,
                    (sd_targets or {}).get("sd_25") if (sd_targets or {}).get("direction", "").startswith("Bearish") else None,
                ]
                if p is not None and p < entry_mid - risk * 0.8
            ),
            reverse=True,
        )

        tp1 = round(low_pools[0], 2) if len(low_pools) >= 1 else round(entry_mid - risk * 1.4, 2)
        if tp1 > entry_mid - risk * 1.1:
            tp1 = round(entry_mid - risk * 1.3, 2)
        tp2_cand = next((p for p in low_pools if p <= min(entry_mid - risk * 2.0, tp1 - risk * 0.6)), None)
        tp2 = round(tp2_cand, 2) if tp2_cand is not None else round(min(entry_mid - risk * 2.3, tp1 - risk * 0.9), 2)
        tp3_cand = next((p for p in low_pools if p <= tp2 - risk * 0.8), None)
        tp3 = round(tp3_cand, 2) if tp3_cand is not None else round(min(entry_mid - risk * 3.4, tp2 - risk * 1.0), 2)

        rr1 = round((entry_mid - tp1) / risk, 2) if risk > 0 else 0
        rr2 = round((entry_mid - tp2) / risk, 2) if risk > 0 else 0
        rr3 = round((entry_mid - tp3) / risk, 2) if risk > 0 else 0

        # v6.0 Strict Win-Rate Gates
        has_trigger = price_action.get("bear_sweep_disp") or price_action.get("bear_candle_trig")
        htf_ok = (htf_1h.get("trend_1h") == "Bearish") or htf_1h.get("bear_nested") or not htf_1h.get("available")

        if blackout.get("active"):
            status, status_tone = "NEWS BLACKOUT — WAIT", "bear"
        elif killzone.get("is_deadzone"):
            status, status_tone = "SESSION DEADZONE — WAIT", "neut"
        elif adr.get("exhausted") and not htf_1h.get("bear_nested"):
            status, status_tone = "ADR EXHAUSTED — NO CHASE", "neut"
        elif short_conf >= 62 and in_zone and has_trigger and htf_ok:
            status, status_tone = "ACTIVE SELL SETUP", "bear"
        elif short_conf >= 48:
            if not in_zone and cur < entry_low:
                status = "PENDING SELL LIMIT (PULLBACK)"
            elif not has_trigger:
                status = "WATCH SELL (AWAIT SWEEP/REJECTION)"
            else:
                status = "WATCH SELL (HTF FILTER)"
            status_tone = "neut"
        else:
            status, status_tone = "LOW CONFLUENCE — WAIT", "neut"

        reasons_all = short_reasons + shield_notes
        return {
            "direction": "SHORT",
            "status": status,
            "status_tone": status_tone,
            "confidence": short_conf,
            "entry_source": entry_src,
            "entry_zone": f"{entry_low} – {entry_high}",
            "entry_low": entry_low,
            "entry_high": entry_high,
            "entry_price": entry_mid,
            "stop_loss": sl,
            "risk_pts": risk,
            "tp1": tp1, "rr1": rr1,
            "tp2": tp2, "rr2": rr2,
            "tp3": tp3, "rr3": rr3,
            "reasons": reasons_all or ["Counter-trend short idea only; await 1H/15m Bearish CHoCH."],
            "invalidation": f"15m close above {sl} invalidates bearish delivery. Move SL to BE ({entry_mid}) at TP1 ({tp1}).",
        }

    def _build_long_plan() -> Dict:
        candidates = sorted(bull_pois, key=lambda x: abs(((x["top"] + x["bottom"]) / 2.0) - cur))
        if candidates:
            poi = candidates[0]
            entry_low = round(poi["bottom"], 2)
            entry_high = round(poi["top"], 2)
            entry_mid = round((entry_low + entry_high) / 2.0, 2)
            entry_src = poi.get("note") or ("Bullish FVG CE" if "partially_filled" in poi else "Bullish OB/Breaker")
        elif ote and ote.get("direction", "").startswith("Long") and ote.get("fib_618"):
            entry_low = ote["fib_786"]
            entry_high = ote["fib_618"]
            entry_mid = ote["fib_705"]
            entry_src = "Long OTE (61.8% - 78.6%)"
        else:
            entry_low = round(cur - atr * 0.5, 2)
            entry_high = round(cur, 2)
            entry_mid = round(cur - atr * 0.2, 2)
            entry_src = "Market / Minor Pullback"

        in_zone = (entry_low - sl_buf * 0.45) <= cur <= (entry_high + sl_buf * 0.45)
        recent_sl = min([s["price"] for s in swing_lows[-3:] if s["price"] < entry_mid] or [entry_low - atr])
        raw_sl = min(entry_low - sl_buf, max(recent_sl - sl_buf, entry_mid - max(cur * 0.0018, atr * 2.2)))

        # Wick-Protected SL beyond EQL / PDL / ORL
        eql = price_action.get("eql")
        shield_notes: List[str] = []
        for pool_name, pool_val in [("EQL", eql), ("PDL", liquidity.get("pdl")), ("ORL", liquidity.get("orl"))]:
            if pool_val is not None and raw_sl - atr * 0.65 <= pool_val < entry_mid:
                if pool_val - sl_buf * 0.8 < raw_sl:
                    raw_sl = pool_val - sl_buf * 0.8
                    shield_notes.append(f"SL shielded below {pool_name} ({pool_val})")

        sl = round(min(raw_sl, entry_mid - max(cur * 0.0012, atr * 0.75)), 2)
        risk = round(entry_mid - sl, 2)

        high_pools = sorted(
            set(
                p for p in [
                    liquidity.get("orh"), dr.get("equilibrium"), liquidity.get("pdh"),
                    liquidity.get("pwh"), dr.get("high"), (ipda.get("d20") or {}).get("high"),
                    (sd_targets or {}).get("sd_15") if (sd_targets or {}).get("direction", "").startswith("Bullish") else None,
                    (sd_targets or {}).get("sd_20") if (sd_targets or {}).get("direction", "").startswith("Bullish") else None,
                    (sd_targets or {}).get("sd_25") if (sd_targets or {}).get("direction", "").startswith("Bullish") else None,
                ]
                if p is not None and p > entry_mid + risk * 0.8
            )
        )

        tp1 = round(high_pools[0], 2) if len(high_pools) >= 1 else round(entry_mid + risk * 1.4, 2)
        if tp1 < entry_mid + risk * 1.1:
            tp1 = round(entry_mid + risk * 1.3, 2)
        tp2_cand = next((p for p in high_pools if p >= max(entry_mid + risk * 2.0, tp1 + risk * 0.6)), None)
        tp2 = round(tp2_cand, 2) if tp2_cand is not None else round(max(entry_mid + risk * 2.3, tp1 + risk * 0.9), 2)
        tp3_cand = next((p for p in high_pools if p >= tp2 + risk * 0.8), None)
        tp3 = round(tp3_cand, 2) if tp3_cand is not None else round(max(entry_mid + risk * 3.4, tp2 + risk * 1.0), 2)

        rr1 = round((tp1 - entry_mid) / risk, 2) if risk > 0 else 0
        rr2 = round((tp2 - entry_mid) / risk, 2) if risk > 0 else 0
        rr3 = round((tp3 - entry_mid) / risk, 2) if risk > 0 else 0

        has_trigger = price_action.get("bull_sweep_disp") or price_action.get("bull_candle_trig")
        htf_ok = (htf_1h.get("trend_1h") == "Bullish") or htf_1h.get("bull_nested") or not htf_1h.get("available")

        if blackout.get("active"):
            status, status_tone = "NEWS BLACKOUT — WAIT", "bear"
        elif killzone.get("is_deadzone"):
            status, status_tone = "SESSION DEADZONE — WAIT", "neut"
        elif adr.get("exhausted") and not htf_1h.get("bull_nested"):
            status, status_tone = "ADR EXHAUSTED — NO CHASE", "neut"
        elif long_conf >= 62 and in_zone and has_trigger and htf_ok:
            status, status_tone = "ACTIVE BUY SETUP", "bull"
        elif long_conf >= 48:
            if not in_zone and cur > entry_high:
                status = "PENDING BUY LIMIT (PULLBACK)"
            elif not has_trigger:
                status = "WATCH BUY (AWAIT SWEEP/REJECTION)"
            else:
                status = "WATCH BUY (HTF FILTER)"
            status_tone = "neut"
        else:
            status, status_tone = "LOW CONFLUENCE — WAIT", "neut"

        reasons_all = long_reasons + shield_notes
        return {
            "direction": "LONG",
            "status": status,
            "status_tone": status_tone,
            "confidence": long_conf,
            "entry_source": entry_src,
            "entry_zone": f"{entry_low} – {entry_high}",
            "entry_low": entry_low,
            "entry_high": entry_high,
            "entry_price": entry_mid,
            "stop_loss": sl,
            "risk_pts": risk,
            "tp1": tp1, "rr1": rr1,
            "tp2": tp2, "rr2": rr2,
            "tp3": tp3, "rr3": rr3,
            "reasons": reasons_all or ["Counter-trend long idea only; await 1H/15m Bullish CHoCH."],
            "invalidation": f"15m close below {sl} invalidates bullish delivery. Move SL to BE ({entry_mid}) at TP1 ({tp1}).",
        }

    short_plan = _build_short_plan()
    long_plan = _build_long_plan()
    primary, alternative = (short_plan, long_plan) if short_conf >= long_conf else (long_plan, short_plan)

    return {
        "available": True,
        "atr_15m": atr,
        "gates": {
            "adr": adr,
            "blackout": blackout,
            "breadth": breadth,
            "htf_1h": htf_1h,
            "price_action": price_action,
        },
        "primary": primary,
        "alternative": alternative,
    }


def _simulate_outcome_with_be(future_bars: List[Dict], direction: str, entry: float, sl: float, tp1: float, tp2: float) -> Tuple[str, float]:
    """Simulate causal trade outcome with 'Move SL to Breakeven at TP1 (50% partial)' rule."""
    tp1_hit = False
    for bar in future_bars:
        if direction == "SHORT":
            if not tp1_hit:
                if bar["h"] >= sl:
                    return "SL LOSS", -1.0
                if bar["l"] <= tp2:
                    return "TP2 WIN", 2.0
                if bar["l"] <= tp1:
                    tp1_hit = True
            else:
                if bar["l"] <= tp2:
                    return "TP2 WIN", 1.75
                if bar["h"] >= entry:
                    return "TP1 BE WIN", 0.65
        else:
            if not tp1_hit:
                if bar["l"] <= sl:
                    return "SL LOSS", -1.0
                if bar["h"] >= tp2:
                    return "TP2 WIN", 2.0
                if bar["h"] >= tp1:
                    tp1_hit = True
            else:
                if bar["h"] >= tp2:
                    return "TP2 WIN", 1.75
                if bar["l"] <= entry:
                    return "TP1 BE WIN", 0.65
    return ("TP1 OPEN (BE)" if tp1_hit else "OPEN"), (0.5 if tp1_hit else 0.0)


def run_5d_walkforward_backtest(candles_15m: List[Dict]) -> Dict:
    """Strictly causal bar-by-bar walk-forward backtest on the real 5d/15m ^GDAXI bars."""
    if not candles_15m or len(candles_15m) < 55:
        return {"available": False, "trades": 0}

    trades: List[Dict] = []
    cooldown_until = 0
    n = len(candles_15m)

    for idx in range(40, n - 8):
        if idx < cooldown_until:
            continue
        kz = get_killzone_status(candles_15m[idx]["t"])
        if kz.get("is_deadzone"):
            continue

        window = candles_15m[: idx + 1]
        atr = _calc_atr_15m(window, 14)
        sh, sl_sw = _find_swings(window, left=2, right=2)
        fvgs, ifvgs = _detect_fvgs_and_ifvgs(window)
        trend, _, obs, breakers = _detect_structure_obs_and_breakers(window, sh, sl_sw, fvgs)
        cur = window[-1]["c"]
        prev = window[-2]

        body = abs(window[-1]["c"] - window[-1]["o"])
        up_wick = window[-1]["h"] - max(window[-1]["o"], window[-1]["c"])
        dn_wick = min(window[-1]["o"], window[-1]["c"]) - window[-1]["l"]

        direction = None
        entry = cur
        sl_px = cur
        setup_name = ""

        # Bearish Killzone FVG/OB + Pin/Engulfing
        if trend == "Bearish":
            bear_zones = [f for f in fvgs if f["type"] == "bearish"] + [o for o in obs if o["type"] == "bearish"]
            near_bear = [z for z in bear_zones if z["bottom"] - atr * 0.4 <= window[-1]["h"] <= z["top"] + atr * 0.5]
            bear_rej = (window[-1]["c"] < window[-1]["o"]) and (up_wick >= body * 1.2 or (prev["c"] > prev["o"] and window[-1]["c"] < prev["o"]))
            if near_bear and bear_rej:
                direction = "SHORT"
                z = near_bear[-1]
                sl_px = round(max(z["top"], window[-1]["h"]) + max(cur * 0.0005, atr * 0.45), 2)
                setup_name = "KZ Bearish POI + Rejection"

        # Bullish Killzone FVG/OB + Pin/Engulfing
        if direction is None and trend == "Bullish":
            bull_zones = [f for f in fvgs if f["type"] == "bullish"] + [o for o in obs if o["type"] == "bullish"]
            near_bull = [z for z in bull_zones if z["bottom"] - atr * 0.5 <= window[-1]["l"] <= z["top"] + atr * 0.4]
            bull_rej = (window[-1]["c"] > window[-1]["o"]) and (dn_wick >= body * 1.2 or (prev["c"] < prev["o"] and window[-1]["c"] > prev["o"]))
            if near_bull and bull_rej:
                direction = "LONG"
                z = near_bull[-1]
                sl_px = round(min(z["bottom"], window[-1]["l"]) - max(cur * 0.0005, atr * 0.45), 2)
                setup_name = "KZ Bullish POI + Rejection"

        if direction is None:
            continue

        risk = abs(entry - sl_px)
        if risk < max(cur * 0.0008, atr * 0.45) or risk > atr * 3.2:
            continue

        tp1 = round(entry - risk * 1.3 if direction == "SHORT" else entry + risk * 1.3, 2)
        tp2 = round(entry - risk * 2.2 if direction == "SHORT" else entry + risk * 2.2, 2)
        outcome, r_res = _simulate_outcome_with_be(candles_15m[idx + 1 : idx + 25], direction, entry, sl_px, tp1, tp2)
        if outcome == "OPEN":
            continue

        dt_de, tz = to_frankfurt_dt(window[-1]["t"])
        trades.append({
            "time": dt_de.strftime("%m-%d %H:%M ") + tz,
            "direction": direction,
            "setup": setup_name,
            "entry": round(entry, 2),
            "sl": sl_px,
            "tp1": tp1,
            "tp2": tp2,
            "outcome": outcome,
            "r": round(r_res, 2),
        })
        cooldown_until = idx + 6

    closed = [t for t in trades if t["outcome"] in ("TP2 WIN", "TP1 BE WIN", "SL LOSS", "TP1 OPEN (BE)")]
    wins = sum(1 for t in closed if t["r"] > 0)
    losses = sum(1 for t in closed if t["r"] < 0)
    gross_win = sum(t["r"] for t in closed if t["r"] > 0)
    gross_loss = abs(sum(t["r"] for t in closed if t["r"] < 0))
    win_rate = round((wins / len(closed)) * 100.0, 1) if closed else 0.0
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (9.99 if gross_win > 0 else 0.0)
    net_r = round(sum(t["r"] for t in closed), 2)

    return {
        "available": True,
        "trades_count": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "net_r": net_r,
        "recent_trades": trades[-8:][::-1],
    }


def update_and_grade_signal_ledger(
    ledger_path: Path,
    primary_sig: Optional[Dict],
    candles_15m: List[Dict],
) -> Dict:
    entries: List[Dict] = []
    if ledger_path.exists():
        try:
            entries = json.loads(ledger_path.read_text(encoding="utf-8"))
        except Exception:
            entries = []

    # Grade any open entries against newer 15m candles
    for item in entries:
        if item.get("status") in ("TP2 WIN", "TP1 BE WIN", "SL LOSS"):
            continue
        future = [c for c in candles_15m if c["t"] > item.get("created_ts", 0)]
        if future:
            out, r_val = _simulate_outcome_with_be(
                future, item["direction"], item["entry"], item["sl"], item["tp1"], item["tp2"]
            )
            item["status"] = out
            item["r"] = round(r_val, 2)

    # Log new high-confluence signal if >= 60% and not deadzone/blackout (deduped by 4h + direction)
    now_ts = int(time.time())
    if primary_sig and primary_sig.get("confidence", 0) >= 60 and "DEADZONE" not in primary_sig.get("status", "") and "BLACKOUT" not in primary_sig.get("status", ""):
        already_logged = any(
            abs(now_ts - e.get("created_ts", 0)) < 14400 and e.get("direction") == primary_sig["direction"]
            and abs(e.get("entry", 0) - primary_sig["entry_price"]) < max(primary_sig["entry_price"] * 0.0014, 5.0)
            for e in entries
        )
        if not already_logged:
            dt_de, tz = to_frankfurt_dt(now_ts)
            entries.append({
                "id": f"sig-{now_ts}",
                "created_ts": now_ts,
                "time": dt_de.strftime("%m-%d %H:%M ") + tz,
                "direction": primary_sig["direction"],
                "setup": primary_sig["entry_source"],
                "confidence": primary_sig["confidence"],
                "entry": primary_sig["entry_price"],
                "sl": primary_sig["stop_loss"],
                "tp1": primary_sig["tp1"],
                "tp2": primary_sig["tp2"],
                "status": "OPEN",
                "r": 0.0,
            })

    entries = entries[-60:]
    try:
        ledger_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception:
        pass

    graded = [e for e in entries if e.get("status") in ("TP2 WIN", "TP1 BE WIN", "SL LOSS")]
    wins = sum(1 for e in graded if e.get("r", 0) > 0)
    win_rate = round((wins / len(graded)) * 100.0, 1) if graded else None
    net_r = round(sum(e.get("r", 0) for e in graded), 2)

    return {
        "total_logged": len(entries),
        "graded_count": len(graded),
        "wins": wins,
        "win_rate_pct": win_rate,
        "net_r": net_r,
        "entries": entries[-10:][::-1],
    }


def analyze_smc_suite(
    candles_15m: List[Dict],
    candles_daily: List[Dict],
    stoxx_15m: List[Dict],
    spx_15m: List[Dict],
    overall_score: int,
    overall_label: str,
    macro_quotes: Optional[List[Dict]] = None,
    candles_1h: Optional[List[Dict]] = None,
    dax_constituents: Optional[List[Dict]] = None,
    catalysts: Optional[List[Dict]] = None,
    ledger_path: Optional[Path] = None,
    instrument: str = "DAX",
) -> Dict:
    killzone = get_killzone_status(instrument=instrument)
    if not candles_15m:
        return {"killzone": killzone, "available": False}

    sh, sl = _find_swings(candles_15m, left=3, right=3)
    fvgs, ifvgs = _detect_fvgs_and_ifvgs(candles_15m)
    trend, events, obs, breakers = _detect_structure_obs_and_breakers(candles_15m, sh, sl, fvgs)
    liquidity = compute_liquidity_and_range(candles_15m, candles_daily, instrument=instrument)
    cur_price = liquidity.get("current_price", candles_15m[-1]["c"])
    ipda = compute_ipda_lookbacks(candles_daily, cur_price)
    po3 = compute_power_of_three(candles_15m, candles_daily, overall_score, instrument=instrument)
    ote, sd_targets = compute_ote_and_sd(candles_15m, sh, sl, trend, fvgs)
    intermarket = compute_intermarket_triad(macro_quotes or [], instrument=instrument)
    base_lbl = "Gold (GC=F)" if instrument == "GOLD" else ("Bitcoin (BTC-USD)" if instrument == "BTC" else "DAX 40")
    peer1_lbl = "Silver (SI=F)" if instrument == "GOLD" else ("Ethereum (ETH-USD)" if instrument == "BTC" else "Euro Stoxx 50")
    smt_stoxx = detect_smt_divergence(candles_15m, stoxx_15m, peer1_lbl, base_name=base_lbl)
    smt_spx = detect_smt_divergence(candles_15m, spx_15m, "S&P 500", base_name=base_lbl)

    atr = _calc_atr_15m(candles_15m, 14)
    adr = compute_adr_metrics(candles_daily, candles_15m)
    blackout = check_news_blackout(catalysts)
    breadth = analyze_dax_breadth(dax_constituents)
    htf_1h = detect_htf_1h_context(candles_1h, cur_price, ipda.get("daily_fvgs", []))
    price_action = detect_eqh_eql_and_sweep_displacement(candles_15m, sh, sl, fvgs, ifvgs, liquidity, atr)

    execution = build_smc_execution_matrix(
        overall_score, overall_label, liquidity, trend, fvgs, ifvgs, breakers, ote, po3, smt_stoxx, smt_spx, killzone
    )
    trade_signals = generate_smc_trade_signals(
        candles_15m, sh, sl, trend, fvgs, ifvgs, obs, breakers,
        liquidity, ipda, po3, ote, sd_targets, smt_stoxx, smt_spx,
        intermarket, killzone, overall_score, overall_label,
        htf_1h=htf_1h, adr=adr, blackout=blackout, breadth=breadth, price_action=price_action,
    )

    walkforward = run_5d_walkforward_backtest(candles_15m)
    l_path = ledger_path or (Path(__file__).resolve().parent / "signal_history.json")
    ledger = update_and_grade_signal_ledger(l_path, trade_signals.get("primary"), candles_15m)

    chart_candles = candles_15m[-90:]
    min_idx = candles_15m.index(chart_candles[0]) if chart_candles else 0

    return {
        "available": True,
        "instrument": instrument,
        "killzone": killzone,
        "structure_trend": trend,
        "structure_events": [e for e in events if e["idx"] >= min_idx],
        "fvgs": fvgs,
        "ifvgs": ifvgs,
        "order_blocks": obs,
        "breakers": breakers,
        "liquidity": liquidity,
        "ipda": ipda,
        "power_of_3": po3,
        "ote": ote,
        "sd_targets": sd_targets,
        "intermarket": intermarket,
        "smt": {"stoxx50": smt_stoxx, "sp500": smt_spx},
        "execution": execution,
        "signals": trade_signals,
        "backtest": walkforward,
        "ledger": ledger,
        "candles_15m": chart_candles,
    }
