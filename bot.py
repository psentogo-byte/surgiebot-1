import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from smc import to_frankfurt_dt

DEFAULT_CONFIG = {
    "enabled": False,
    "mode": "PAPER",  # "PAPER" or "MT5_BRIDGE"
    "balance": 10000.0,
    "risk_pct": 0.75,
    "min_confidence": 65,
    "min_rr2": 1.8,
    "daily_max_loss_pct": 2.5,
    "max_daily_trades": 4,
    "max_open_positions": 3,
    "trade_dax": True,
    "trade_gold": True,
    "trade_btc": True,
    "dax_symbol": "DE30m",
    "gold_symbol": "XAUUSDm",
    "btc_symbol": "BTCUSDm",
    "dax_max_spread": 4.5,
    "gold_max_spread": 0.65,
    "btc_max_spread": 45.0,
    "dax_pt_value": 1.0,      # $1 per point per 1.0 lot (adjust to broker contract)
    "gold_pt_value": 100.0,   # $100 per $1 move per 1.00 lot XAUUSD (0.01 lot = $1/pt)
    "btc_pt_value": 1.0,      # $1 per $1 move per 1.00 lot BTCUSD (0.01 lot = $0.01/pt)
    "partial_tp1_pct": 50,
    "allow_pending_limits": True,
}


class SmcExecutionBot:
    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or (Path(__file__).resolve().parent / "bot_state.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        today_de = to_frankfurt_dt()[0].strftime("%Y-%m-%d")
        base = {
            "config": dict(DEFAULT_CONFIG),
            "active_orders": [],
            "closed_trades": [],
            "outbox_commands": [],
            "mt5_telemetry": {
                "connected": False,
                "last_heartbeat_ts": 0,
                "account_login": None,
                "server": "",
                "balance": None,
                "equity": None,
                "dax_spread": None,
                "gold_spread": None,
                "btc_spread": None,
                "broker_positions": [],
            },
            "daily_stats": {
                "date": today_de,
                "trades_taken": 0,
                "realized_pnl": 0.0,
                "halted_reason": "",
            },
            "decision_log": [],
            "last_eval_ts": 0,
        }
        if self.state_path.exists():
            try:
                saved = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    cfg = dict(DEFAULT_CONFIG)
                    cfg.update(saved.get("config") or {})
                    base["config"] = cfg
                    base["active_orders"] = saved.get("active_orders") or []
                    base["closed_trades"] = saved.get("closed_trades") or []
                    base["outbox_commands"] = saved.get("outbox_commands") or []
                    if saved.get("mt5_telemetry"):
                        base["mt5_telemetry"].update(saved["mt5_telemetry"])
                    if saved.get("daily_stats"):
                        base["daily_stats"].update(saved["daily_stats"])
                    base["decision_log"] = saved.get("decision_log") or []
                    base["last_eval_ts"] = saved.get("last_eval_ts") or 0
            except Exception:
                pass
        self._roll_daily_stats_if_needed(base)
        return base

    def _save(self):
        try:
            self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _roll_daily_stats_if_needed(self, st: Optional[Dict] = None):
        st = st or self.state
        today_de = to_frankfurt_dt()[0].strftime("%Y-%m-%d")
        if st["daily_stats"].get("date") != today_de:
            st["daily_stats"] = {
                "date": today_de,
                "trades_taken": 0,
                "realized_pnl": 0.0,
                "halted_reason": "",
            }

    def _log(self, instrument: str, action: str, detail: str, tone: str = "neut"):
        dt_de, tz = to_frankfurt_dt()
        entry = {
            "ts": int(time.time()),
            "time": dt_de.strftime("%H:%M:%S ") + tz,
            "instrument": instrument,
            "action": action,
            "detail": detail,
            "tone": tone,
        }
        # Avoid spamming identical consecutive log lines
        logs = self.state["decision_log"]
        if logs and logs[0]["instrument"] == instrument and logs[0]["action"] == action and logs[0]["detail"] == detail:
            logs[0]["ts"] = entry["ts"]
            logs[0]["time"] = entry["time"]
        else:
            logs.insert(0, entry)
            self.state["decision_log"] = logs[:50]

    def _queue_bridge_cmd(self, cmd_type: str, payload: Dict):
        if self.state["config"].get("mode") != "MT5_BRIDGE":
            return
        cmd = {
            "cmd_id": f"cmd-{int(time.time() * 1000)}-{len(self.state['outbox_commands'])}",
            "created_ts": int(time.time()),
            "type": cmd_type,
            **payload,
        }
        self.state["outbox_commands"].append(cmd)
        self.state["outbox_commands"] = self.state["outbox_commands"][-40:]

    def update_config(self, updates: Dict) -> Dict:
        cfg = self.state["config"]
        for k, v in updates.items():
            if k not in DEFAULT_CONFIG:
                continue
            if isinstance(DEFAULT_CONFIG[k], bool):
                cfg[k] = bool(v)
            elif isinstance(DEFAULT_CONFIG[k], int):
                cfg[k] = int(v)
            elif isinstance(DEFAULT_CONFIG[k], float):
                cfg[k] = float(v)
            else:
                cfg[k] = str(v).strip()
        if cfg["mode"] not in ("PAPER", "MT5_BRIDGE"):
            cfg["mode"] = "PAPER"
        cfg["risk_pct"] = max(0.1, min(5.0, cfg["risk_pct"]))
        cfg["min_confidence"] = max(45, min(95, cfg["min_confidence"]))
        cfg["daily_max_loss_pct"] = max(0.5, min(10.0, cfg["daily_max_loss_pct"]))
        cfg["max_daily_trades"] = max(1, min(20, cfg["max_daily_trades"]))
        cfg["max_open_positions"] = max(1, min(6, cfg["max_open_positions"]))
        self._log("SYSTEM", "CONFIG UPDATED", f"Mode={cfg['mode']} | Enabled={cfg['enabled']} | Risk={cfg['risk_pct']}% | MinConf={cfg['min_confidence']}%", "neut")
        self._save()
        return self.get_status()

    def kill_switch(self) -> Dict:
        cfg = self.state["config"]
        cfg["enabled"] = False
        closed_cnt = 0
        for order in list(self.state["active_orders"]):
            if order["status"] == "PENDING":
                self._queue_bridge_cmd("CANCEL_ORDER", {"order_id": order["id"], "symbol": order["broker_symbol"], "ticket": order.get("broker_ticket")})
                self.state["active_orders"].remove(order)
                closed_cnt += 1
            elif order["status"] == "OPEN":
                self._queue_bridge_cmd("CLOSE_POSITION", {"order_id": order["id"], "symbol": order["broker_symbol"], "ticket": order.get("broker_ticket")})
                self._finalize_trade(order, order.get("last_price", order["entry"]), "KILL SWITCH")
                closed_cnt += 1
        self._log("SYSTEM", "KILL SWITCH", f"Bot paused & {closed_cnt} active order(s)/position(s) terminated.", "bear")
        self._save()
        return self.get_status()

    def close_order_by_id(self, order_id: str) -> Dict:
        for order in list(self.state["active_orders"]):
            if order["id"] == order_id:
                if order["status"] == "PENDING":
                    self._queue_bridge_cmd("CANCEL_ORDER", {"order_id": order["id"], "symbol": order["broker_symbol"], "ticket": order.get("broker_ticket")})
                    self.state["active_orders"].remove(order)
                    self._log(order["instrument"], "ORDER CANCELLED", f"Cancelled pending {order['direction']} @ {order['entry']}", "neut")
                else:
                    self._queue_bridge_cmd("CLOSE_POSITION", {"order_id": order["id"], "symbol": order["broker_symbol"], "ticket": order.get("broker_ticket")})
                    self._finalize_trade(order, order.get("last_price", order["entry"]), "MANUAL CLOSE")
                self._save()
                break
        return self.get_status()

    def _effective_balance(self) -> float:
        tel = self.state["mt5_telemetry"]
        if self.state["config"]["mode"] == "MT5_BRIDGE" and tel.get("connected") and tel.get("equity"):
            return float(tel["equity"])
        return float(self.state["config"]["balance"])

    def _finalize_trade(self, order: Dict, exit_price: float, reason: str):
        if order in self.state["active_orders"]:
            self.state["active_orders"].remove(order)
        pt_val = order["pt_value"]
        sign = 1.0 if order["direction"] == "LONG" else -1.0
        rem_pnl = round(sign * (exit_price - order["entry"]) * order["lots"] * pt_val, 2)
        total_pnl = round(order.get("realized_pnl", 0.0) + rem_pnl, 2)
        r_mult = round(total_pnl / max(1.0, order["risk_usd"]), 2)

        self.state["daily_stats"]["realized_pnl"] = round(self.state["daily_stats"]["realized_pnl"] + rem_pnl, 2)
        if self.state["config"]["mode"] == "PAPER":
            self.state["config"]["balance"] = round(self.state["config"]["balance"] + rem_pnl, 2)

        dt_de, tz = to_frankfurt_dt()
        self.state["closed_trades"].insert(0, {
            "id": order["id"],
            "instrument": order["instrument"],
            "broker_symbol": order["broker_symbol"],
            "direction": order["direction"],
            "entry": order["entry"],
            "exit": round(exit_price, 2),
            "orig_sl": order["orig_sl"],
            "tp1": order["tp1"],
            "tp2": order["tp2"],
            "orig_lots": order["orig_lots"],
            "pnl_usd": total_pnl,
            "r_multiple": r_mult,
            "reason": reason,
            "closed_time": dt_de.strftime("%m-%d %H:%M ") + tz,
            "mode": order.get("mode", "PAPER"),
        })
        self.state["closed_trades"] = self.state["closed_trades"][:80]
        tone = "bull" if total_pnl > 0 else ("bear" if total_pnl < 0 else "neut")
        self._log(order["instrument"], f"CLOSED ({reason})", f"{order['direction']} exit {round(exit_price, 2)} | PnL: ${total_pnl:+.2f} ({r_mult:+.2f}R)", tone)

    def manage_live_prices(self, prices: Dict[str, Optional[float]]) -> Dict:
        """Fast price tick for active pending limits and open positions (TP1 partial + BE, TP2, TP3, SL)."""
        self._roll_daily_stats_if_needed()
        changed = False

        for order in list(self.state["active_orders"]):
            inst = order["instrument"]
            px = prices.get(inst)
            if px is None:
                continue
            order["last_price"] = px
            changed = True

            # 1. Check PENDING limit fill
            if order["status"] == "PENDING":
                if order["direction"] == "SHORT":
                    if px >= order["sl"]:
                        self._queue_bridge_cmd("CANCEL_ORDER", {"order_id": order["id"], "symbol": order["broker_symbol"]})
                        self.state["active_orders"].remove(order)
                        self._log(inst, "LIMIT INVALIDATED", f"Price {px} breached SL {order['sl']} before fill.", "neut")
                        continue
                    if px >= order["entry_low"]:
                        order["status"] = "OPEN"
                        order["entry"] = round(px, 2)
                        self._log(inst, "LIMIT FILLED", f"SHORT filled @ {order['entry']} ({order['lots']} lots)", "bear")
                else:
                    if px <= order["sl"]:
                        self._queue_bridge_cmd("CANCEL_ORDER", {"order_id": order["id"], "symbol": order["broker_symbol"]})
                        self.state["active_orders"].remove(order)
                        self._log(inst, "LIMIT INVALIDATED", f"Price {px} breached SL {order['sl']} before fill.", "neut")
                        continue
                    if px <= order["entry_high"]:
                        order["status"] = "OPEN"
                        order["entry"] = round(px, 2)
                        self._log(inst, "LIMIT FILLED", f"LONG filled @ {order['entry']} ({order['lots']} lots)", "bull")
                continue

            # 2. Manage OPEN position
            sign = 1.0 if order["direction"] == "LONG" else -1.0
            pt_val = order["pt_value"]
            order["unrealized_pnl"] = round(sign * (px - order["entry"]) * order["lots"] * pt_val, 2)

            # Check Stop Loss
            if (order["direction"] == "SHORT" and px >= order["sl"]) or (order["direction"] == "LONG" and px <= order["sl"]):
                self._queue_bridge_cmd("CLOSE_POSITION", {"order_id": order["id"], "symbol": order["broker_symbol"], "ticket": order.get("broker_ticket")})
                reason = "BE STOP" if order.get("be_armed") else "SL HIT"
                self._finalize_trade(order, order["sl"], reason)
                continue

            # Check TP1 Partial Close + Move SL to Breakeven
            if not order.get("tp1_hit"):
                hit_tp1 = (order["direction"] == "SHORT" and px <= order["tp1"]) or (order["direction"] == "LONG" and px >= order["tp1"])
                if hit_tp1:
                    order["tp1_hit"] = True
                    order["be_armed"] = True
                    be_buf = 1.5 if inst == "DAX" else (0.30 if inst == "GOLD" else 15.0)
                    new_sl = round(order["entry"] - be_buf if order["direction"] == "SHORT" else order["entry"] + be_buf, 2)
                    order["sl"] = new_sl

                    # Partial close (respect Exness 0.01 lot step)
                    pct = self.state["config"]["partial_tp1_pct"] / 100.0
                    close_lots = round(order["lots"] * pct, 2)
                    if close_lots >= 0.01 and order["lots"] - close_lots >= 0.01:
                        part_pnl = round(sign * (px - order["entry"]) * close_lots * pt_val, 2)
                        order["realized_pnl"] = round(order.get("realized_pnl", 0.0) + part_pnl, 2)
                        order["lots"] = round(order["lots"] - close_lots, 2)
                        self.state["daily_stats"]["realized_pnl"] = round(self.state["daily_stats"]["realized_pnl"] + part_pnl, 2)
                        if self.state["config"]["mode"] == "PAPER":
                            self.state["config"]["balance"] = round(self.state["config"]["balance"] + part_pnl, 2)
                        self._queue_bridge_cmd("PARTIAL_CLOSE", {"order_id": order["id"], "symbol": order["broker_symbol"], "lots": close_lots, "ticket": order.get("broker_ticket")})
                        self._log(inst, "TP1 PARTIAL + BE", f"Closed {close_lots} lots @ {px} (+${part_pnl:.2f}), SL -> BE {new_sl}", "bull")
                    else:
                        self._log(inst, "TP1 HIT -> BE ARMED", f"TP1 {order['tp1']} tagged, SL moved to BE {new_sl}", "bull")

                    self._queue_bridge_cmd("MODIFY_SL", {"order_id": order["id"], "symbol": order["broker_symbol"], "sl": new_sl, "tp": order["tp2"], "ticket": order.get("broker_ticket")})

            # Check TP2 Target
            hit_tp2 = (order["direction"] == "SHORT" and px <= order["tp2"]) or (order["direction"] == "LONG" and px >= order["tp2"])
            if hit_tp2:
                self._queue_bridge_cmd("CLOSE_POSITION", {"order_id": order["id"], "symbol": order["broker_symbol"], "ticket": order.get("broker_ticket")})
                self._finalize_trade(order, order["tp2"], "TP2 TARGET WIN")

        if changed:
            self._save()
        return self.get_status()

    def evaluate_dashboard_and_execute(self, dashboard_data: Dict) -> Dict:
        """Full SMC institutional evaluation on DAX 40, GOLD (GC=F), and BTC (BTC-USD) signals."""
        self._roll_daily_stats_if_needed()
        self.state["last_eval_ts"] = int(time.time())
        cfg = self.state["config"]

        quotes = {q["symbol"]: q["price"] for q in (dashboard_data.get("macro_quotes") or [])}
        prices = {"DAX": quotes.get("^GDAXI"), "GOLD": quotes.get("GC=F"), "BTC": quotes.get("BTC-USD")}
        self.manage_live_prices(prices)

        if not cfg["enabled"]:
            self._save()
            return self.get_status()

        # Daily Max Loss Circuit Breaker
        bal = self._effective_balance()
        max_loss_usd = bal * (cfg["daily_max_loss_pct"] / 100.0)
        if self.state["daily_stats"]["realized_pnl"] <= -max_loss_usd:
            reason = f"Daily Max Loss (-{cfg['daily_max_loss_pct']}%) reached (${self.state['daily_stats']['realized_pnl']:.2f})."
            self.state["daily_stats"]["halted_reason"] = reason
            self._log("SYSTEM", "CIRCUIT BREAKER", reason, "bear")
            self._save()
            return self.get_status()

        if self.state["daily_stats"]["trades_taken"] >= cfg["max_daily_trades"]:
            self.state["daily_stats"]["halted_reason"] = f"Max daily trades ({cfg['max_daily_trades']}) reached."
            self._save()
            return self.get_status()

        instruments = []
        if cfg["trade_dax"]:
            instruments.append(("DAX", cfg["dax_symbol"], cfg["dax_pt_value"], cfg["dax_max_spread"], dashboard_data.get("smc", {}), prices.get("DAX")))
        if cfg["trade_gold"]:
            g_smc = (dashboard_data.get("gold") or {}).get("smc", {})
            instruments.append(("GOLD", cfg["gold_symbol"], cfg["gold_pt_value"], cfg["gold_max_spread"], g_smc, prices.get("GOLD")))
        if cfg.get("trade_btc", True):
            b_smc = (dashboard_data.get("btc") or {}).get("smc", {})
            instruments.append(("BTC", cfg.get("btc_symbol", "BTCUSDm"), cfg.get("btc_pt_value", 1.0), cfg.get("btc_max_spread", 45.0), b_smc, prices.get("BTC")))

        tel = self.state["mt5_telemetry"]
        mt5_alive = (time.time() - (tel.get("last_heartbeat_ts") or 0)) < 35

        for inst, broker_sym, pt_val, max_spread, smc, spot in instruments:
            if not smc or not smc.get("available") or spot is None:
                continue

            signals = smc.get("signals") or {}
            pri = signals.get("primary")
            gates = signals.get("gates") or {}
            kz = smc.get("killzone") or {}
            if not pri:
                continue

            # Cancel any pending limit order if Killzone closed or News Blackout active
            for ord_item in list(self.state["active_orders"]):
                if ord_item["instrument"] == inst and ord_item["status"] == "PENDING":
                    if kz.get("is_deadzone") or (gates.get("blackout") or {}).get("active"):
                        self._queue_bridge_cmd("CANCEL_ORDER", {"order_id": ord_item["id"], "symbol": broker_sym})
                        self.state["active_orders"].remove(ord_item)
                        self._log(inst, "AUTO-CANCELLED LIMIT", "Entered deadzone or news blackout before fill.", "neut")

            # Already has open/pending order on this instrument?
            if any(o["instrument"] == inst for o in self.state["active_orders"]):
                continue
            if len(self.state["active_orders"]) >= cfg["max_open_positions"]:
                continue

            # Institutional Pre-Flight Gates
            if (gates.get("blackout") or {}).get("active"):
                self._log(inst, "BLOCKED (NEWS)", gates["blackout"].get("status", "High-impact news blackout"), "neut")
                continue
            if kz.get("is_deadzone"):
                self._log(inst, "BLOCKED (DEADZONE)", f"{kz.get('phase')} — outside London/NY Killzone", "neut")
                continue
            if (gates.get("adr") or {}).get("exhausted"):
                self._log(inst, "BLOCKED (ADR)", f"ADR {gates['adr'].get('consumed_pct')}% exhausted — no chasing", "neut")
                continue
            if pri["confidence"] < cfg["min_confidence"]:
                self._log(inst, "SKIPPED (CONF)", f"{pri['direction']} {pri['confidence']}% < {cfg['min_confidence']}% floor", "neut")
                continue
            if pri["rr2"] < cfg["min_rr2"]:
                self._log(inst, "SKIPPED (R:R)", f"TP2 R:R {pri['rr2']} < {cfg['min_rr2']} minimum", "neut")
                continue

            # Exness Spread Check when MT5 connected
            cur_spread = tel.get("dax_spread") if inst == "DAX" else (tel.get("gold_spread") if inst == "GOLD" else tel.get("btc_spread"))
            if cfg["mode"] == "MT5_BRIDGE":
                if not mt5_alive:
                    self._log(inst, "MT5 WAITING", "Armed for MT5_BRIDGE — start Exness_SMC_Bridge.mq5 or exness_mt5_worker.py", "neut")
                    continue
                if cur_spread is not None and cur_spread > max_spread:
                    self._log(inst, "BLOCKED (SPREAD)", f"Exness spread {cur_spread} > max {max_spread}", "bear")
                    continue

            # Determine Market vs Limit Order
            is_active_trigger = pri["status"].startswith("ACTIVE")
            is_pending_limit = cfg["allow_pending_limits"] and "PULLBACK" in pri["status"]
            if not is_active_trigger and not is_pending_limit:
                self._log(inst, "WATCHING", f"{pri['direction']} ({pri['confidence']}%) — {pri['status']}", "neut")
                continue

            entry_px = round(spot, 2) if is_active_trigger else pri["entry_price"]
            sl_px = pri["stop_loss"]
            risk_pts = abs(entry_px - sl_px)
            if risk_pts <= 0:
                continue

            risk_usd = round(bal * (cfg["risk_pct"] / 100.0), 2)
            raw_lots = risk_usd / (risk_pts * pt_val)
            lots = round(max(0.01, min(20.0, raw_lots)), 2)

            order_type = "MARKET" if is_active_trigger else "LIMIT"
            order_id = f"bot-{inst.lower()}-{int(time.time())}"
            new_order = {
                "id": order_id,
                "instrument": inst,
                "broker_symbol": broker_sym,
                "direction": pri["direction"],
                "order_type": order_type,
                "status": "OPEN" if is_active_trigger else "PENDING",
                "entry": entry_px,
                "entry_low": pri["entry_low"],
                "entry_high": pri["entry_high"],
                "sl": sl_px,
                "orig_sl": sl_px,
                "tp1": pri["tp1"],
                "tp2": pri["tp2"],
                "tp3": pri["tp3"],
                "lots": lots,
                "orig_lots": lots,
                "pt_value": pt_val,
                "risk_usd": risk_usd,
                "confidence": pri["confidence"],
                "setup_source": pri["entry_source"],
                "tp1_hit": False,
                "be_armed": False,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "last_price": spot,
                "created_ts": int(time.time()),
                "created_time": to_frankfurt_dt()[0].strftime("%m-%d %H:%M ") + to_frankfurt_dt()[1],
                "mode": cfg["mode"],
                "broker_ticket": None,
            }
            self.state["active_orders"].append(new_order)
            self.state["daily_stats"]["trades_taken"] += 1

            cmd_name = "PLACE_MARKET" if is_active_trigger else "PLACE_LIMIT"
            self._queue_bridge_cmd(cmd_name, {
                "order_id": order_id,
                "symbol": broker_sym,
                "direction": pri["direction"],
                "lots": lots,
                "price": entry_px,
                "sl": sl_px,
                "tp1": pri["tp1"],
                "tp2": pri["tp2"],
                "comment": f"SMC_{inst}_{pri['confidence']}pct",
            })
            tone = "bull" if pri["direction"] == "LONG" else "bear"
            self._log(
                inst,
                f"{order_type} {pri['direction']}",
                f"{broker_sym} {lots} lots @ {entry_px} | SL {sl_px} | TP1 {pri['tp1']} | TP2 {pri['tp2']} (${risk_usd} risk)",
                tone,
            )

        self._save()
        return self.get_status()

    def poll_bridge_commands(self, single: bool = False) -> Dict:
        """Called by Exness MT5 EA / Python worker to pop pending execution commands."""
        if single:
            cmds = self.state["outbox_commands"][:1]
            self.state["outbox_commands"] = self.state["outbox_commands"][1:]
        else:
            cmds = list(self.state["outbox_commands"])
            self.state["outbox_commands"] = []
        self._save()
        return {"commands": cmds, "ts": int(time.time())}

    def ingest_mt5_report(self, report: Dict) -> Dict:
        """Called by Exness MT5 EA / Python worker to push account equity, spreads, and fills."""
        tel = self.state["mt5_telemetry"]
        tel["connected"] = True
        tel["last_heartbeat_ts"] = int(time.time())
        if "login" in report:
            tel["account_login"] = report["login"]
        if "server" in report:
            tel["server"] = report["server"]
        if "balance" in report:
            tel["balance"] = report["balance"]
        if "equity" in report:
            tel["equity"] = report["equity"]
        if "dax_spread" in report:
            tel["dax_spread"] = report["dax_spread"]
        if "gold_spread" in report:
            tel["gold_spread"] = report["gold_spread"]
        if "btc_spread" in report:
            tel["btc_spread"] = report["btc_spread"]
        if "fills" in report and isinstance(report["fills"], list):
            for fill in report["fills"]:
                oid = fill.get("order_id")
                for o in self.state["active_orders"]:
                    if o["id"] == oid:
                        if fill.get("ticket"):
                            o["broker_ticket"] = fill["ticket"]
                        if fill.get("filled_price"):
                            o["entry"] = float(fill["filled_price"])
                            o["status"] = "OPEN"
        self._save()
        return {"ok": True, "ts": tel["last_heartbeat_ts"]}

    def get_status(self) -> Dict:
        tel = dict(self.state["mt5_telemetry"])
        tel["connected"] = (time.time() - (tel.get("last_heartbeat_ts") or 0)) < 35
        closed = self.state["closed_trades"]
        wins = sum(1 for c in closed if c["pnl_usd"] > 0)
        tot_closed = len(closed)
        win_rate = round((wins / tot_closed) * 100.0, 1) if tot_closed else None
        net_pnl = round(sum(c["pnl_usd"] for c in closed), 2)
        return {
            "config": self.state["config"],
            "effective_balance": round(self._effective_balance(), 2),
            "mt5_telemetry": tel,
            "daily_stats": self.state["daily_stats"],
            "active_orders": self.state["active_orders"],
            "closed_trades": closed[:20],
            "stats": {
                "closed_count": tot_closed,
                "wins": wins,
                "win_rate_pct": win_rate,
                "net_pnl_usd": net_pnl,
            },
            "decision_log": self.state["decision_log"][:25],
            "last_eval_ts": self.state["last_eval_ts"],
        }


# Ready-to-use Exness MT5 MQL5 Expert Advisor & Python MT5 Worker templates

EXNESS_MQL5_EA = r"""//+------------------------------------------------------------------+
//|                                            Exness_SMC_Bridge.mq5 |
//|   Real-Time Exness MT5 Execution Bridge (DAX, Gold & BTC Bot)    |
//|                                                                  |
//|  REQUIRED MT5 SETUP:                                             |
//|   1. Tools -> Options -> Expert Advisors:                        |
//|      [x] Allow algorithmic trading                               |
//|      [x] Allow WebRequest for listed URL:                        |
//|          http://127.0.0.1:8765                                   |
//|   2. Click "Algo Trading" button in top toolbar (turn GREEN)     |
//|   3. Attach to ANY chart -> Check Experts tab for "MT5 LIVE"     |
//+------------------------------------------------------------------+
#property copyright "DAX, Gold & BTC SMC Sentinel v6"
#property version   "2.00"
#include <Trade\Trade.mqh>

input string InpServerUrl  = "http://127.0.0.1:8765"; // Desktop port (:8765) or Web (:8000)
input string InpDaxSymbol  = "";                      // Leave blank to auto-detect (DE30m/DE30/GER40m)
input string InpGoldSymbol = "";                      // Leave blank to auto-detect (XAUUSDm/XAUUSD)
input string InpBtcSymbol  = "";                      // Leave blank to auto-detect (BTCUSDm/BTCUSD)
input int    InpPollSecs   = 2;
input ulong  InpMagic      = 260601;

CTrade trade;
string gDaxSym = "DE30m";
string gGoldSym = "XAUUSDm";
string gBtcSym = "BTCUSDm";
bool   gConnectedOnce = false;
int    gLastErrCode = -999;

string AutoDetectSymbol(string overrideSym, string candidatesCsv, string fallback) {
   if (StringLen(overrideSym) > 0 && SymbolSelect(overrideSym, true)) {
      if (SymbolInfoDouble(overrideSym, SYMBOL_BID) > 0 || SymbolInfoInteger(overrideSym, SYMBOL_DIGITS) > 0)
         return overrideSym;
   }
   string parts[];
   int n = StringSplit(candidatesCsv, ',', parts);
   for (int i = 0; i < n; i++) {
      string s = parts[i];
      if (SymbolSelect(s, true)) {
         if (SymbolInfoDouble(s, SYMBOL_BID) > 0 || SymbolInfoInteger(s, SYMBOL_DIGITS) > 0)
            return s;
      }
   }
   return fallback;
}

string ResolveOrderSymbol(string reqSym) {
   string u = reqSym;
   StringToUpper(u);
   if (StringFind(u, "DE30") >= 0 || StringFind(u, "DE40") >= 0 || StringFind(u, "GER") >= 0 || StringFind(u, "DAX") >= 0)
      return gDaxSym;
   if (StringFind(u, "XAU") >= 0 || StringFind(u, "GOLD") >= 0)
      return gGoldSym;
   if (StringFind(u, "BTC") >= 0)
      return gBtcSym;
   if (SymbolSelect(reqSym, true)) return reqSym;
   return gGoldSym;
}

int OnInit() {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(30);
   gDaxSym  = AutoDetectSymbol(InpDaxSymbol,  "DE30m,DE30,GER40m,GER40,DE40m,DE40", "DE30m");
   gGoldSym = AutoDetectSymbol(InpGoldSymbol, "XAUUSDm,XAUUSD,XAUUSDc,GOLD", "XAUUSDm");
   gBtcSym  = AutoDetectSymbol(InpBtcSymbol,  "BTCUSDm,BTCUSD,BTCUSDc", "BTCUSDm");

   PrintFormat("Exness_SMC_Bridge v2 initialized | URL=%s | Symbols: DAX=%s, GOLD=%s, BTC=%s",
               InpServerUrl, gDaxSym, gGoldSym, gBtcSym);
   if (!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      Print("WARNING: Top toolbar 'Algo Trading' is OFF! Click Algo Trading to enable orders.");

   EventSetTimer(InpPollSecs);
   SendHeartbeat();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer() {
   SendHeartbeat();
   PollCommands();
}

void ReportWebRequestError(string step, int code) {
   int err = GetLastError();
   if (err == gLastErrCode && code == -1) return;
   gLastErrCode = err;
   gConnectedOnce = false;
   if (err == 4014 || err == 4060) {
      PrintFormat("EXNESS BRIDGE ERROR [%s]: WebRequest blocked (err=%d). FIX: MT5 -> Tools -> Options -> Expert Advisors -> check 'Allow WebRequest for listed URL' and add: %s",
                  step, err, InpServerUrl);
   } else if (err == 5203 || code == -1) {
      PrintFormat("EXNESS BRIDGE ERROR [%s]: Cannot reach Sentinel app at %s (code=%d err=%d). Make sure Start_DAX_Sentinel_Windows.bat is running!",
                  step, InpServerUrl, code, err);
   } else {
      PrintFormat("EXNESS BRIDGE HTTP %d on %s (err=%d)", code, step, err);
   }
}

void SendHeartbeat() {
   double daxSp = SymbolInfoInteger(gDaxSym, SYMBOL_SPREAD) * SymbolInfoDouble(gDaxSym, SYMBOL_POINT);
   double gldSp = SymbolInfoInteger(gGoldSym, SYMBOL_SPREAD) * SymbolInfoDouble(gGoldSym, SYMBOL_POINT);
   double btcSp = SymbolInfoInteger(gBtcSym, SYMBOL_SPREAD) * SymbolInfoDouble(gBtcSym, SYMBOL_POINT);
   string json = StringFormat(
      "{\"login\":%I64d,\"server\":\"%s\",\"balance\":%.2f,\"equity\":%.2f,\"dax_spread\":%.2f,\"gold_spread\":%.2f,\"btc_spread\":%.2f}",
      AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_SERVER),
      AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY), daxSp, gldSp, btcSp
   );
   char post[], res[]; string hdrs;
   StringToCharArray(json, post, 0, StringLen(json));
   ResetLastError();
   int code = WebRequest("POST", InpServerUrl + "/api/bot/mt5-report", "Content-Type: application/json\r\n", 2000, post, res, hdrs);
   if (code == 200) {
      gLastErrCode = -999;
      if (!gConnectedOnce) {
         gConnectedOnce = true;
         PrintFormat("EXNESS BRIDGE CONNECTED! Account=%I64d | Server=%s | Balance=%.2f | Equity=%.2f",
                     AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_SERVER),
                     AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY));
      }
   } else {
      ReportWebRequestError("HEARTBEAT", code);
   }
}

void PollCommands() {
   char post[], res[]; string hdrs;
   ResetLastError();
   int code = WebRequest("GET", InpServerUrl + "/api/bot/bridge/poll?single=1", "", 2000, post, res, hdrs);
   if (code != 200) {
      if (code != -1 || !gConnectedOnce) ReportWebRequestError("POLL", code);
      return;
   }
   string body = CharArrayToString(res);
   if (StringFind(body, "\"PLACE_MARKET\"") >= 0 || StringFind(body, "\"PLACE_LIMIT\"") >= 0 ||
       StringFind(body, "\"MODIFY_SL\"") >= 0 || StringFind(body, "\"PARTIAL_CLOSE\"") >= 0 ||
       StringFind(body, "\"CLOSE_POSITION\"") >= 0 || StringFind(body, "\"CANCEL_ORDER\"") >= 0) {
      Print("Bridge received command: ", body);
      ExecuteBridgePayload(body);
   }
}

string ExtractStr(string src, string key) {
   int p = StringFind(src, "\"" + key + "\":");
   if (p < 0) return "";
   int q1 = StringFind(src, "\"", p + StringLen(key) + 3);
   int q2 = StringFind(src, "\"", q1 + 1);
   if (q1 < 0 || q2 < 0) return "";
   return StringSubstr(src, q1 + 1, q2 - q1 - 1);
}

double ExtractNum(string src, string key) {
   int p = StringFind(src, "\"" + key + "\":");
   if (p < 0) return 0;
   int s = p + StringLen(key) + 3;
   while (s < StringLen(src) && (StringGetCharacter(src, s) == ' ' || StringGetCharacter(src, s) == ':')) s++;
   int e = s;
   while (e < StringLen(src)) {
      ushort ch = StringGetCharacter(src, e);
      if ((ch >= '0' && ch <= '9') || ch == '.' || ch == '-') e++; else break;
   }
   return StringToDouble(StringSubstr(src, s, e - s));
}

void ExecuteBridgePayload(string body) {
   string cmdType = ExtractStr(body, "type");
   string rawSym  = ExtractStr(body, "symbol");
   string sym     = ResolveOrderSymbol(rawSym);
   string dir     = ExtractStr(body, "direction");
   string comment = ExtractStr(body, "order_id");
   double lots    = NormalizeDouble(ExtractNum(body, "lots"), 2);
   double price   = ExtractNum(body, "price");
   double sl      = ExtractNum(body, "sl");
   double tp      = ExtractNum(body, "tp2");
   if (tp <= 0) tp = ExtractNum(body, "tp");

   SymbolSelect(sym, true);
   trade.SetTypeFillingBySymbol(sym);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   sl    = NormalizeDouble(sl, digits);
   tp    = NormalizeDouble(tp, digits);
   price = NormalizeDouble(price, digits);

   bool ok = false;
   if (cmdType == "PLACE_MARKET") {
      ok = (dir == "BUY" || dir == "LONG") ? trade.Buy(lots, sym, 0, sl, tp, comment) : trade.Sell(lots, sym, 0, sl, tp, comment);
   } else if (cmdType == "PLACE_LIMIT") {
      ok = (dir == "BUY" || dir == "LONG") ? trade.BuyLimit(lots, price, sym, sl, tp, ORDER_TIME_DAY, 0, comment) : trade.SellLimit(lots, price, sym, sl, tp, ORDER_TIME_DAY, 0, comment);
   } else if (cmdType == "MODIFY_SL") {
      for (int i = PositionsTotal() - 1; i >= 0; i--) {
         ulong tk = PositionGetTicket(i);
         if (PositionGetString(POSITION_SYMBOL) == sym) ok = trade.PositionModify(tk, sl, tp);
      }
   } else if (cmdType == "PARTIAL_CLOSE") {
      for (int i = PositionsTotal() - 1; i >= 0; i--) {
         ulong tk = PositionGetTicket(i);
         if (PositionGetString(POSITION_SYMBOL) == sym) ok = trade.PositionClosePartial(tk, lots);
      }
   } else if (cmdType == "CLOSE_POSITION") {
      for (int i = PositionsTotal() - 1; i >= 0; i--) {
         ulong tk = PositionGetTicket(i);
         if (PositionGetString(POSITION_SYMBOL) == sym) ok = trade.PositionClose(tk);
      }
   } else if (cmdType == "CANCEL_ORDER") {
      for (int i = OrdersTotal() - 1; i >= 0; i--) {
         ulong tk = OrderGetTicket(i);
         if (OrderGetString(ORDER_SYMBOL) == sym) ok = trade.OrderDelete(tk);
      }
   }
   PrintFormat("Executed %s on %s (raw=%s) -> ok=%s retcode=%d (%s)",
               cmdType, sym, rawSym, ok ? "true" : "false", trade.ResultRetcode(), trade.ResultRetcodeDescription());
}
"""

EXNESS_PYTHON_WORKER = r'''#!/usr/bin/env python3
"""
Standalone Exness MT5 Python Bridge Worker (Windows + Exness MetaTrader 5 Desktop)
Requires: Python 3.10-3.12 (64-bit) + pip install MetaTrader5 requests
Run alongside your logged-in Exness MT5 Terminal.
"""
import sys
import time
import requests
import MetaTrader5 as mt5

SERVER_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
DAX_CANDIDATES = ["DE30m", "DE30", "GER40m", "GER40", "DE40m", "DE40"]
GOLD_CANDIDATES = ["XAUUSDm", "XAUUSD", "XAUUSDc", "GOLD"]
BTC_CANDIDATES = ["BTCUSDm", "BTCUSD", "BTCUSDc"]


def pick_symbol(candidates):
    for s in candidates:
        info = mt5.symbol_info(s)
        if info is not None:
            mt5.symbol_select(s, True)
            return s
    return candidates[0]


def resolve_symbol(req_sym, dax_sym, gold_sym, btc_sym):
    u = (req_sym or "").upper()
    if any(k in u for k in ("DE30", "DE40", "GER", "DAX")):
        return dax_sym
    if any(k in u for k in ("XAU", "GOLD")):
        return gold_sym
    if "BTC" in u:
        return btc_sym
    return req_sym or gold_sym


def filling_mode_for(sym):
    info = mt5.symbol_info(sym)
    if info is not None:
        fm = info.filling_mode
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def main():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    dax_sym = pick_symbol(DAX_CANDIDATES)
    gold_sym = pick_symbol(GOLD_CANDIDATES)
    btc_sym = pick_symbol(BTC_CANDIDATES)
    print(f"Connected to Exness MT5 | Server={SERVER_URL} | DAX={dax_sym} | GOLD={gold_sym} | BTC={btc_sym}")

    try:
        while True:
            acct = mt5.account_info()
            d_tick = mt5.symbol_info_tick(dax_sym)
            g_tick = mt5.symbol_info_tick(gold_sym)
            b_tick = mt5.symbol_info_tick(btc_sym)
            payload = {
                "login": acct.login if acct else None,
                "server": acct.server if acct else "",
                "balance": acct.balance if acct else None,
                "equity": acct.equity if acct else None,
                "dax_spread": round(d_tick.ask - d_tick.bid, 2) if d_tick else None,
                "gold_spread": round(g_tick.ask - g_tick.bid, 2) if g_tick else None,
                "btc_spread": round(b_tick.ask - b_tick.bid, 2) if b_tick else None,
            }
            try:
                requests.post(f"{SERVER_URL}/api/bot/mt5-report", json=payload, timeout=3)
                cmds = requests.get(f"{SERVER_URL}/api/bot/bridge/poll", timeout=3).json().get("commands", [])
                for c in cmds:
                    sym = resolve_symbol(c.get("symbol"), dax_sym, gold_sym, btc_sym)
                    mt5.symbol_select(sym, True)
                    tick = mt5.symbol_info_tick(sym)
                    if not tick:
                        print("No tick for", sym)
                        continue
                    fill_mode = filling_mode_for(sym)
                    ctype = c["type"]
                    if ctype == "PLACE_MARKET":
                        is_buy = c["direction"] == "LONG"
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": sym,
                            "volume": float(c["lots"]),
                            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                            "price": tick.ask if is_buy else tick.bid,
                            "sl": float(c["sl"]),
                            "tp": float(c["tp2"]),
                            "deviation": 30,
                            "comment": c.get("order_id", "SMC_BOT"),
                            "type_filling": fill_mode,
                        }
                        print("MT5 Market:", mt5.order_send(req))
                    elif ctype == "PLACE_LIMIT":
                        is_buy = c["direction"] == "LONG"
                        req = {
                            "action": mt5.TRADE_ACTION_PENDING,
                            "symbol": sym,
                            "volume": float(c["lots"]),
                            "type": mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT,
                            "price": float(c["price"]),
                            "sl": float(c["sl"]),
                            "tp": float(c["tp2"]),
                            "comment": c.get("order_id", "SMC_BOT"),
                            "type_time": mt5.ORDER_TIME_DAY,
                        }
                        print("MT5 Limit:", mt5.order_send(req))
                    elif ctype == "MODIFY_SL":
                        for pos in mt5.positions_get(symbol=sym) or []:
                            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": sym, "sl": float(c["sl"]), "tp": float(c["tp"])})
                    elif ctype in ("PARTIAL_CLOSE", "CLOSE_POSITION"):
                        for pos in mt5.positions_get(symbol=sym) or []:
                            vol = float(c.get("lots", pos.volume)) if ctype == "PARTIAL_CLOSE" else pos.volume
                            is_buy = pos.type == mt5.POSITION_TYPE_BUY
                            mt5.order_send({
                                "action": mt5.TRADE_ACTION_DEAL, "position": pos.ticket, "symbol": sym,
                                "volume": min(vol, pos.volume),
                                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                                "price": tick.bid if is_buy else tick.ask, "deviation": 30,
                                "type_filling": fill_mode,
                            })
                    elif ctype == "CANCEL_ORDER":
                        for od in mt5.orders_get(symbol=sym) or []:
                            mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": od.ticket})
            except Exception as e:
                print("Bridge error:", e)
            time.sleep(2)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
'''
