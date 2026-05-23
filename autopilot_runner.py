"""
Standalone Auto-Pilot Runner
Runs independently via GitHub Actions every 2 hours.
Reads/writes the same Supabase tables as the Streamlit app.
"""
import os
import requests
import pandas as pd
import ta
import time
import numpy as np
from datetime import datetime, timedelta

# ── Config from env ────────────────────────────────────────────────────────────
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

HEADERS = {"x-cg-demo-api-key": COINGECKO_API_KEY}

# ── Supabase helpers ───────────────────────────────────────────────────────────
def supabase_get(table, row_id):
    try:
        url = SUPABASE_URL + "/rest/v1/" + table + "?id=eq." + row_id + "&select=data"
        res = requests.get(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
        }, timeout=10)
        rows = res.json()
        if rows and len(rows) > 0:
            return rows[0]["data"]
        return None
    except Exception as e:
        print("supabase_get error:", e)
        return None

def supabase_set(table, row_id, data):
    try:
        url = SUPABASE_URL + "/rest/v1/" + table
        requests.post(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }, json={"id": row_id, "data": data}, timeout=10)
    except Exception as e:
        print("supabase_set error:", e)

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"
        }, timeout=10)
    except:
        pass

# ── Coin filtering ─────────────────────────────────────────────────────────────
STABLECOIN_SYMBOLS = {"usdt", "usdc", "dai", "busd", "tusd", "frax", "usdd", "gusd",
                      "usdp", "usdn", "fei", "lusd", "usde", "usdf", "usds", "pyusd",
                      "eurt", "eurc", "eurs", "rain", "usd1", "usdy", "figr_heloc",
                      "buidl", "usdm", "sdai"}

def get_top_coins(limit=100):
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=" + str(limit) + "&page=1"
        res = requests.get(url, headers=HEADERS, timeout=15)
        coins = {}
        for item in res.json():
            cid = item["id"]
            symbol = item["symbol"].lower()
            name_lower = item["name"].lower()
            if symbol in STABLECOIN_SYMBOLS:
                continue
            if any(p in symbol for p in ["usd", "yield", "heloc", "dollar", "stable", "euro"]):
                continue
            if any(p in name_lower for p in ["us dollar", "stable", "yield", "heloc"]):
                continue
            coins[item["name"] + " (" + item["symbol"].upper() + ")"] = cid
        return coins
    except Exception as e:
        print("get_top_coins error:", e)
        return {}

def categorize_coin(coin_id):
    defi = {"chainlink", "uniswap", "aave", "maker", "compound", "curve-dao-token",
            "synthetix-network-token", "pancakeswap-token", "lido-dao", "rocket-pool"}
    layer1 = {"bitcoin", "ethereum", "solana", "binancecoin", "cardano", "avalanche-2",
              "polkadot", "near", "cosmos", "algorand", "tron", "tezos", "fantom"}
    meme = {"dogecoin", "shiba-inu", "pepe", "floki", "bonk", "dogwifcoin", "memecoin"}
    privacy = {"monero", "zcash", "dash"}
    if coin_id in defi: return "DeFi"
    if coin_id in layer1: return "Layer 1"
    if coin_id in meme: return "Memecoin"
    if coin_id in privacy: return "Privacy"
    return "Other"

# ── Analysis ───────────────────────────────────────────────────────────────────
def check_btc_health():
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin"
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json()[0].get("price_change_percentage_24h", 0) or 0
    except:
        return 0

def get_fear_greed():
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        return int(res.json()["data"][0]["value"])
    except:
        return 50

def analyze_coin(coin_id):
    try:
        hist_url = "https://api.coingecko.com/api/v3/coins/" + coin_id + "/market_chart?vs_currency=usd&days=90"
        hist_res = requests.get(hist_url, headers=HEADERS, timeout=10)
        market_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + coin_id
        market_res = requests.get(market_url, headers=HEADERS, timeout=10)
        market_data = market_res.json()[0]
        prices = [p[1] for p in hist_res.json()["prices"]]
        volumes = [v[1] for v in hist_res.json()["total_volumes"]]
        if len(prices) < 20:
            return None
        df = pd.DataFrame({"close": prices, "volume": volumes})
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        macd = ta.trend.MACD(df["close"])
        df["macd_hist"] = macd.macd_diff()
        df["ema9"] = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
        df["ema21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(df["close"], window=min(50, len(df)-1)).ema_indicator()
        df["ema200"] = ta.trend.EMAIndicator(df["close"], window=min(200, len(df)-1)).ema_indicator()
        latest = df.iloc[-1]
        current_price = market_data["current_price"]
        change_24h = market_data["price_change_percentage_24h"] or 0
        avg_volume = df["volume"].mean()
        current_volume = market_data["total_volume"] or 0
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        bull = bear = 0
        if latest["rsi"] < 35: bull += 2
        elif latest["rsi"] > 65: bear += 2
        if latest["macd_hist"] > 0: bull += 1
        else: bear += 1
        if latest["ema9"] > latest["ema21"]: bull += 1
        else: bear += 1
        if latest["ema21"] > latest["ema50"]: bull += 1
        else: bear += 1
        if not pd.isna(latest["ema200"]):
            if current_price > latest["ema200"]: bull += 2
            else: bear += 2
        if volume_ratio > 1.5:
            if change_24h > 0: bull += 2
            else: bear += 2
        elif volume_ratio > 1.1:
            if change_24h > 0: bull += 1
            else: bear += 1
        total = bull + bear
        confidence = int((max(bull, bear) / total) * 100) if total > 0 else 50
        if bull >= 10: signal = "STRONG BUY"
        elif bull >= 7: signal = "BUY"
        elif bear >= 10: signal = "STRONG SELL"
        elif bear >= 7: signal = "SELL"
        else: signal = "HOLD"
        return {
            "price": current_price, "signal": signal, "bull": bull, "bear": bear,
            "confidence": confidence, "rsi": float(latest["rsi"]),
            "volume_ratio": volume_ratio,
        }
    except Exception as e:
        print("analyze error for", coin_id, ":", e)
        return None

# ── Main run ───────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Auto-Pilot Runner started at", datetime.now())
    print("=" * 60)

    cfg = supabase_get("autopilot_config", "main") or {}
    if not cfg.get("enabled"):
        print("Auto-Pilot is DISABLED. Exiting.")
        return

    paper = supabase_get("paper_trades", "main") or {"balance": 10000.0, "trades": [], "positions": {}}
    held = set(paper.get("positions", {}).keys())
    print("Current balance: $" + str(paper["balance"]))
    print("Open positions:", len(held))

    # ── First: check open positions for SL/TP/trailing ────────────────────────
    print("\n--- Checking open positions for SL/TP ---")
    # Pre-fetch coin list for ID lookups
    all_coins = get_top_coins(100)
    positions_to_close = []
    for coin_name_pos, pos in list(paper["positions"].items()):
        coin_id_pos = pos.get("coin_id") or all_coins.get(coin_name_pos)
        if not coin_id_pos:
            print("Skipping", coin_name_pos, "- no coin_id and not in top coins")
            continue
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + coin_id_pos
            res = requests.get(url, headers=HEADERS, timeout=10)
            current_px = res.json()[0]["current_price"]
        except:
            continue
        entry_px = pos["entry_price"]
        sl_price = pos.get("sl_price", entry_px * 0.95)
        tp_price = pos.get("tp_price", entry_px * 1.15)
        trailing_sl = pos.get("trailing_sl", sl_price)
        highest = pos.get("highest_price", entry_px)
        if current_px > highest:
            highest = current_px
            gain = ((current_px - entry_px) / entry_px) * 100
            if gain >= 2:
                new_trail = current_px * 0.95
                if new_trail > trailing_sl:
                    trailing_sl = new_trail
            pos["highest_price"] = highest
            pos["trailing_sl"] = trailing_sl
        active_sl = max(sl_price, trailing_sl)
        if current_px <= active_sl:
            positions_to_close.append((coin_name_pos, current_px, "STOP-LOSS", pos))
        elif current_px >= tp_price:
            positions_to_close.append((coin_name_pos, current_px, "TAKE-PROFIT", pos))
        time.sleep(0.3)

    for coin_name_c, sell_px, reason, pos in positions_to_close:
        sale_value = pos["coins"] * sell_px
        profit_usd = sale_value - pos["cost"]
        profit_pct = (profit_usd / pos["cost"]) * 100
        paper["balance"] += sale_value
        paper["trades"].append({
            "type": "SELL", "coin": coin_name_c, "price": sell_px,
            "amount": sale_value, "coins": pos["coins"],
            "date": str(datetime.now())[:19],
            "profit_usd": profit_usd, "profit_pct": profit_pct,
            "reason": reason, "source": "auto-pilot-bg",
        })
        del paper["positions"][coin_name_c]
        emoji = "✅" if profit_usd >= 0 else "❌"
        msg = "🤖 <b>AUTO-CLOSE: " + reason + " " + emoji + "</b>\nCoin: " + coin_name_c + "\nP&L: " + ("+" if profit_usd >= 0 else "") + "$" + str(round(profit_usd, 2)) + " (" + ("+" if profit_pct >= 0 else "") + str(round(profit_pct, 2)) + "%)"
        send_telegram(msg)
        print("CLOSED:", coin_name_c, reason, "P&L:", profit_usd)
        held.discard(coin_name_c)

    if positions_to_close:
        supabase_set("paper_trades", "main", paper)

    # ── Check filters ─────────────────────────────────────────────────────────
    if cfg.get("btc_filter", True):
        btc_change = check_btc_health()
        if btc_change < cfg.get("btc_threshold", -3.0):
            print("BTC filter active. BTC change:", btc_change)
            send_telegram("🛡️ BTC down " + str(round(btc_change, 2)) + "% — pausing new buys")
            supabase_set("autopilot_config", "main", cfg)
            return

    # Position limit
    if len(held) >= cfg.get("max_open_positions", 8):
        print("Max positions reached")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    trades_today = [t for t in cfg.get("trades_today", []) if t.startswith(today_str)]
    if len(trades_today) >= cfg.get("max_trades_per_day", 5):
        print("Daily limit reached")
        return

    # Losing streak
    cutoff = datetime.now() - timedelta(hours=48)
    recent_sells = []
    for t in paper.get("trades", []):
        if t["type"] == "SELL":
            try:
                if datetime.fromisoformat(t["date"]) >= cutoff:
                    recent_sells.append(t)
            except:
                pass
    sorted_sells = sorted(recent_sells, key=lambda x: x["date"], reverse=True)
    consecutive_losses = 0
    for t in sorted_sells:
        if t["profit_usd"] <= 0:
            consecutive_losses += 1
        else:
            break
    if consecutive_losses >= 3:
        cooldown_start = cfg.get("cooldown_start")
        if cooldown_start:
            hours_passed = (datetime.now() - datetime.fromisoformat(cooldown_start)).total_seconds() / 3600
            if hours_passed < 24:
                print("Cooldown active, hours left:", 24 - hours_passed)
                return
            else:
                cfg["cooldown_start"] = None
        else:
            cfg["cooldown_start"] = datetime.now().isoformat()
            send_telegram("🛑 LOSING STREAK COOLDOWN: " + str(consecutive_losses) + " losses. Pausing 24h.")
            supabase_set("autopilot_config", "main", cfg)
            return

    # Sentiment override
    effective_min_bull = cfg.get("min_bull_score", 10)
    if cfg.get("sentiment_override", True):
        fg = get_fear_greed()
        if fg < 20:
            effective_min_bull = max(effective_min_bull - 2, 7)
        elif fg > 80:
            effective_min_bull = effective_min_bull + 2

    # ── Scan ──────────────────────────────────────────────────────────────────
    print("\n--- Scanning coins ---")
    coins = all_coins
    print("Got", len(coins), "coins to scan")
    results = []
    for coin_name, coin_id in coins.items():
        if coin_name in held:
            continue
        r = analyze_coin(coin_id)
        if r:
            r["coin_name"] = coin_name
            r["coin_id"] = coin_id
            results.append(r)
        time.sleep(0.4)

    # Re-entry blocker
    loss_counts = {}
    for t in paper.get("trades", []):
        if t["type"] == "SELL" and t["profit_usd"] <= 0:
            loss_counts[t["coin"]] = loss_counts.get(t["coin"], 0) + 1
    blocked = {c for c, n in loss_counts.items() if n >= 2}
    print("Blocked coins:", blocked)

    candidates = [r for r in results
                  if r["signal"] == "STRONG BUY"
                  and r["bull"] >= effective_min_bull
                  and r["confidence"] >= cfg.get("min_confidence", 70)
                  and r["coin_name"] not in blocked]
    candidates.sort(key=lambda x: (x["bull"], x["confidence"]), reverse=True)
    print("Qualifying candidates:", len(candidates))

    # Buy
    slots = min(
        cfg.get("max_open_positions", 8) - len(held),
        cfg.get("max_trades_per_day", 5) - len(trades_today),
        len(candidates),
    )
    pos_size = cfg.get("position_size", 500.0)
    stop_loss_pct = 5.0
    take_profit_ratio = 2.0

    bought = []
    for c in candidates[:slots]:
        if paper["balance"] < pos_size:
            break
        entry = c["price"]
        coins_bought = pos_size / entry
        sl_px = entry * (1 - stop_loss_pct / 100)
        tp_px = entry + (entry - sl_px) * take_profit_ratio
        paper["balance"] -= pos_size
        paper["positions"][c["coin_name"]] = {
            "coins": coins_bought, "entry_price": entry, "cost": pos_size,
            "date": str(datetime.now())[:19], "sl_price": sl_px, "tp_price": tp_px,
            "trailing_sl": sl_px, "highest_price": entry, "coin_id": c["coin_id"],
        }
        paper["trades"].append({
            "type": "BUY", "coin": c["coin_name"], "price": entry,
            "amount": pos_size, "coins": coins_bought,
            "date": str(datetime.now())[:19], "profit_usd": 0, "profit_pct": 0,
            "entry_rsi": c.get("rsi", 50), "entry_bull": c["bull"],
            "entry_bear": c["bear"], "entry_volume_ratio": c.get("volume_ratio", 1),
            "entry_category": categorize_coin(c["coin_id"]),
            "source": "auto-pilot-bg",
        })
        bought.append(c["coin_name"])
        cfg.setdefault("trades_today", []).append(str(datetime.now())[:19])
        send_telegram("🤖 <b>AUTO-PILOT BOUGHT</b>\n" + c["coin_name"] + " @ $" + str(round(entry, 4)) + "\nBull: " + str(c["bull"]) + " · " + str(c["confidence"]) + "%\nSL: $" + str(round(sl_px, 4)) + " · TP: $" + str(round(tp_px, 4)))
        print("BOUGHT:", c["coin_name"], "@", entry)

    if bought:
        supabase_set("paper_trades", "main", paper)

    cfg["last_scan"] = datetime.now().isoformat()
    cfg.setdefault("log", []).insert(0, str(datetime.now())[:19] + " · BG scan complete · " + str(len(bought)) + " bought, " + str(len(positions_to_close)) + " closed")
    cfg["log"] = cfg["log"][:30]
    supabase_set("autopilot_config", "main", cfg)
    print("\nDone. Bought:", len(bought), "Closed:", len(positions_to_close))

if __name__ == "__main__":
    main()
