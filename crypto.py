import streamlit as st
import requests
import pandas as pd
import ta
import time
import numpy as np
import json
import os
from datetime import datetime, timedelta
from binance.client import Client
from binance.exceptions import BinanceAPIException

API_KEY = st.secrets.get("COINGECKO_API_KEY", os.environ.get("COINGECKO_API_KEY", ""))
HEADERS = {"x-cg-demo-api-key": API_KEY}
NEWS_API_KEY = st.secrets.get("GNEWS_API_KEY", os.environ.get("GNEWS_API_KEY", ""))
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", os.environ.get("TELEGRAM_TOKEN", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
BINANCE_API_KEY = st.secrets.get("BINANCE_API_KEY", os.environ.get("BINANCE_API_KEY", ""))
BINANCE_SECRET_KEY = st.secrets.get("BINANCE_SECRET_KEY", os.environ.get("BINANCE_SECRET_KEY", ""))
JOURNAL_FILE = "trade_journal.json"
PAPER_FILE = "paper_trades.json"
TOP_COINS_CACHE_FILE = "top_coins_cache.json"

BULLISH_WORDS = [
    "surge", "surges", "surging", "rally", "rallies", "rallying", "bullish", "bull",
    "gain", "gains", "rise", "rises", "rising", "pump", "pumps", "moon", "mooning",
    "breakout", "breakthrough", "all-time high", "ath", "record", "adopt", "adoption",
    "approve", "approved", "approval", "launch", "partnership", "invest", "buy",
    "positive", "growth", "recover", "recovery", "bounce", "upgrade", "success"
]
BEARISH_WORDS = [
    "crash", "crashes", "crashing", "drop", "drops", "dropping", "dump", "dumps",
    "dumping", "bearish", "bear", "fall", "falls", "falling", "plunge", "plunges",
    "hack", "hacked", "scam", "fraud", "ban", "banned", "banning", "sell", "selling",
    "fear", "panic", "loss", "losses", "down", "decline", "collapse", "warning",
    "lawsuit", "sec", "regulation", "restrict", "negative", "risk", "danger", "fail"
]

# Default 8 coins always available
DEFAULT_COINS = {
    "Bitcoin (BTC)": "bitcoin", "Ethereum (ETH)": "ethereum", "Solana (SOL)": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "Cardano (ADA)": "cardano",
    "Dogecoin (DOGE)": "dogecoin", "Avalanche (AVAX)": "avalanche-2",
}

COIN_KEYWORDS = {
    "bitcoin": "Bitcoin BTC", "ethereum": "Ethereum ETH", "solana": "Solana SOL",
    "binancecoin": "BNB Binance", "ripple": "XRP Ripple", "cardano": "Cardano ADA",
    "dogecoin": "Dogecoin DOGE", "avalanche-2": "Avalanche AVAX",
}

COIN_TO_SYMBOL = {
    "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT",
    "binancecoin": "BNBUSDT", "ripple": "XRPUSDT", "cardano": "ADAUSDT",
    "dogecoin": "DOGEUSDT", "avalanche-2": "AVAXUSDT",
}

STABLECOIN_IDS = {
    "tether", "usd-coin", "dai", "binance-usd", "true-usd", "frax", "usdd",
    "gemini-dollar", "paxos-standard", "neutrino", "fei-usd", "liquity-usd",
    "ethena-usde", "falcon-usd", "usds", "first-digital-usd", "paypal-usd",
    "tether-eurt", "euro-coin", "stasis-eurs", "bridged-usdc-polygon-pos-bridge",
    "usd1-wlfi", "usd1", "ondo-us-dollar-yield", "figure-heloc", "rain",
    "blackrock-usd-institutional-digital-liquidity-fund", "mountain-protocol-usdm",
    "savings-dai", "compound-usdt", "compound-usdc", "aave-usdc", "aave-usdt",
}
STABLECOIN_SYMBOLS = {"usdt", "usdc", "dai", "busd", "tusd", "frax", "usdd", "gusd",
                      "usdp", "usdn", "fei", "lusd", "usde", "usdf", "usds", "pyusd",
                      "eurt", "eurc", "eurs", "rain", "usd1", "usdy", "figr_heloc",
                      "buidl", "usdm", "sdai", "cusdt", "cusdc", "ausdc", "ausdt",
                      "wsteth", "usdtb"}

def get_top_coins(limit=75):
    """Fetch top coins by market cap from CoinGecko, filtering stablecoins. Cache for 1 hour."""
    cache = {}
    if os.path.exists(TOP_COINS_CACHE_FILE):
        try:
            with open(TOP_COINS_CACHE_FILE, "r") as f:
                cache = json.load(f)
            cached_time = datetime.fromisoformat(cache.get("timestamp", "2000-01-01"))
            if datetime.now() - cached_time < timedelta(hours=1):
                return cache.get("coins", DEFAULT_COINS), cache.get("keywords", COIN_KEYWORDS)
        except:
            pass
    try:
        url = ("https://api.coingecko.com/api/v3/coins/markets"
               "?vs_currency=usd&order=market_cap_desc&per_page=" + str(limit) + "&page=1")
        res = requests.get(url, headers=HEADERS, timeout=15)
        data = res.json()
        coins = {}
        keywords = dict(COIN_KEYWORDS)
        for item in data:
            cid = item["id"]
            symbol = item["symbol"].lower()
            name_lower = item["name"].lower()
            if cid in STABLECOIN_IDS or symbol in STABLECOIN_SYMBOLS:
                continue
            # Pattern-based filter: catch any stablecoin/yield token we missed
            stable_patterns = ["usd", "yield", "heloc", "dollar", "stable", "euro", "stsui"]
            if any(p in symbol for p in stable_patterns):
                continue
            if any(p in name_lower for p in ["us dollar", "stable", "yield", "heloc"]):
                continue
            name = item["name"] + " (" + item["symbol"].upper() + ")"
            coins[name] = cid
            if cid not in keywords:
                keywords[cid] = item["name"] + " " + item["symbol"].upper()
        with open(TOP_COINS_CACHE_FILE, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "coins": coins, "keywords": keywords}, f)
        return coins, keywords
    except:
        return DEFAULT_COINS, COIN_KEYWORDS

def get_binance_client():
    try:
        client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY, testnet=True)
        return client
    except:
        return None

def send_telegram(message):
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except:
        return False

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_journal(trades):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(trades, f, indent=2)

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

def supabase_get(table, row_id):
    """Fetch a row from Supabase by id."""
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
    except:
        return None

def supabase_set(table, row_id, data):
    """Upsert a row in Supabase."""
    try:
        url = SUPABASE_URL + "/rest/v1/" + table
        requests.post(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }, json={"id": row_id, "data": data}, timeout=10)
    except:
        pass

def load_paper_trades():
    if SUPABASE_URL and SUPABASE_KEY:
        data = supabase_get("paper_trades", "main")
        if data:
            return data
    if os.path.exists(PAPER_FILE):
        try:
            with open(PAPER_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"balance": 10000.0, "trades": [], "positions": {}}

def save_paper_trades(data):
    if SUPABASE_URL and SUPABASE_KEY:
        supabase_set("paper_trades", "main", data)
    with open(PAPER_FILE, "w") as f:
        json.dump(data, f, indent=2)

def analyze_sentiment(articles):
    if not articles:
        return 0, "Neutral", 0, 0, 0
    bull_count = 0
    bear_count = 0
    for article in articles:
        text = (article.get("title", "") + " " + article.get("description", "")).lower()
        for word in text.split():
            clean = word.strip(".,!?()[]")
            if clean in BULLISH_WORDS: bull_count += 1
            elif clean in BEARISH_WORDS: bear_count += 1
    total = bull_count + bear_count
    if total == 0: return 0, "Neutral", 0, 0, 100
    bull_pct = int((bull_count / total) * 100)
    bear_pct = int((bear_count / total) * 100)
    neutral_pct = max(0, 100 - bull_pct - bear_pct)
    score = (bull_count - bear_count) / total
    label = "Bullish" if score > 0.3 else "Bearish" if score < -0.3 else "Neutral"
    return round(score, 2), label, bull_pct, bear_pct, neutral_pct

def find_support_resistance(prices, window=5, num_levels=3):
    prices_array = np.array(prices)
    support_levels = []
    resistance_levels = []
    for i in range(window, len(prices_array) - window):
        is_support = all(prices_array[i] <= prices_array[i-j] for j in range(1, window+1)) and \
                     all(prices_array[i] <= prices_array[i+j] for j in range(1, window+1))
        is_resistance = all(prices_array[i] >= prices_array[i-j] for j in range(1, window+1)) and \
                        all(prices_array[i] >= prices_array[i+j] for j in range(1, window+1))
        if is_support: support_levels.append(prices_array[i])
        if is_resistance: resistance_levels.append(prices_array[i])
    def cluster_levels(levels, tolerance=0.02):
        if not levels: return []
        levels = sorted(levels)
        clusters = []
        current_cluster = [levels[0]]
        for level in levels[1:]:
            if (level - current_cluster[0]) / current_cluster[0] < tolerance:
                current_cluster.append(level)
            else:
                clusters.append(np.mean(current_cluster))
                current_cluster = [level]
        clusters.append(np.mean(current_cluster))
        return clusters
    support_clusters = cluster_levels(support_levels)
    resistance_clusters = cluster_levels(resistance_levels)
    current_price = prices_array[-1]
    support_below = sorted([s for s in support_clusters if s < current_price], reverse=True)[:num_levels]
    resistance_above = sorted([r for r in resistance_clusters if r > current_price])[:num_levels]
    return support_below, resistance_above

def calculate_atr(prices, period=14):
    prices_array = np.array(prices)
    if len(prices_array) < period + 1: return prices_array[-1] * 0.02
    tr_list = [abs(prices_array[i] - prices_array[i-1]) for i in range(1, len(prices_array))]
    return np.mean(tr_list[-period:])

def calculate_fibonacci(prices):
    high = max(prices)
    low = min(prices)
    diff = high - low
    levels = {
        "0%": high, "23.6%": high - diff * 0.236, "38.2%": high - diff * 0.382,
        "50%": high - diff * 0.5, "61.8% (Golden)": high - diff * 0.618,
        "78.6%": high - diff * 0.786, "100%": low,
    }
    return levels, high, low

def run_backtest(prices, initial_capital=100, stop_loss_pct=5, take_profit_pct=10):
    df = pd.DataFrame({"close": prices})
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    macd = ta.trend.MACD(df["close"])
    df["macd_hist"] = macd.macd_diff()
    df["ema9"] = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
    df["ema21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    boll = ta.volatility.BollingerBands(df["close"])
    df["bb_upper"] = boll.bollinger_hband()
    df["bb_lower"] = boll.bollinger_lband()
    stoch_rsi = ta.momentum.StochRSIIndicator(df["close"])
    df["stoch_rsi"] = stoch_rsi.stochrsi() * 100
    capital = initial_capital
    position = 0
    entry_price = 0
    trades = []
    equity_curve = [initial_capital]
    for i in range(50, len(df)):
        row = df.iloc[i]
        price = row["close"]
        if pd.isna(row["rsi"]) or pd.isna(row["ema50"]) or pd.isna(row["stoch_rsi"]):
            equity_curve.append(capital + (position * price))
            continue
        bull = 0
        bear = 0
        if row["rsi"] < 35: bull += 2
        elif row["rsi"] > 65: bear += 2
        if row["macd_hist"] > 0: bull += 1
        else: bear += 1
        if row["ema9"] > row["ema21"]: bull += 1
        else: bear += 1
        if row["ema21"] > row["ema50"]: bull += 1
        else: bear += 1
        if price < row["bb_lower"]: bull += 1
        elif price > row["bb_upper"]: bear += 1
        if row["stoch_rsi"] < 20: bull += 1
        elif row["stoch_rsi"] > 80: bear += 1
        if position == 0:
            if bull >= 5:
                position = capital / price
                entry_price = price
                capital = 0
                trades.append({"type": "BUY", "price": price, "index": i, "profit_pct": 0})
        else:
            change_pct = ((price - entry_price) / entry_price) * 100
            should_sell = False
            sell_reason = ""
            if change_pct <= -stop_loss_pct: should_sell = True; sell_reason = "STOP-LOSS"
            elif change_pct >= take_profit_pct: should_sell = True; sell_reason = "TAKE-PROFIT"
            elif bear >= 5: should_sell = True; sell_reason = "SELL SIGNAL"
            if should_sell:
                capital = position * price
                trades.append({"type": "SELL", "price": price, "index": i, "profit_pct": change_pct, "reason": sell_reason})
                position = 0
                entry_price = 0
        equity_curve.append(capital + (position * price) if position > 0 else capital)
    if position > 0: capital = position * df.iloc[-1]["close"]
    final_value = capital
    total_return = ((final_value - initial_capital) / initial_capital) * 100
    sell_trades = [t for t in trades if t["type"] == "SELL"]
    winning_trades = [t for t in sell_trades if t["profit_pct"] > 0]
    losing_trades = [t for t in sell_trades if t["profit_pct"] <= 0]
    win_rate = (len(winning_trades) / len(sell_trades) * 100) if sell_trades else 0
    avg_win = np.mean([t["profit_pct"] for t in winning_trades]) if winning_trades else 0
    avg_loss = np.mean([t["profit_pct"] for t in losing_trades]) if losing_trades else 0
    best_trade = max([t["profit_pct"] for t in sell_trades]) if sell_trades else 0
    worst_trade = min([t["profit_pct"] for t in sell_trades]) if sell_trades else 0
    max_drawdown = 0
    peak = initial_capital
    for value in equity_curve:
        if value > peak: peak = value
        drawdown = ((peak - value) / peak) * 100
        if drawdown > max_drawdown: max_drawdown = drawdown
    return {
        "final_value": final_value, "total_return": total_return, "total_trades": len(sell_trades),
        "win_rate": win_rate, "winning_trades": len(winning_trades), "losing_trades": len(losing_trades),
        "avg_win": avg_win, "avg_loss": avg_loss, "best_trade": best_trade, "worst_trade": worst_trade,
        "max_drawdown": max_drawdown, "equity_curve": equity_curve, "trades": trades,
    }

def check_btc_health():
    """Returns BTC's 24h change %. Used as a market filter."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin"
        res = requests.get(url, headers=HEADERS, timeout=10)
        return res.json()[0].get("price_change_percentage_24h", 0) or 0
    except:
        return 0

def get_fear_greed():
    """Returns Fear & Greed Index value (0-100)."""
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        return int(res.json()["data"][0]["value"])
    except:
        return 50

def detect_hot_sectors(scan_results):
    """From scanner results, find which categories have the most STRONG BUY signals."""
    sector_scores = {}
    for r in scan_results:
        if r["signal"] in ("STRONG BUY", "BUY"):
            cat = categorize_coin(r["coin_id"])
            if cat not in sector_scores:
                sector_scores[cat] = {"signals": 0, "total_bull": 0}
            sector_scores[cat]["signals"] += 1
            sector_scores[cat]["total_bull"] += r["bull"]
    return sector_scores

def quick_analyze_short(coin_id):
    """Lightweight 14d analysis just for signal direction. Used for multi-timeframe confirmation."""
    try:
        hist_url = "https://api.coingecko.com/api/v3/coins/" + coin_id + "/market_chart?vs_currency=usd&days=14"
        hist_res = requests.get(hist_url, headers=HEADERS, timeout=10)
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
        latest = df.iloc[-1]
        bull = bear = 0
        if latest["rsi"] < 40: bull += 1
        elif latest["rsi"] > 60: bear += 1
        if latest["macd_hist"] > 0: bull += 1
        else: bear += 1
        if latest["ema9"] > latest["ema21"]: bull += 1
        else: bear += 1
        if bull > bear: return "BULLISH"
        elif bear > bull: return "BEARISH"
        return "NEUTRAL"
    except:
        return None

def quick_analyze(coin_id, days=90, coin_keywords=None):
    if coin_keywords is None:
        coin_keywords = COIN_KEYWORDS
    try:
        hist_url = "https://api.coingecko.com/api/v3/coins/" + coin_id + "/market_chart?vs_currency=usd&days=" + str(days)
        hist_res = requests.get(hist_url, headers=HEADERS, timeout=10)
        hist_data = hist_res.json()
        market_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + coin_id
        market_res = requests.get(market_url, headers=HEADERS, timeout=10)
        market_data = market_res.json()[0]
        time.sleep(0.5)
        prices = [p[1] for p in hist_data["prices"]]
        volumes = [v[1] for v in hist_data["total_volumes"]]
        df = pd.DataFrame({"close": prices, "volume": volumes})
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        macd = ta.trend.MACD(df["close"])
        df["macd_hist"] = macd.macd_diff()
        df["ema9"] = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
        df["ema21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(df["close"], window=min(50, len(df)-1)).ema_indicator()
        df["ema200"] = ta.trend.EMAIndicator(df["close"], window=min(200, len(df)-1)).ema_indicator()
        boll = ta.volatility.BollingerBands(df["close"])
        df["bb_upper"] = boll.bollinger_hband()
        df["bb_lower"] = boll.bollinger_lband()
        stoch_rsi = ta.momentum.StochRSIIndicator(df["close"])
        df["stoch_rsi"] = stoch_rsi.stochrsi() * 100
        df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
        latest = df.iloc[-1]
        current_price = market_data["current_price"]
        change_24h = market_data["price_change_percentage_24h"] or 0
        current_volume = market_data["total_volume"] or 0
        avg_volume = df["volume"].mean()
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        support_levels, resistance_levels = find_support_resistance(prices)
        fib_levels, fib_high, fib_low = calculate_fibonacci(prices)
        try:
            fg_res = requests.get("https://api.alternative.me/fng/", timeout=10)
            fg_value = int(fg_res.json()["data"][0]["value"])
        except:
            fg_value = 50
        keyword = coin_keywords.get(coin_id, coin_id)
        try:
            news_url = "https://gnews.io/api/v4/search?q=" + keyword + "&lang=en&max=5&token=" + NEWS_API_KEY
            news_res = requests.get(news_url, timeout=10)
            news_articles = news_res.json().get("articles", [])
            sentiment_score, sentiment_label, bull_pct, bear_pct, neutral_pct = analyze_sentiment(news_articles)
        except:
            sentiment_score = 0
        bull = 0
        bear = 0
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
        if latest["stoch_rsi"] < 20: bull += 1
        elif latest["stoch_rsi"] > 80: bear += 1
        if current_price > latest["vwap"]: bull += 1
        else: bear += 1
        if current_price < latest["bb_lower"]: bull += 1
        elif current_price > latest["bb_upper"]: bear += 1
        if fg_value < 25: bull += 2
        elif fg_value < 45: bull += 1
        elif fg_value > 75: bear += 2
        elif fg_value > 55: bear += 1
        if volume_ratio > 1.5:
            if change_24h > 0: bull += 2
            else: bear += 2
        elif volume_ratio > 1.1:
            if change_24h > 0: bull += 1
            else: bear += 1
        if sentiment_score > 0.3: bull += 2
        elif sentiment_score > 0.1: bull += 1
        elif sentiment_score < -0.3: bear += 2
        elif sentiment_score < -0.1: bear += 1
        if support_levels:
            d = ((current_price - support_levels[0]) / current_price) * 100
            if d < 3: bull += 2
            elif d < 8: bull += 1
        if resistance_levels:
            d = ((resistance_levels[0] - current_price) / current_price) * 100
            if d < 3: bear += 2
            elif d < 8: bear += 1
        fib_golden = fib_levels["61.8% (Golden)"]
        if abs(current_price - fib_golden) / current_price < 0.02:
            bull += 2
        total = bull + bear
        confidence = int((max(bull, bear) / total) * 100) if total > 0 else 50
        if bull >= 10: signal = "STRONG BUY"
        elif bull >= 7: signal = "BUY"
        elif bear >= 10: signal = "STRONG SELL"
        elif bear >= 7: signal = "SELL"
        else: signal = "HOLD"
        return {
            "price": current_price, "change_24h": change_24h, "signal": signal,
            "bull": bull, "bear": bear, "confidence": confidence,
            "rsi": latest["rsi"], "volume_ratio": volume_ratio,
            "above_vwap": current_price > latest["vwap"], "success": True
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── App setup ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Crypto Signal Analyzer Pro", page_icon="📡", layout="wide")
st.title("📡 Crypto Signal Analyzer Pro")
st.caption("Live · Scanner · TA · Sentiment · Risk Mgmt · Backtest · Telegram · Journal · Paper Trading")

# Load top coins (cached hourly)
with st.spinner("Loading coin list..."):
    COINS, COIN_KEYWORDS_FULL = get_top_coins(50)

st.sidebar.header("⚠️ Risk Settings")
account_balance = st.sidebar.number_input("Account Balance ($)", min_value=10.0, value=1000.0, step=100.0)
risk_per_trade = st.sidebar.slider("Risk per Trade (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
stop_loss_pct = st.sidebar.slider("Stop Loss (%)", min_value=1.0, max_value=15.0, value=5.0, step=0.5)
take_profit_ratio = st.sidebar.slider("Take Profit Ratio (R:R)", min_value=1.0, max_value=5.0, value=2.0, step=0.5)
st.sidebar.divider()
st.sidebar.markdown("**Max risk per trade: $" + str(round(account_balance * risk_per_trade / 100, 2)) + "**")
st.sidebar.divider()
st.sidebar.header("📱 Telegram")
alert_strong_only = st.sidebar.checkbox("Only STRONG signals", value=True)
if st.sidebar.button("🧪 Test Telegram"):
    ok = send_telegram("👋 Hello from your Crypto Signal Analyzer!")
    if ok: st.sidebar.success("✅ Sent!")
    else: st.sidebar.error("❌ Failed")
st.sidebar.divider()
st.sidebar.header("🔬 Backtest Settings")
backtest_capital = st.sidebar.number_input("Starting Capital ($)", min_value=10.0, value=100.0, step=10.0)
backtest_stop_loss = st.sidebar.slider("BT Stop Loss (%)", min_value=1.0, max_value=20.0, value=5.0, step=0.5)
backtest_take_profit = st.sidebar.slider("BT Take Profit (%)", min_value=2.0, max_value=50.0, value=10.0, step=1.0)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔍 Live Analysis", "🔭 Scanner", "🔬 Backtest", "📒 Trade Journal", "🤖 Paper Trading"])

# ── TODAY'S PICKS (Smart Suggestion Card) ──────────────────────────────────────
def categorize_coin(coin_id):
    """Rough category for diversification check."""
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

TRADE_INSIGHTS_FILE = "trade_insights.json"

def generate_trade_insights(trades):
    """Analyze closed trades and generate learning insights."""
    sell_trades = [t for t in trades if t["type"] == "SELL"]
    if len(sell_trades) < 5:
        return None
    insights = {
        "total_trades": len(sell_trades),
        "wins": 0, "losses": 0,
        "category_stats": {},
        "rsi_ranges": {"0-30": {"w": 0, "l": 0}, "30-40": {"w": 0, "l": 0},
                       "40-50": {"w": 0, "l": 0}, "50-60": {"w": 0, "l": 0},
                       "60-70": {"w": 0, "l": 0}, "70-100": {"w": 0, "l": 0}},
        "bull_score_stats": {"7-9": {"w": 0, "l": 0}, "10-12": {"w": 0, "l": 0},
                             "13+": {"w": 0, "l": 0}},
        "volume_stats": {"low": {"w": 0, "l": 0}, "normal": {"w": 0, "l": 0},
                         "high": {"w": 0, "l": 0}},
        "avg_win_pct": 0, "avg_loss_pct": 0,
        "best_trade": None, "worst_trade": None,
        "avoid_categories": [], "prefer_categories": [],
        "avoid_rsi_ranges": [], "prefer_rsi_ranges": [],
        "tips": [],
    }
    win_pcts = []
    loss_pcts = []
    for t in sell_trades:
        is_win = t["profit_usd"] > 0
        if is_win:
            insights["wins"] += 1
            win_pcts.append(t["profit_pct"])
        else:
            insights["losses"] += 1
            loss_pcts.append(t["profit_pct"])
        if insights["best_trade"] is None or t["profit_pct"] > insights["best_trade"]["profit_pct"]:
            insights["best_trade"] = {"coin": t["coin"], "profit_pct": t["profit_pct"], "profit_usd": t["profit_usd"]}
        if insights["worst_trade"] is None or t["profit_pct"] < insights["worst_trade"]["profit_pct"]:
            insights["worst_trade"] = {"coin": t["coin"], "profit_pct": t["profit_pct"], "profit_usd": t["profit_usd"]}
        cat = t.get("entry_category", "Other")
        if cat not in insights["category_stats"]:
            insights["category_stats"][cat] = {"w": 0, "l": 0, "total_pnl": 0}
        if is_win:
            insights["category_stats"][cat]["w"] += 1
        else:
            insights["category_stats"][cat]["l"] += 1
        insights["category_stats"][cat]["total_pnl"] += t["profit_usd"]
        rsi = t.get("entry_rsi", 50)
        if rsi <= 30: rsi_key = "0-30"
        elif rsi <= 40: rsi_key = "30-40"
        elif rsi <= 50: rsi_key = "40-50"
        elif rsi <= 60: rsi_key = "50-60"
        elif rsi <= 70: rsi_key = "60-70"
        else: rsi_key = "70-100"
        if is_win: insights["rsi_ranges"][rsi_key]["w"] += 1
        else: insights["rsi_ranges"][rsi_key]["l"] += 1
        bull = t.get("entry_bull", 10)
        if bull >= 13: bull_key = "13+"
        elif bull >= 10: bull_key = "10-12"
        else: bull_key = "7-9"
        if is_win: insights["bull_score_stats"][bull_key]["w"] += 1
        else: insights["bull_score_stats"][bull_key]["l"] += 1
        vr = t.get("entry_volume_ratio", 1)
        if vr < 0.8: vol_key = "low"
        elif vr < 1.5: vol_key = "normal"
        else: vol_key = "high"
        if is_win: insights["volume_stats"][vol_key]["w"] += 1
        else: insights["volume_stats"][vol_key]["l"] += 1
    insights["win_rate"] = round(insights["wins"] / insights["total_trades"] * 100, 1) if insights["total_trades"] > 0 else 0
    insights["avg_win_pct"] = round(np.mean(win_pcts), 2) if win_pcts else 0
    insights["avg_loss_pct"] = round(np.mean(loss_pcts), 2) if loss_pcts else 0
    for cat, stats in insights["category_stats"].items():
        total = stats["w"] + stats["l"]
        if total >= 3:
            wr = stats["w"] / total * 100
            if wr < 40:
                insights["avoid_categories"].append(cat)
            elif wr >= 60:
                insights["prefer_categories"].append(cat)
    for rsi_key, stats in insights["rsi_ranges"].items():
        total = stats["w"] + stats["l"]
        if total >= 3:
            wr = stats["w"] / total * 100
            if wr < 40:
                insights["avoid_rsi_ranges"].append(rsi_key)
            elif wr >= 60:
                insights["prefer_rsi_ranges"].append(rsi_key)
    if insights["win_rate"] < 50:
        insights["tips"].append("Win rate is below 50%. Consider only taking STRONG BUY signals (bull ≥ 10).")
    if insights["avg_loss_pct"] and abs(insights["avg_loss_pct"]) > abs(insights["avg_win_pct"]):
        insights["tips"].append("Avg loss is bigger than avg win. Tighten stop losses or widen take profit targets.")
    if insights["avoid_categories"]:
        insights["tips"].append("Avoid " + ", ".join(insights["avoid_categories"]) + " coins — your win rate is under 40% there.")
    if insights["prefer_categories"]:
        insights["tips"].append("Focus on " + ", ".join(insights["prefer_categories"]) + " coins — you perform best in that category.")
    if insights["avoid_rsi_ranges"]:
        insights["tips"].append("Avoid entering when RSI is in range " + ", ".join(insights["avoid_rsi_ranges"]) + " — historically loses for you.")
    if insights["prefer_rsi_ranges"]:
        insights["tips"].append("Your best entries are when RSI is in range " + ", ".join(insights["prefer_rsi_ranges"]) + ".")
    high_vol = insights["volume_stats"]["high"]
    low_vol = insights["volume_stats"]["low"]
    if high_vol["w"] + high_vol["l"] >= 3:
        hv_wr = high_vol["w"] / (high_vol["w"] + high_vol["l"]) * 100
        if hv_wr > 65:
            insights["tips"].append("High volume trades win " + str(round(hv_wr)) + "% of the time. Prioritize coins with volume > 1.5x.")
    if low_vol["w"] + low_vol["l"] >= 3:
        lv_wr = low_vol["w"] / (low_vol["w"] + low_vol["l"]) * 100
        if lv_wr < 40:
            insights["tips"].append("Low volume trades lose often. Skip coins with volume < 0.8x average.")
    try:
        if SUPABASE_URL and SUPABASE_KEY:
            supabase_set("trade_insights", "main", insights)
        with open(TRADE_INSIGHTS_FILE, "w") as f:
            json.dump(insights, f)
    except:
        pass
    return insights

def run_diagnostic(trades, positions):
    """Analyze trade history and return prioritized list of issues + recommended fixes."""
    sell_trades = [t for t in trades if t["type"] == "SELL"]
    buy_trades = [t for t in trades if t["type"] == "BUY"]
    issues = []
    if len(sell_trades) < 3:
        return [{
            "severity": "info",
            "title": "Not enough data yet",
            "detail": "Need at least 3 closed trades to diagnose. You have " + str(len(sell_trades)) + ".",
            "fix": "Let auto-pilot run for a few more days."
        }]
    wins = [t for t in sell_trades if t["profit_usd"] > 0]
    losses = [t for t in sell_trades if t["profit_usd"] <= 0]
    win_rate = len(wins) / len(sell_trades) * 100
    avg_win = np.mean([t["profit_pct"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["profit_pct"] for t in losses]) if losses else 0
    total_pnl = sum(t["profit_usd"] for t in sell_trades)
    if win_rate < 40:
        issues.append({
            "severity": "critical",
            "title": "Win rate is critically low (" + str(round(win_rate, 1)) + "%)",
            "detail": "Less than 40% of trades win. The signals aren't reliable enough for current settings.",
            "fix": "Raise min bull score to 12 and min confidence to 75% in Auto-Pilot settings. Or enable Multi-Timeframe confirmation (next feature).",
        })
    elif win_rate < 50:
        issues.append({
            "severity": "warning",
            "title": "Win rate below 50% (" + str(round(win_rate, 1)) + "%)",
            "detail": "Most trades are losing. Signals work but not strongly enough.",
            "fix": "Tighten signal filters: min bull score 11+, min confidence 70%+.",
        })
    if abs(avg_loss) > avg_win * 1.5 and wins and losses:
        issues.append({
            "severity": "critical",
            "title": "Risk/Reward is inverted",
            "detail": "Avg loss (" + str(round(avg_loss, 2)) + "%) is bigger than avg win (+" + str(round(avg_win, 2)) + "%). Even winning 50% of the time = losing money.",
            "fix": "Increase Take Profit ratio to 2.5x or higher. Or tighten Stop Loss to 4%.",
        })
    cat_stats = {}
    for t in sell_trades:
        cat = t.get("entry_category", "Other")
        if cat not in cat_stats:
            cat_stats[cat] = {"w": 0, "l": 0, "pnl": 0}
        if t["profit_usd"] > 0: cat_stats[cat]["w"] += 1
        else: cat_stats[cat]["l"] += 1
        cat_stats[cat]["pnl"] += t["profit_usd"]
    losing_cats = []
    for cat, s in cat_stats.items():
        total = s["w"] + s["l"]
        if total >= 3 and s["w"]/total < 0.35:
            losing_cats.append((cat, round(s["w"]/total * 100, 1), s["pnl"]))
    if losing_cats:
        worst = max(losing_cats, key=lambda x: abs(x[2]))
        issues.append({
            "severity": "warning",
            "title": worst[0] + " coins are killing you",
            "detail": "Win rate on " + worst[0] + ": " + str(worst[1]) + "% · Total P&L from this category: $" + str(round(worst[2], 2)),
            "fix": "Trade Review Engine already deprioritizes this. Consider adding " + worst[0] + " to a hard blacklist.",
        })
    sorted_trades = sorted(sell_trades, key=lambda x: x["date"])
    streak = 0
    max_streak = 0
    for t in sorted_trades:
        if t["profit_usd"] <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    if max_streak >= 4:
        issues.append({
            "severity": "warning",
            "title": "Losing streaks happening (" + str(max_streak) + " in a row)",
            "detail": "Long losing streaks suggest the bot keeps trading through bad market conditions.",
            "fix": "Add Losing Streak Cooldown — pause auto-pilot for 24h after 3 losses in a row.",
        })
    coin_loss_count = {}
    for t in losses:
        coin_loss_count[t["coin"]] = coin_loss_count.get(t["coin"], 0) + 1
    repeat_losers = [(c, n) for c, n in coin_loss_count.items() if n >= 2]
    if repeat_losers:
        worst_repeat = max(repeat_losers, key=lambda x: x[1])
        issues.append({
            "severity": "warning",
            "title": "Bot keeps re-buying losers",
            "detail": "Lost on " + worst_repeat[0] + " " + str(worst_repeat[1]) + " times. Bot doesn't learn coin-level lessons.",
            "fix": "Add a Re-Entry Blocker — don't auto-buy a coin that lost twice.",
        })
    sl_count = len([t for t in losses if t.get("reason") == "STOP-LOSS"])
    if sl_count >= 5 and sl_count / len(sell_trades) > 0.5:
        issues.append({
            "severity": "warning",
            "title": "Stop-losses triggering too often (" + str(sl_count) + " of " + str(len(sell_trades)) + ")",
            "detail": "Over half your closes are SL hits. Either entries are bad or SL is too tight.",
            "fix": "Add Multi-Timeframe confirmation to filter weak entries, OR widen Stop Loss to 6-7%.",
        })
    avg_hold = []
    for t in losses:
        if t.get("reason") == "STOP-LOSS":
            avg_hold.append(1)
    if len(losses) > 0 and len([t for t in losses if t.get("reason") == "STOP-LOSS"]) / max(len(losses),1) > 0.7:
        issues.append({
            "severity": "warning",
            "title": "Losers stop out fast",
            "detail": "Most losses hit SL quickly — suggests entries are timed poorly.",
            "fix": "Add Multi-Timeframe filter (require 14d + 30d both bullish before buying).",
        })
    tp_count = len([t for t in wins if t.get("reason") == "TAKE-PROFIT"])
    if tp_count >= 3 and tp_count / len(wins) > 0.6 and avg_win > 0:
        issues.append({
            "severity": "info",
            "title": "Most winners hit fixed TP",
            "detail": str(tp_count) + " of " + str(len(wins)) + " wins closed at TP. You're leaving money on the table when coins keep running.",
            "fix": "Add Partial Take-Profit — sell 50% at TP1, let rest ride with trailing stop to capture bigger moves.",
        })
    if win_rate > 50 and total_pnl < 0:
        issues.append({
            "severity": "critical",
            "title": "Winning more than losing but still losing money",
            "detail": "Win rate " + str(round(win_rate, 1)) + "% but P&L is " + str(round(total_pnl, 2)) + ". Classic R:R problem.",
            "fix": "Avg win must beat avg loss. Either raise TP ratio or tighten SL.",
        })
    open_count = len(positions)
    if open_count >= 6:
        issues.append({
            "severity": "info",
            "title": "Highly diversified portfolio (" + str(open_count) + " open)",
            "detail": "Wide diversification — small moves on individual coins won't matter much.",
            "fix": "Consider lowering max_open_positions to 5 to concentrate on best signals.",
        })
    if not issues:
        issues.append({
            "severity": "success",
            "title": "No major issues detected!",
            "detail": "Win rate " + str(round(win_rate, 1)) + "%, P&L $" + str(round(total_pnl, 2)) + ". Bot is performing well.",
            "fix": "Keep running. Consider adding partial take-profit to amplify winning trades.",
        })
    severity_order = {"critical": 0, "warning": 1, "info": 2, "success": 3}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 4))
    return issues


    """Re-rank and filter picks based on learned insights."""
    if not insights:
        return picks
    scored_picks = []
    for p in picks:
        score = p["bull"]
        cat = categorize_coin(p["coin_id"])
        if cat in insights.get("avoid_categories", []):
            score -= 5
            p["insight_warning"] = "⚠️ You historically lose on " + cat + " coins"
        if cat in insights.get("prefer_categories", []):
            score += 3
            p["insight_boost"] = "✅ " + cat + " is your best category"
        rsi = p.get("rsi", 50)
        for rng in insights.get("prefer_rsi_ranges", []):
            low, high = map(int, rng.split("-") if "-" in rng else (rng, "100"))
            if low <= rsi <= high:
                score += 2
                p["insight_boost"] = p.get("insight_boost", "") + " · RSI in your winning range"
        for rng in insights.get("avoid_rsi_ranges", []):
            low, high = map(int, rng.split("-") if "-" in rng else (rng, "100"))
            if low <= rsi <= high:
                score -= 3
                p["insight_warning"] = p.get("insight_warning", "") + " · RSI in your losing range"
        if p.get("volume_ratio", 1) > 1.5:
            high_vol = insights.get("volume_stats", {}).get("high", {})
            if high_vol.get("w", 0) + high_vol.get("l", 0) >= 3:
                hv_wr = high_vol["w"] / (high_vol["w"] + high_vol["l"]) * 100
                if hv_wr > 60:
                    score += 2
        p["adjusted_score"] = score
        scored_picks.append(p)
    scored_picks.sort(key=lambda x: x["adjusted_score"], reverse=True)
    return scored_picks

with st.expander("🎯 **Today's Picks** — smart suggestions based on signals", expanded=False):
    st.caption("Click below to scan the top 20 coins and find the best opportunities right now.")
    if st.button("🔍 Find Today's Best Opportunities", type="primary", key="todays_picks_btn"):
        paper_data_pick = load_paper_trades()
        held_coins = set(paper_data_pick.get("positions", {}).keys())
        coin_items = list(COINS.items())
        progress = st.progress(0)
        status = st.empty()
        all_results = []
        for idx, (coin_name_p, coin_id_p) in enumerate(coin_items):
            status.text("Analyzing " + coin_name_p + "... (" + str(idx + 1) + "/" + str(len(coin_items)) + ")")
            progress.progress((idx + 1) / len(coin_items))
            r = quick_analyze(coin_id_p, days=90, coin_keywords=COIN_KEYWORDS_FULL)
            if r.get("success"):
                r["coin_name"] = coin_name_p
                r["coin_id"] = coin_id_p
                all_results.append(r)
            time.sleep(0.4)
        progress.empty()
        status.empty()
        strong_buys = [r for r in all_results if r["signal"] == "STRONG BUY"]
        buys = [r for r in all_results if r["signal"] == "BUY"]
        ranked = sorted(strong_buys, key=lambda x: (x["bull"], x["confidence"]), reverse=True)
        new_picks = [r for r in ranked if r["coin_name"] not in held_coins]
        trade_insights = generate_trade_insights(paper_data_pick.get("trades", []))
        if trade_insights:
            new_picks = apply_insights_to_picks(new_picks, trade_insights)
        st.session_state["picks_results"] = {
            "new_picks": new_picks[:3],
            "all_strong": ranked,
            "buys": buys,
            "held_coins": list(held_coins),
            "scanned_at": datetime.now().strftime("%H:%M"),
            "insights": trade_insights,
        }
    if "picks_results" in st.session_state:
        pr = st.session_state["picks_results"]
        st.caption("Last scanned at " + pr["scanned_at"])
        st.divider()
        if not pr["all_strong"] and not pr["buys"]:
            st.warning("🧘 **No strong signals today.**")
            st.markdown("Market is quiet — patience is part of the strategy. Don't force trades when the system isn't giving you clean setups. Check back this evening or tomorrow.")
        elif not pr["new_picks"] and pr["all_strong"]:
            held_strong = [r for r in pr["all_strong"] if r["coin_name"] in pr["held_coins"]]
            st.info("✅ **You're already in the best opportunities.** No new buys needed.")
            st.markdown("Coins you hold that are showing STRONG BUY:")
            for r in held_strong:
                st.markdown("- **" + r["coin_name"] + "** · " + str(r["bull"]) + " bull · " + str(r["confidence"]) + "% confidence")
        elif pr["new_picks"]:
            st.success("🎯 **Top " + str(len(pr["new_picks"])) + " Picks Today** — ranked by signal strength")
            categories_picked = []
            max_risk = round(account_balance * risk_per_trade / 100, 2)
            position_size = round(max_risk / (stop_loss_pct / 100), 2)
            for idx, r in enumerate(pr["new_picks"], 1):
                cat = categorize_coin(r["coin_id"])
                categories_picked.append(cat)
                entry = r["price"]
                sl = entry * (1 - stop_loss_pct / 100)
                tp = entry + (entry - sl) * take_profit_ratio
                with st.container():
                    st.markdown("### " + str(idx) + ". " + r["coin_name"] + " · " + r["signal"])
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Confidence", str(r["confidence"]) + "%")
                    c2.metric("Bull Score", str(r["bull"]) + " / " + str(r["bull"] + r["bear"]))
                    c3.metric("RSI", str(round(r["rsi"], 1)))
                    c4.metric("Volume", str(round(r["volume_ratio"], 2)) + "x")
                    e1, e2, e3 = st.columns(3)
                    e1.markdown("**Entry:** $" + str(round(entry, 4)))
                    e2.markdown("**Stop Loss:** $" + str(round(sl, 4)) + " (-" + str(stop_loss_pct) + "%)")
                    e3.markdown("**Take Profit:** $" + str(round(tp, 4)) + " (+" + str(round(stop_loss_pct * take_profit_ratio, 1)) + "%)")
                    st.markdown("💰 **Suggested position size:** $" + str(position_size) + " (risks $" + str(max_risk) + " at -" + str(stop_loss_pct) + "% SL) · Category: " + cat)
                    if r.get("insight_boost"):
                        st.success("🧠 " + r["insight_boost"])
                    if r.get("insight_warning"):
                        st.warning("🧠 " + r["insight_warning"])
                    st.divider()
            if len(set(categories_picked)) == 1 and len(categories_picked) > 1:
                st.warning("⚠️ **Diversification warning:** All " + str(len(categories_picked)) + " picks are " + categories_picked[0] + " coins. They tend to move together — if one drops, they all probably will. Consider mixing categories.")
            elif "Memecoin" in categories_picked and categories_picked.count("Memecoin") >= 2:
                st.warning("⚠️ Multiple memecoins in your picks — these are extra volatile. Size down or skip one.")
            if pr["held_coins"]:
                st.caption("Already holding: " + ", ".join(pr["held_coins"]) + " — these were skipped from suggestions.")
        elif pr["buys"] and not pr["all_strong"]:
            st.info("📊 No STRONG BUY signals, but a few BUY signals exist. Consider waiting for stronger setups or use smaller position sizes.")
            for r in sorted(pr["buys"], key=lambda x: x["bull"], reverse=True)[:3]:
                st.markdown("- **" + r["coin_name"] + "** · " + str(r["bull"]) + " bull · " + str(r["confidence"]) + "% confidence · RSI " + str(round(r["rsi"], 1)))
        if pr.get("insights"):
            ins = pr["insights"]
            st.divider()
            st.markdown("### 🧠 What I've Learned From Your Trades")
            st.caption("Based on " + str(ins["total_trades"]) + " closed trades")
            il1, il2, il3, il4 = st.columns(4)
            il1.metric("Win Rate", str(ins["win_rate"]) + "%")
            il2.metric("Avg Win", "+" + str(ins["avg_win_pct"]) + "%")
            il3.metric("Avg Loss", str(ins["avg_loss_pct"]) + "%")
            il4.metric("W / L", str(ins["wins"]) + " / " + str(ins["losses"]))
            if ins.get("best_trade"):
                bt = ins["best_trade"]
                st.success("🏆 Best trade: **" + bt["coin"] + "** · +" + str(round(bt["profit_pct"], 2)) + "% (+$" + str(round(bt["profit_usd"], 2)) + ")")
            if ins.get("worst_trade"):
                wt = ins["worst_trade"]
                st.error("💀 Worst trade: **" + wt["coin"] + "** · " + str(round(wt["profit_pct"], 2)) + "% ($" + str(round(wt["profit_usd"], 2)) + ")")
            if ins.get("category_stats"):
                st.markdown("**Performance by Category:**")
                for cat, stats in ins["category_stats"].items():
                    total = stats["w"] + stats["l"]
                    wr = round(stats["w"] / total * 100, 1) if total > 0 else 0
                    emoji = "✅" if wr >= 60 else "⚠️" if wr < 40 else "➖"
                    st.markdown(emoji + " **" + cat + "** — " + str(total) + " trades · " + str(wr) + "% win rate · P&L: " + ("+" if stats["total_pnl"] >= 0 else "") + "$" + str(round(stats["total_pnl"], 2)))
            if ins.get("tips"):
                st.markdown("**💡 Tips Based on Your History:**")
                for tip in ins["tips"]:
                    st.info("🧠 " + tip)

st.divider()

# ── TAB 1: Live Analysis ───────────────────────────────────────────────────────
with tab1:
    col1, col2 = st.columns([2, 1])
    with col1:
        coin_name = st.selectbox("Select Coin", list(COINS.keys()), key="live_coin")
    with col2:
        days = st.selectbox("Timeframe", [7, 14, 30, 90], index=1, key="live_days")

    if st.button("Analyze", type="primary", key="analyze_btn"):
        coin_id = COINS[coin_name]
        with st.spinner("Fetching live data..."):
            try:
                market_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + coin_id
                market_res = requests.get(market_url, headers=HEADERS, timeout=10)
                market_data = market_res.json()[0]
                time.sleep(1)
                hist_url = "https://api.coingecko.com/api/v3/coins/" + coin_id + "/market_chart?vs_currency=usd&days=" + str(days)
                hist_res = requests.get(hist_url, headers=HEADERS, timeout=10)
                hist_data = hist_res.json()
                fg_res = requests.get("https://api.alternative.me/fng/", timeout=10)
                fg_data = fg_res.json()
                fg_value = int(fg_data["data"][0]["value"])
                fg_label = fg_data["data"][0]["value_classification"]
                keyword = COIN_KEYWORDS_FULL.get(coin_id, coin_name)
                news_url = "https://gnews.io/api/v4/search?q=" + keyword + "&lang=en&max=10&token=" + NEWS_API_KEY
                news_res = requests.get(news_url, timeout=10)
                news_data = news_res.json()
                news_articles = news_data.get("articles", [])
                sentiment_score, sentiment_label, bull_pct, bear_pct, neutral_pct = analyze_sentiment(news_articles)
                prices = [p[1] for p in hist_data["prices"]]
                volumes = [v[1] for v in hist_data["total_volumes"]]
                support_levels, resistance_levels = find_support_resistance(prices)
                atr = calculate_atr(prices)
                fib_levels, fib_high, fib_low = calculate_fibonacci(prices)
                df = pd.DataFrame({"close": prices, "volume": volumes})
                df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
                macd = ta.trend.MACD(df["close"])
                df["macd_hist"] = macd.macd_diff()
                df["ema9"] = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
                df["ema21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
                df["ema50"] = ta.trend.EMAIndicator(df["close"], window=min(50, len(df)-1)).ema_indicator()
                df["ema200"] = ta.trend.EMAIndicator(df["close"], window=min(200, len(df)-1)).ema_indicator()
                boll = ta.volatility.BollingerBands(df["close"])
                df["bb_upper"] = boll.bollinger_hband()
                df["bb_lower"] = boll.bollinger_lband()
                stoch_rsi = ta.momentum.StochRSIIndicator(df["close"])
                df["stoch_rsi"] = stoch_rsi.stochrsi() * 100
                df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
                latest = df.iloc[-1]
                current_price = market_data["current_price"]
                change_24h = market_data["price_change_percentage_24h"]
                current_volume = market_data["total_volume"]
                avg_volume = df["volume"].mean()
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
                bull = 0
                bear = 0
                reasons = []
                if latest["rsi"] < 35: bull += 2; reasons.append("RSI oversold")
                elif latest["rsi"] > 65: bear += 2; reasons.append("RSI overbought")
                else: reasons.append("RSI neutral")
                if latest["macd_hist"] > 0: bull += 1; reasons.append("MACD bullish")
                else: bear += 1; reasons.append("MACD bearish")
                if latest["ema9"] > latest["ema21"]: bull += 1; reasons.append("EMA9 > EMA21")
                else: bear += 1; reasons.append("EMA9 < EMA21")
                if latest["ema21"] > latest["ema50"]: bull += 1; reasons.append("EMA21 > EMA50")
                else: bear += 1; reasons.append("EMA21 < EMA50")
                if not pd.isna(latest["ema200"]):
                    if current_price > latest["ema200"]: bull += 2; reasons.append("Above EMA200 (long-term bull)")
                    else: bear += 2; reasons.append("Below EMA200 (long-term bear)")
                if latest["stoch_rsi"] < 20: bull += 1; reasons.append("Stoch RSI oversold")
                elif latest["stoch_rsi"] > 80: bear += 1; reasons.append("Stoch RSI overbought")
                if current_price > latest["vwap"]: bull += 1; reasons.append("Above VWAP")
                else: bear += 1; reasons.append("Below VWAP")
                if current_price < latest["bb_lower"]: bull += 1; reasons.append("Below Bollinger lower")
                elif current_price > latest["bb_upper"]: bear += 1; reasons.append("Above Bollinger upper")
                if fg_value < 25: bull += 2; reasons.append("Extreme Fear")
                elif fg_value < 45: bull += 1; reasons.append("Fear")
                elif fg_value > 75: bear += 2; reasons.append("Extreme Greed")
                elif fg_value > 55: bear += 1; reasons.append("Greed")
                if volume_ratio > 1.5:
                    if change_24h > 0: bull += 2; reasons.append("Very high volume rising")
                    else: bear += 2; reasons.append("Very high volume falling")
                elif volume_ratio > 1.1:
                    if change_24h > 0: bull += 1; reasons.append("Above avg volume rising")
                    else: bear += 1; reasons.append("Above avg volume falling")
                if sentiment_score > 0.3: bull += 2; reasons.append("News strongly bullish")
                elif sentiment_score > 0.1: bull += 1; reasons.append("News slightly bullish")
                elif sentiment_score < -0.3: bear += 2; reasons.append("News strongly bearish")
                elif sentiment_score < -0.1: bear += 1; reasons.append("News slightly bearish")
                if support_levels:
                    d = ((current_price - support_levels[0]) / current_price) * 100
                    if d < 3: bull += 2; reasons.append("Very close to support")
                    elif d < 8: bull += 1; reasons.append("Near support")
                if resistance_levels:
                    d = ((resistance_levels[0] - current_price) / current_price) * 100
                    if d < 3: bear += 2; reasons.append("Very close to resistance")
                    elif d < 8: bear += 1; reasons.append("Approaching resistance")
                fib_golden = fib_levels["61.8% (Golden)"]
                if abs(current_price - fib_golden) / current_price < 0.02:
                    bull += 2; reasons.append("At Fibonacci Golden Zone!")
                total = bull + bear
                if total == 0: total = 1
                confidence = int((max(bull, bear) / total) * 100)
                if bull >= 10: signal = "STRONG BUY"
                elif bull >= 7: signal = "BUY"
                elif bear >= 10: signal = "STRONG SELL"
                elif bear >= 7: signal = "SELL"
                else: signal = "HOLD"
                entry_price = current_price
                if "BUY" in signal:
                    sl_price = entry_price * (1 - stop_loss_pct / 100)
                    tp_price = entry_price + (entry_price - sl_price) * take_profit_ratio
                elif "SELL" in signal:
                    sl_price = entry_price * (1 + stop_loss_pct / 100)
                    tp_price = entry_price - (sl_price - entry_price) * take_profit_ratio
                else:
                    sl_price = entry_price * (1 - stop_loss_pct / 100)
                    tp_price = entry_price * (1 + stop_loss_pct * take_profit_ratio / 100)
                risk_amount = account_balance * risk_per_trade / 100
                price_risk = abs(entry_price - sl_price)
                position_size_coins = risk_amount / price_risk if price_risk > 0 else 0
                position_size_usd_capped = min(position_size_coins * entry_price, account_balance * 0.5)
                should_alert = ("STRONG" in signal) if alert_strong_only else (signal != "HOLD")
                if should_alert:
                    emoji = "🚀" if "BUY" in signal else "💀"
                    msg = emoji + " <b>" + signal + " ALERT</b>\n\n"
                    msg += "Coin: <b>" + coin_name + "</b>\n"
                    msg += "Price: <b>$" + str(round(current_price, 4)) + "</b>\n"
                    msg += "24h: " + str(round(change_24h, 2)) + "%\n"
                    msg += "Confidence: " + str(confidence) + "%\n"
                    msg += "Entry: $" + str(round(entry_price, 4)) + "\n"
                    msg += "Stop Loss: $" + str(round(sl_price, 4)) + "\n"
                    msg += "Take Profit: $" + str(round(tp_price, 4)) + "\n\n"
                    for r in reasons[:5]: msg += "- " + r + "\n"
                    msg += "\n⚠️ Not financial advice."
                    sent = send_telegram(msg)
                    if sent: st.success("📱 Telegram alert sent!")
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Current Price", "$" + str(round(current_price, 4)), str(round(change_24h, 2)) + "% (24h)")
                c2.metric("24h High", "$" + str(round(market_data["high_24h"], 4)))
                c3.metric("24h Low", "$" + str(round(market_data["low_24h"], 4)))
                st.divider()
                if "STRONG BUY" in signal: st.success("## 🚀 Signal: STRONG BUY")
                elif "BUY" in signal: st.success("## Signal: BUY")
                elif "STRONG SELL" in signal: st.error("## 💀 Signal: STRONG SELL")
                elif "SELL" in signal: st.error("## Signal: SELL")
                else: st.warning("## Signal: HOLD")
                st.write("Confidence: " + str(confidence) + "% · Bull: " + str(bull) + " · Bear: " + str(bear))
                st.divider()
                st.subheader("🛡️ Risk Management")
                rm1, rm2, rm3 = st.columns(3)
                rm1.metric("📍 Entry", "$" + str(round(entry_price, 4)))
                rm2.metric("🛑 Stop Loss", "$" + str(round(sl_price, 4)))
                rm3.metric("🎯 Take Profit", "$" + str(round(tp_price, 4)))
                ps1, ps2, ps3 = st.columns(3)
                ps1.metric("💰 Invest", "$" + str(round(position_size_usd_capped, 2)))
                ps2.metric("🪙 Coins", str(round(position_size_coins, 6)))
                ps3.metric("⚠️ Max Risk", "$" + str(round(risk_amount, 2)))
                st.divider()
                st.subheader("📊 Technical Indicators")
                i1, i2, i3, i4 = st.columns(4)
                rsi_val = round(latest["rsi"], 1)
                rsi_label = " 🟢 Oversold" if rsi_val < 35 else " 🔴 Overbought" if rsi_val > 65 else " ⚪ Neutral"
                i1.metric("RSI (14)", str(rsi_val) + rsi_label)
                macd_val = round(latest["macd_hist"], 4)
                i2.metric("MACD Histogram", str(macd_val), "Bullish" if macd_val > 0 else "Bearish")
                stoch_val = round(latest["stoch_rsi"], 1)
                stoch_label = "Oversold" if stoch_val < 20 else "Overbought" if stoch_val > 80 else "Neutral"
                i3.metric("Stoch RSI", str(stoch_val), stoch_label)
                vol_label = "High" if volume_ratio > 1.5 else "Normal" if volume_ratio > 0.8 else "Low"
                i4.metric("Volume Ratio", str(round(volume_ratio, 2)) + "x", vol_label)
                i5, i6, i7, i8 = st.columns(4)
                i5.metric("VWAP", "$" + str(round(latest["vwap"], 4)), "Above" if current_price > latest["vwap"] else "Below")
                i6.metric("Bollinger Upper", "$" + str(round(latest["bb_upper"], 4)))
                i7.metric("Bollinger Lower", "$" + str(round(latest["bb_lower"], 4)))
                i8.metric("ATR (Volatility)", "$" + str(round(atr, 4)))
                st.divider()
                st.subheader("📈 Moving Averages")
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("EMA 9", "$" + str(round(latest["ema9"], 4)), "↑" if current_price > latest["ema9"] else "↓")
                e2.metric("EMA 21", "$" + str(round(latest["ema21"], 4)), "↑" if current_price > latest["ema21"] else "↓")
                e3.metric("EMA 50", "$" + str(round(latest["ema50"], 4)), "↑" if current_price > latest["ema50"] else "↓")
                ema200_val = latest["ema200"] if not pd.isna(latest["ema200"]) else None
                if ema200_val:
                    e4.metric("EMA 200", "$" + str(round(ema200_val, 4)), "↑" if current_price > ema200_val else "↓")
                else:
                    e4.metric("EMA 200", "Need more data")
                if not pd.isna(latest["ema200"]) and latest["ema9"] > latest["ema21"] > latest["ema50"] > latest["ema200"]:
                    st.success("🏆 Perfect Bull Alignment: EMA9 > EMA21 > EMA50 > EMA200")
                elif not pd.isna(latest["ema200"]) and latest["ema9"] < latest["ema21"] < latest["ema50"] < latest["ema200"]:
                    st.error("💀 Perfect Bear Alignment: EMA9 < EMA21 < EMA50 < EMA200")
                st.divider()
                st.subheader("📐 Fibonacci Levels")
                fib_cols = st.columns(len(fib_levels))
                for idx, (level_name, level_price) in enumerate(fib_levels.items()):
                    dist = round(((current_price - level_price) / level_price) * 100, 1)
                    fib_cols[idx].metric(level_name, "$" + str(round(level_price, 4)), str(dist) + "%")
                st.divider()
                st.subheader("🎯 Support & Resistance")
                if support_levels or resistance_levels:
                    sr1, sr2 = st.columns(2)
                    with sr1:
                        st.markdown("**🟢 Support Levels**")
                        for s in support_levels:
                            dist = round(((current_price - s) / current_price) * 100, 2)
                            st.write("$" + str(round(s, 4)) + " (" + str(dist) + "% below)")
                    with sr2:
                        st.markdown("**🔴 Resistance Levels**")
                        for r in resistance_levels:
                            dist = round(((r - current_price) / current_price) * 100, 2)
                            st.write("$" + str(round(r, 4)) + " (" + str(dist) + "% above)")
                st.divider()
                st.subheader("😱 Fear & Greed Index")
                fg1, fg2 = st.columns(2)
                fg1.metric("Score", str(fg_value) + "/100", fg_label)
                if fg_value < 25: fg2.markdown("🟢 **EXTREME FEAR** — Potential buying opportunity")
                elif fg_value < 45: fg2.markdown("🟡 **FEAR** — Market uncertain")
                elif fg_value > 75: fg2.markdown("🔴 **EXTREME GREED** — Potential sell opportunity")
                elif fg_value > 55: fg2.markdown("🟠 **GREED** — Exercise caution")
                else: fg2.markdown("⚪ **NEUTRAL** — Market balanced")
                st.divider()
                st.subheader("📰 News & Sentiment")
                ns1, ns2, ns3 = st.columns(3)
                ns1.metric("Sentiment", sentiment_label)
                ns2.metric("Bullish Words", str(bull_pct) + "%")
                ns3.metric("Bearish Words", str(bear_pct) + "%")
                if news_articles:
                    for article in news_articles[:5]:
                        st.markdown("**" + article.get("title", "No title") + "**")
                        st.caption(article.get("description", "")[:200])
                        st.caption("Source: " + article.get("source", {}).get("name", "Unknown") + " · " + article.get("publishedAt", "")[:10])
                        st.divider()
                st.subheader("📋 Signal Reasons")
                for r in reasons:
                    st.write("• " + r)
                import plotly.graph_objects as go
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=list(range(len(prices))), y=prices, name="Price", line=dict(color="white", width=2)))
                ema9_list = df["ema9"].tolist()
                ema21_list = df["ema21"].tolist()
                ema50_list = df["ema50"].tolist()
                vwap_list = df["vwap"].tolist()
                fig.add_trace(go.Scatter(x=list(range(len(ema9_list))), y=ema9_list, name="EMA9", line=dict(color="cyan", width=1)))
                fig.add_trace(go.Scatter(x=list(range(len(ema21_list))), y=ema21_list, name="EMA21", line=dict(color="orange", width=1)))
                fig.add_trace(go.Scatter(x=list(range(len(ema50_list))), y=ema50_list, name="EMA50", line=dict(color="yellow", width=1)))
                fig.add_trace(go.Scatter(x=list(range(len(vwap_list))), y=vwap_list, name="VWAP", line=dict(color="purple", width=1, dash="dash")))
                fig.update_layout(title=coin_name + " — Price Chart", template="plotly_dark", height=400)
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error("Error: " + str(e))

# ── TAB 2: Scanner ─────────────────────────────────────────────────────────────
with tab2:
    st.markdown("### 🔭 Market Scanner")

    # Scanner coin selection
    sc_col1, sc_col2 = st.columns([2, 1])
    with sc_col1:
        all_coin_names = list(COINS.keys())
        default_selection = [c for c in list(DEFAULT_COINS.keys()) if c in all_coin_names]
        scanner_coins_selected = st.multiselect(
            "Select coins to scan (default = top 8)",
            all_coin_names,
            default=default_selection,
            key="scanner_coin_select"
        )
    with sc_col2:
        scanner_days = st.selectbox("Scanner Timeframe", [7, 14, 30], index=1, key="scanner_days")

    st.divider()

    # ── Auto-scanner timer ────────────────────────────────────────────────────
    st.subheader("⏱️ Auto-Scanner")
    auto_col1, auto_col2, auto_col3 = st.columns(3)
    with auto_col1:
        auto_interval = st.selectbox(
            "Scan every",
            [5, 10, 15, 30, 60],
            index=2,
            format_func=lambda x: str(x) + " minutes",
            key="auto_interval"
        )
    with auto_col2:
        auto_enabled = st.toggle("Enable Auto-Scan", value=False, key="auto_enabled")
    with auto_col3:
        if "last_auto_scan" in st.session_state and st.session_state.last_auto_scan:
            last_scan_str = st.session_state.last_auto_scan.strftime("%H:%M:%S")
            next_scan_dt = st.session_state.last_auto_scan + timedelta(minutes=auto_interval)
            now = datetime.now()
            secs_left = max(0, int((next_scan_dt - now).total_seconds()))
            mins_left = secs_left // 60
            secs_rem = secs_left % 60
            st.metric("Next scan in", str(mins_left) + "m " + str(secs_rem) + "s")
            st.caption("Last scan: " + last_scan_str)
        else:
            st.metric("Next scan in", "—")
            st.caption("Auto-scan not started yet")

    # Check if auto-scan should fire
    should_auto_scan = False
    if auto_enabled:
        if "last_auto_scan" not in st.session_state or st.session_state.last_auto_scan is None:
            should_auto_scan = True
        else:
            elapsed = (datetime.now() - st.session_state.last_auto_scan).total_seconds()
            if elapsed >= auto_interval * 60:
                should_auto_scan = True

    manual_scan = st.button("🔍 Scan Now", type="primary", key="scan_btn")

    if manual_scan or should_auto_scan:
        coins_to_scan = scanner_coins_selected if scanner_coins_selected else list(DEFAULT_COINS.keys())[:8]
        scan_ids = {name: COINS[name] for name in coins_to_scan if name in COINS}

        if should_auto_scan and not manual_scan:
            st.info("🤖 Auto-scan triggered at " + datetime.now().strftime("%H:%M:%S"))

        st.session_state.last_auto_scan = datetime.now()

        results = []
        progress = st.progress(0)
        status_text = st.empty()
        total_coins = len(scan_ids)
        for i, (name, cid) in enumerate(scan_ids.items()):
            status_text.text("Scanning " + name + " (" + str(i+1) + "/" + str(total_coins) + ")...")
            result = quick_analyze(cid, scanner_days, COIN_KEYWORDS_FULL)
            if result["success"]:
                results.append({
                    "Coin": name, "Price": "$" + str(round(result["price"] or 0, 4)),
                    "24h %": str(round(result["change_24h"] or 0, 2)) + "%",
                    "Signal": result["signal"],
                    "Bull": result["bull"], "Bear": result["bear"],
                    "Confidence": str(result["confidence"]) + "%",
                    "RSI": str(round(result["rsi"], 1)),
                    "Vol Ratio": str(round(result["volume_ratio"], 2)) + "x",
                    "VWAP": "Above" if result["above_vwap"] else "Below",
                    "_signal_raw": result["signal"],
                    "_price_raw": result["price"],
                    "_change_raw": result["change_24h"],
                    "_confidence_raw": result["confidence"],
                    "_bull_raw": result["bull"],
                })
                should_alert = ("STRONG" in result["signal"]) if alert_strong_only else (result["signal"] != "HOLD")
                if should_alert:
                    emoji = "🚀" if "BUY" in result["signal"] else "💀"
                    msg = emoji + " <b>SCANNER: " + result["signal"] + "</b>\n"
                    msg += "Coin: <b>" + name + "</b>\n"
                    msg += "Price: $" + str(round(result["price"], 4)) + "\n"
                    msg += "24h: " + str(round(result["change_24h"] or 0, 2)) + "%\n"
                    msg += "Confidence: " + str(result["confidence"]) + "%"
                    send_telegram(msg)
            else:
                results.append({
                    "Coin": name, "Price": "Error", "24h %": "—", "Signal": "ERROR",
                    "Bull": 0, "Bear": 0, "Confidence": "—", "RSI": "—", "Vol Ratio": "—", "VWAP": "—",
                    "_signal_raw": "ERROR", "_price_raw": 0, "_change_raw": 0, "_confidence_raw": 0, "_bull_raw": 0,
                })
            progress.progress((i + 1) / total_coins)
            time.sleep(0.5)
        status_text.text("✅ Scan complete — " + str(total_coins) + " coins analyzed")
        progress.empty()

        signal_order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4, "ERROR": 5}
        results.sort(key=lambda x: signal_order.get(x["_signal_raw"], 99))

        st.divider()
        strong_buys = [r for r in results if r["_signal_raw"] == "STRONG BUY"]
        buys = [r for r in results if r["_signal_raw"] == "BUY"]
        sells = [r for r in results if r["_signal_raw"] == "SELL"]
        strong_sells = [r for r in results if r["_signal_raw"] == "STRONG SELL"]
        holds = [r for r in results if r["_signal_raw"] == "HOLD"]
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("🚀 Strong Buy", len(strong_buys))
        m2.metric("📈 Buy", len(buys))
        m3.metric("⚪ Hold", len(holds))
        m4.metric("📉 Sell", len(sells))
        m5.metric("💀 Strong Sell", len(strong_sells))
        st.divider()
        display_cols = ["Coin", "Price", "24h %", "Signal", "Bull", "Bear", "Confidence", "RSI", "Vol Ratio", "VWAP"]
        display_df = pd.DataFrame([{k: r[k] for k in display_cols} for r in results])
        st.dataframe(display_df, use_container_width=True)

        # Store results in session state for auto-refresh display
        st.session_state.last_scan_results = results
        st.session_state.last_scan_time = datetime.now().strftime("%H:%M:%S")

    elif "last_scan_results" in st.session_state and st.session_state.last_scan_results:
        st.info("Showing last scan results from " + st.session_state.get("last_scan_time", "earlier") + " · Click 'Scan Now' or enable Auto-Scan to refresh")
        results = st.session_state.last_scan_results
        signal_order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4, "ERROR": 5}
        results.sort(key=lambda x: signal_order.get(x["_signal_raw"], 99))
        strong_buys = [r for r in results if r["_signal_raw"] == "STRONG BUY"]
        buys = [r for r in results if r["_signal_raw"] == "BUY"]
        sells = [r for r in results if r["_signal_raw"] == "SELL"]
        strong_sells = [r for r in results if r["_signal_raw"] == "STRONG SELL"]
        holds = [r for r in results if r["_signal_raw"] == "HOLD"]
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("🚀 Strong Buy", len(strong_buys))
        m2.metric("📈 Buy", len(buys))
        m3.metric("⚪ Hold", len(holds))
        m4.metric("📉 Sell", len(sells))
        m5.metric("💀 Strong Sell", len(strong_sells))
        st.divider()
        display_cols = ["Coin", "Price", "24h %", "Signal", "Bull", "Bear", "Confidence", "RSI", "Vol Ratio", "VWAP"]
        display_df = pd.DataFrame([{k: r[k] for k in display_cols} for r in results])
        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("Select coins above and click 'Scan Now', or enable Auto-Scan.")

    # Auto-refresh page when auto-scan is enabled
    if auto_enabled:
        next_scan_secs = auto_interval * 60
        if "last_auto_scan" in st.session_state and st.session_state.last_auto_scan:
            elapsed = (datetime.now() - st.session_state.last_auto_scan).total_seconds()
            next_scan_secs = max(5, int((auto_interval * 60) - elapsed))
        st.caption("🔄 Page will refresh automatically in " + str(next_scan_secs) + " seconds")
        time.sleep(next_scan_secs)
        st.rerun()

# ── TAB 3: Backtest ────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### 🔬 Backtest")
    b1, b2 = st.columns(2)
    with b1:
        bt_coin = st.selectbox("Coin", list(COINS.keys()), key="bt_coin")
    with b2:
        bt_days = st.selectbox("Period", [30, 90, 180, 365], index=1, format_func=lambda x: str(x) + " days", key="bt_days")
    if st.button("Run Backtest", type="primary", key="backtest_btn"):
        with st.spinner("Running backtest on " + str(bt_days) + " days of data..."):
            try:
                bt_coin_id = COINS[bt_coin]
                hist_url = "https://api.coingecko.com/api/v3/coins/" + bt_coin_id + "/market_chart?vs_currency=usd&days=" + str(bt_days)
                hist_res = requests.get(hist_url, headers=HEADERS, timeout=15)
                hist_data = hist_res.json()
                prices = [p[1] for p in hist_data["prices"]]
                bt_results = run_backtest(prices, backtest_capital, backtest_stop_loss, backtest_take_profit)
                st.divider()
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Final Value", "$" + str(round(bt_results["final_value"], 2)), str(round(bt_results["total_return"], 1)) + "%")
                r2.metric("Win Rate", str(round(bt_results["win_rate"], 1)) + "%")
                r3.metric("Total Trades", str(bt_results["total_trades"]))
                r4.metric("Max Drawdown", str(round(bt_results["max_drawdown"], 1)) + "%")
                r5, r6, r7, r8 = st.columns(4)
                r5.metric("Wins", str(bt_results["winning_trades"]))
                r6.metric("Losses", str(bt_results["losing_trades"]))
                r7.metric("Avg Win", str(round(bt_results["avg_win"], 1)) + "%")
                r8.metric("Avg Loss", str(round(bt_results["avg_loss"], 1)) + "%")
                r9, r10 = st.columns(2)
                r9.metric("Best Trade", str(round(bt_results["best_trade"], 1)) + "%")
                r10.metric("Worst Trade", str(round(bt_results["worst_trade"], 1)) + "%")
                if bt_results["total_return"] > 20 and bt_results["win_rate"] > 55:
                    st.success("🏆 Verdict: EXCELLENT — Strong strategy on this coin/period")
                elif bt_results["total_return"] > 0 and bt_results["win_rate"] > 45:
                    st.success("✅ Verdict: GOOD — Profitable strategy")
                elif bt_results["total_return"] > -10:
                    st.warning("⚠️ Verdict: MIXED — Marginal results")
                else:
                    st.error("❌ Verdict: BAD — Strategy struggled in this period")
                import plotly.graph_objects as go
                eq_fig = go.Figure()
                eq_fig.add_trace(go.Scatter(y=bt_results["equity_curve"], name="Portfolio Value", fill="tozeroy", line=dict(color="cyan")))
                eq_fig.update_layout(title="Equity Curve", template="plotly_dark", height=350)
                st.plotly_chart(eq_fig, use_container_width=True)
                st.subheader("📋 Trade Log")
                trade_log = []
                for t in bt_results["trades"]:
                    if t["type"] == "SELL":
                        trade_log.append({
                            "Type": t["type"], "Price": "$" + str(round(t["price"], 4)),
                            "P&L %": str(round(t["profit_pct"], 2)) + "%",
                            "Reason": t.get("reason", "SELL SIGNAL")
                        })
                if trade_log:
                    st.dataframe(pd.DataFrame(trade_log), use_container_width=True)
            except Exception as e:
                st.error("Backtest error: " + str(e))

# ── TAB 4: Trade Journal ───────────────────────────────────────────────────────
with tab4:
    st.markdown("### 📒 Trade Journal")
    journal = load_journal()
    st.subheader("➕ Log a Trade")
    j1, j2, j3 = st.columns(3)
    with j1:
        j_coin = st.selectbox("Coin", list(COINS.keys()), key="j_coin")
        j_type = st.selectbox("Trade Type", ["BUY", "SELL"], key="j_type")
    with j2:
        j_entry = st.number_input("Entry Price ($)", min_value=0.0, value=0.0, step=0.01, key="j_entry")
        j_exit = st.number_input("Exit Price ($, 0 if open)", min_value=0.0, value=0.0, step=0.01, key="j_exit")
    with j3:
        j_amount = st.number_input("Amount ($)", min_value=0.0, value=100.0, step=10.0, key="j_amount")
        j_signal = st.selectbox("Signal Used", ["BUY", "STRONG BUY", "SELL", "STRONG SELL", "HOLD", "Manual"], key="j_signal")
    j_notes = st.text_area("Notes", key="j_notes", height=80)
    j_date = st.date_input("Trade Date", key="j_date")
    if st.button("💾 Save Trade", type="primary", key="save_trade"):
        if j_entry > 0 and j_amount > 0:
            coins_bought = j_amount / j_entry if j_entry > 0 else 0
            profit_usd = 0
            profit_pct = 0
            status = "OPEN"
            if j_exit > 0:
                profit_usd = (j_exit - j_entry) * coins_bought
                profit_pct = ((j_exit - j_entry) / j_entry) * 100
                status = "CLOSED"
            journal.append({
                "coin": j_coin, "type": j_type, "entry": j_entry, "exit": j_exit,
                "amount": j_amount, "coins_bought": coins_bought,
                "profit_usd": profit_usd, "profit_pct": profit_pct,
                "signal": j_signal, "notes": j_notes,
                "date": str(j_date), "status": status
            })
            save_journal(journal)
            st.success("✅ Trade saved!")
            st.rerun()
        else:
            st.error("Please enter valid entry price and amount.")
    if journal:
        st.divider()
        st.subheader("📊 Performance Summary")
        closed = [t for t in journal if t.get("status") == "CLOSED"]
        if closed:
            total_pnl = sum(t["profit_usd"] for t in closed)
            wins = [t for t in closed if t["profit_usd"] > 0]
            losses = [t for t in closed if t["profit_usd"] <= 0]
            win_rate_j = (len(wins) / len(closed)) * 100 if closed else 0
            avg_win_j = np.mean([t["profit_usd"] for t in wins]) if wins else 0
            avg_loss_j = np.mean([t["profit_usd"] for t in losses]) if losses else 0
            p1, p2, p3, p4, p5 = st.columns(5)
            p1.metric("Win Rate", str(round(win_rate_j, 1)) + "%")
            p2.metric("Total P&L", ("+" if total_pnl >= 0 else "") + "$" + str(round(total_pnl, 2)))
            p3.metric("Closed Trades", str(len(closed)))
            p4.metric("Avg Win", "+$" + str(round(avg_win_j, 2)))
            p5.metric("Avg Loss", "-$" + str(round(abs(avg_loss_j), 2)))
            import plotly.graph_objects as go
            cumulative = np.cumsum([t["profit_usd"] for t in closed]).tolist()
            pnl_fig = go.Figure()
            pnl_fig.add_trace(go.Scatter(y=cumulative, fill="tozeroy", name="Cumulative P&L", line=dict(color="cyan")))
            pnl_fig.update_layout(title="Equity Curve (Real Trades)", template="plotly_dark", height=300)
            st.plotly_chart(pnl_fig, use_container_width=True)
        st.divider()
        st.subheader("📋 Trade History")
        display_j = []
        for t in reversed(journal):
            display_j.append({
                "Date": t.get("date", ""), "Coin": t["coin"], "Type": t["type"],
                "Entry": "$" + str(round(t["entry"], 4)),
                "Exit": "$" + str(round(t["exit"], 4)) if t["exit"] > 0 else "Open",
                "Amount": "$" + str(round(t["amount"], 2)),
                "P&L": ("+" if t["profit_usd"] >= 0 else "") + "$" + str(round(t["profit_usd"], 2)) if t["status"] == "CLOSED" else "Open",
                "Signal": t.get("signal", ""), "Status": t.get("status", ""),
                "Notes": t.get("notes", "")[:40]
            })
        st.dataframe(pd.DataFrame(display_j), use_container_width=True)
        st.divider()
        st.subheader("🔒 Close an Open Trade")
        open_trades = [t for t in journal if t.get("status") == "OPEN"]
        if open_trades:
            close_idx = st.selectbox("Select trade to close", range(len(open_trades)),
                format_func=lambda x: open_trades[x]["coin"] + " — $" + str(round(open_trades[x]["entry"], 4)) + " on " + open_trades[x].get("date", ""))
            close_exit = st.number_input("Exit Price ($)", min_value=0.0, value=0.0, step=0.01, key="close_exit")
            if st.button("✅ Close Trade", key="close_trade_btn"):
                target = open_trades[close_idx]
                for t in journal:
                    if t["coin"] == target["coin"] and t["entry"] == target["entry"] and t.get("status") == "OPEN":
                        t["exit"] = close_exit
                        t["profit_usd"] = (close_exit - t["entry"]) * t["coins_bought"]
                        t["profit_pct"] = ((close_exit - t["entry"]) / t["entry"]) * 100
                        t["status"] = "CLOSED"
                        break
                save_journal(journal)
                st.success("✅ Trade closed!")
        if st.button("🗑️ Delete Last Trade"):
            if journal:
                journal.pop()
                save_journal(journal)
                st.warning("Last trade deleted.")
    else:
        st.info("No trades logged yet.")

# ── TAB 5: Paper Trading ───────────────────────────────────────────────────────
with tab5:
    st.markdown("### 🤖 Paper Trading")
    st.markdown("Practice trading with **fake $10,000** using real live prices from CoinGecko. No real money involved!")
    st.info("💡 Paper trading — real market prices, completely fake money. Practice before going live.")

    paper_data = load_paper_trades()
    paper_balance = paper_data["balance"]
    paper_positions = paper_data["positions"]
    paper_trades = paper_data["trades"]

    st.divider()
    st.subheader("💰 Paper Account")
    pa1, pa2, pa3 = st.columns(3)
    pa1.metric("Available Balance", "$" + str(round(paper_balance, 2)))
    pa2.metric("Open Positions", str(len(paper_positions)))
    pa3.metric("Total Trades", str(len([t for t in paper_trades if t["type"] == "SELL"])))

    if st.button("🔄 Reset Paper Account to $10,000", key="reset_paper"):
        paper_data = {"balance": 10000.0, "trades": [], "positions": {}}
        save_paper_trades(paper_data)
        st.success("✅ Paper account reset to $10,000!")
        st.rerun()

    # ── DIAGNOSTIC ENGINE ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("🔧 Diagnostic Engine")
    st.caption("Analyzes your trades and tells you exactly what's broken — and which feature would fix it.")
    if st.button("🔍 Run Diagnostic", key="run_diag"):
        st.session_state["diag_results"] = run_diagnostic(paper_trades, paper_positions)
    if "diag_results" in st.session_state:
        diag = st.session_state["diag_results"]
        critical_count = len([d for d in diag if d["severity"] == "critical"])
        warning_count = len([d for d in diag if d["severity"] == "warning"])
        info_count = len([d for d in diag if d["severity"] == "info"])
        dc1, dc2, dc3 = st.columns(3)
        dc1.metric("🔴 Critical", critical_count)
        dc2.metric("🟡 Warnings", warning_count)
        dc3.metric("🔵 Info", info_count)
        for i, issue in enumerate(diag, 1):
            sev = issue["severity"]
            if sev == "critical":
                with st.container():
                    st.error("**🔴 " + str(i) + ". " + issue["title"] + "**")
                    st.markdown(issue["detail"])
                    st.markdown("**💡 Fix:** " + issue["fix"])
            elif sev == "warning":
                with st.container():
                    st.warning("**🟡 " + str(i) + ". " + issue["title"] + "**")
                    st.markdown(issue["detail"])
                    st.markdown("**💡 Fix:** " + issue["fix"])
            elif sev == "success":
                with st.container():
                    st.success("**✅ " + issue["title"] + "**")
                    st.markdown(issue["detail"])
                    st.markdown("**💡 Next step:** " + issue["fix"])
            else:
                with st.container():
                    st.info("**🔵 " + str(i) + ". " + issue["title"] + "**")
                    st.markdown(issue["detail"])
                    st.markdown("**💡 Fix:** " + issue["fix"])

    AUTOPILOT_FILE = "autopilot_config.json"

    def load_autopilot():
        default = {
            "enabled": False,
            "scan_every_hours": 4,
            "max_trades_per_day": 5,
            "max_open_positions": 8,
            "min_confidence": 65,
            "min_bull_score": 10,
            "position_size": 500.0,
            "multi_timeframe": True,
            "btc_filter": True,
            "btc_threshold": -3.0,
            "sector_rotation": True,
            "sentiment_override": True,
            "last_scan": None,
            "trades_today": [],
            "log": [],
        }
        if SUPABASE_URL and SUPABASE_KEY:
            saved = supabase_get("autopilot_config", "main")
            if saved:
                default.update(saved)
        elif os.path.exists("autopilot_config.json"):
            try:
                with open("autopilot_config.json", "r") as f:
                    saved = json.load(f)
                default.update(saved)
            except:
                pass
        today_str = datetime.now().strftime("%Y-%m-%d")
        default["trades_today"] = [t for t in default.get("trades_today", []) if t.startswith(today_str)]
        return default

    def save_autopilot(cfg):
        if SUPABASE_URL and SUPABASE_KEY:
            supabase_set("autopilot_config", "main", cfg)
        with open("autopilot_config.json", "w") as f:
            json.dump(cfg, f)

    autopilot = load_autopilot()

    st.divider()
    st.subheader("🤖 Auto-Pilot")
    st.caption("Let the bot scan and trade automatically using your settings. Paper money only — no real funds at risk.")

    ap_col1, ap_col2 = st.columns([1, 2])
    with ap_col1:
        autopilot_on = st.toggle("🟢 Enable Auto-Pilot", value=autopilot["enabled"], key="autopilot_toggle")
        if autopilot_on != autopilot["enabled"]:
            autopilot["enabled"] = autopilot_on
            save_autopilot(autopilot)
            if autopilot_on:
                st.success("Auto-Pilot is now ON 🚀")
                send_telegram("🤖 <b>AUTO-PILOT ENABLED</b>\nThe bot will start scanning and trading automatically.")
            else:
                st.warning("Auto-Pilot is now OFF 🛑")
                send_telegram("🤖 <b>AUTO-PILOT DISABLED</b>")
            st.rerun()
    with ap_col2:
        if autopilot["enabled"]:
            st.success("✅ **Auto-Pilot is ACTIVE** — scanning and trading on its own")
        else:
            st.info("⚪ Auto-Pilot is OFF — you trade manually")

    with st.expander("⚙️ Auto-Pilot Settings"):
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            new_scan_hrs = st.number_input("Scan every (hours)", min_value=1, max_value=24, value=autopilot["scan_every_hours"], key="ap_scan_hrs")
            new_max_daily = st.number_input("Max trades per day", min_value=1, max_value=20, value=autopilot["max_trades_per_day"], key="ap_max_daily")
        with ac2:
            new_max_open = st.number_input("Max open positions", min_value=1, max_value=20, value=autopilot["max_open_positions"], key="ap_max_open")
            new_min_conf = st.slider("Min confidence (%)", min_value=50, max_value=95, value=autopilot["min_confidence"], step=5, key="ap_min_conf")
        with ac3:
            new_min_bull = st.number_input("Min bull score", min_value=7, max_value=15, value=autopilot["min_bull_score"], key="ap_min_bull")
            new_pos_size = st.number_input("Position size ($)", min_value=10.0, max_value=5000.0, value=autopilot["position_size"], step=50.0, key="ap_pos_size")
        new_mtf = st.checkbox("🔄 Multi-Timeframe Confirmation (require 14d signal to agree before buying)",
                              value=autopilot.get("multi_timeframe", True), key="ap_mtf")
        st.markdown("**🛡️ Smart Filters**")
        nf1, nf2 = st.columns(2)
        with nf1:
            new_btc_filter = st.checkbox("🟠 BTC Crash Filter (pause buys when BTC drops hard)",
                                         value=autopilot.get("btc_filter", True), key="ap_btc")
            new_btc_thresh = st.number_input("Pause if BTC 24h drops below (%)",
                                             min_value=-15.0, max_value=-1.0,
                                             value=autopilot.get("btc_threshold", -3.0), step=0.5, key="ap_btc_thr")
        with nf2:
            new_sector = st.checkbox("🔥 Sector Rotation (prefer hot sectors)",
                                     value=autopilot.get("sector_rotation", True), key="ap_sector")
            new_sentiment = st.checkbox("😨 Sentiment Override (adapt to Fear & Greed)",
                                        value=autopilot.get("sentiment_override", True), key="ap_sent")
        if st.button("💾 Save Settings", key="save_ap"):
            autopilot["scan_every_hours"] = int(new_scan_hrs)
            autopilot["max_trades_per_day"] = int(new_max_daily)
            autopilot["max_open_positions"] = int(new_max_open)
            autopilot["min_confidence"] = int(new_min_conf)
            autopilot["min_bull_score"] = int(new_min_bull)
            autopilot["position_size"] = float(new_pos_size)
            autopilot["multi_timeframe"] = bool(new_mtf)
            autopilot["btc_filter"] = bool(new_btc_filter)
            autopilot["btc_threshold"] = float(new_btc_thresh)
            autopilot["sector_rotation"] = bool(new_sector)
            autopilot["sentiment_override"] = bool(new_sentiment)
            save_autopilot(autopilot)
            st.success("Saved!")
            st.rerun()

    # Market Status mini-panel
    with st.expander("📡 Market Status"):
        msc1, msc2 = st.columns(2)
        with msc1:
            try:
                btc_now = check_btc_health()
                if btc_now > 0:
                    msc1.metric("BTC 24h", "+" + str(round(btc_now, 2)) + "%", delta="Bullish 🟢")
                elif btc_now > autopilot.get("btc_threshold", -3.0):
                    msc1.metric("BTC 24h", str(round(btc_now, 2)) + "%", delta="Caution 🟡")
                else:
                    msc1.metric("BTC 24h", str(round(btc_now, 2)) + "%", delta="DANGER 🔴")
            except:
                msc1.metric("BTC 24h", "N/A")
        with msc2:
            try:
                fg_now = get_fear_greed()
                if fg_now < 25:
                    label = "Extreme Fear 😨"
                elif fg_now < 45:
                    label = "Fear 😟"
                elif fg_now < 55:
                    label = "Neutral 😐"
                elif fg_now < 75:
                    label = "Greed 😏"
                else:
                    label = "Extreme Greed 🤑"
                msc2.metric("Fear & Greed", str(fg_now) + "/100", delta=label)
            except:
                msc2.metric("Fear & Greed", "N/A")

    # Status row
    aps1, aps2, aps3, aps4 = st.columns(4)
    trades_today_count = len(autopilot.get("trades_today", []))
    aps1.metric("Trades Today", str(trades_today_count) + " / " + str(autopilot["max_trades_per_day"]))
    aps2.metric("Open Positions", str(len(paper_positions)) + " / " + str(autopilot["max_open_positions"]))
    if autopilot.get("last_scan"):
        last_scan_dt = datetime.fromisoformat(autopilot["last_scan"])
        mins_ago = int((datetime.now() - last_scan_dt).total_seconds() / 60)
        aps3.metric("Last Auto-Scan", str(mins_ago) + " min ago")
        next_scan_mins = max(0, autopilot["scan_every_hours"] * 60 - mins_ago)
        aps4.metric("Next Scan", "in " + str(next_scan_mins) + " min" if next_scan_mins > 0 else "Due now")
    else:
        aps3.metric("Last Auto-Scan", "Never")
        aps4.metric("Next Scan", "On enable")

    # Run logic
    def run_autopilot_scan():
        cfg = load_autopilot()
        if not cfg["enabled"]:
            return None
        paper_d = load_paper_trades()
        held = set(paper_d.get("positions", {}).keys())
        if len(held) >= cfg["max_open_positions"]:
            cfg["log"].insert(0, str(datetime.now())[:19] + " · Skipped: max positions reached (" + str(len(held)) + ")")
            cfg["last_scan"] = datetime.now().isoformat()
            cfg["log"] = cfg["log"][:30]
            save_autopilot(cfg)
            return {"action": "skipped", "reason": "max positions"}
        today_str = datetime.now().strftime("%Y-%m-%d")
        trades_today_now = [t for t in cfg.get("trades_today", []) if t.startswith(today_str)]
        if len(trades_today_now) >= cfg["max_trades_per_day"]:
            cfg["log"].insert(0, str(datetime.now())[:19] + " · Skipped: daily trade limit reached")
            cfg["last_scan"] = datetime.now().isoformat()
            cfg["log"] = cfg["log"][:30]
            save_autopilot(cfg)
            return {"action": "skipped", "reason": "daily limit"}
        # BTC crash filter
        if cfg.get("btc_filter", True):
            btc_change = check_btc_health()
            if btc_change < cfg.get("btc_threshold", -3.0):
                cfg["log"].insert(0, str(datetime.now())[:19] + " · 🟠 BTC FILTER: BTC down " + str(round(btc_change, 2)) + "% — pausing new buys")
                cfg["last_scan"] = datetime.now().isoformat()
                cfg["log"] = cfg["log"][:30]
                save_autopilot(cfg)
                send_telegram("🛡️ <b>BTC CRASH FILTER ACTIVE</b>\nBTC is down " + str(round(btc_change, 2)) + "% in 24h.\nPausing new buys until BTC stabilizes.")
                return {"action": "skipped", "reason": "BTC dumping " + str(round(btc_change, 2)) + "%"}
        # Sentiment override — adjust effective bull score requirement
        effective_min_bull = cfg["min_bull_score"]
        sentiment_note = ""
        if cfg.get("sentiment_override", True):
            fg = get_fear_greed()
            if fg < 20:
                effective_min_bull = max(cfg["min_bull_score"] - 2, 7)
                sentiment_note = " (😨 extreme fear: bull threshold lowered to " + str(effective_min_bull) + ")"
            elif fg > 80:
                effective_min_bull = cfg["min_bull_score"] + 2
                sentiment_note = " (🤑 extreme greed: bull threshold raised to " + str(effective_min_bull) + ")"
        # Scan
        results = []
        coin_items = list(COINS.items())
        for coin_name_a, coin_id_a in coin_items:
            if coin_name_a in held:
                continue
            r = quick_analyze(coin_id_a, days=90, coin_keywords=COIN_KEYWORDS_FULL)
            if r.get("success"):
                r["coin_name"] = coin_name_a
                r["coin_id"] = coin_id_a
                results.append(r)
            time.sleep(0.4)
        candidates = [r for r in results
                      if r["signal"] == "STRONG BUY"
                      and r["bull"] >= effective_min_bull
                      and r["confidence"] >= cfg["min_confidence"]]
        # Sector rotation boost
        if cfg.get("sector_rotation", True):
            sectors = detect_hot_sectors(results)
            if sectors:
                top_sector = max(sectors.items(), key=lambda x: x[1]["signals"])
                if top_sector[1]["signals"] >= 2:
                    for c in candidates:
                        cat = categorize_coin(c["coin_id"])
                        if cat == top_sector[0]:
                            c["sector_boost"] = True
                            c["bull"] += 2
                    cfg["log"].insert(0, str(datetime.now())[:19] + " · 🔥 Hot sector: " + top_sector[0] + " (" + str(top_sector[1]["signals"]) + " signals)")
        insights_now = generate_trade_insights(paper_d.get("trades", []))
        if insights_now:
            candidates = apply_insights_to_picks(candidates, insights_now)
            candidates = [c for c in candidates if c.get("adjusted_score", c["bull"]) >= effective_min_bull]
        else:
            candidates.sort(key=lambda x: (x["bull"], x["confidence"]), reverse=True)
        slots_available = min(
            cfg["max_open_positions"] - len(held),
            cfg["max_trades_per_day"] - len(trades_today_now)
        )
        bought = []
        for c in candidates[:slots_available]:
            if paper_d["balance"] < cfg["position_size"]:
                cfg["log"].insert(0, str(datetime.now())[:19] + " · Skipped " + c["coin_name"] + ": low balance")
                break
            if cfg.get("multi_timeframe", True):
                short_signal = quick_analyze_short(c["coin_id"])
                if short_signal != "BULLISH":
                    cfg["log"].insert(0, str(datetime.now())[:19] + " · Skipped " + c["coin_name"] + ": 14d signal " + str(short_signal) + " (need BULLISH)")
                    time.sleep(0.4)
                    continue
                time.sleep(0.4)
            entry_price = c["price"]
            coins_bought = cfg["position_size"] / entry_price
            sl_px = entry_price * (1 - stop_loss_pct / 100)
            tp_px = entry_price + (entry_price - sl_px) * take_profit_ratio
            paper_d["balance"] -= cfg["position_size"]
            paper_d["positions"][c["coin_name"]] = {
                "coins": coins_bought, "entry_price": entry_price,
                "cost": cfg["position_size"], "date": str(datetime.now())[:19],
                "sl_price": sl_px, "tp_price": tp_px,
                "trailing_sl": sl_px, "highest_price": entry_price,
            }
            paper_d["trades"].append({
                "type": "BUY", "coin": c["coin_name"], "price": entry_price,
                "amount": cfg["position_size"], "coins": coins_bought,
                "date": str(datetime.now())[:19], "profit_usd": 0, "profit_pct": 0,
                "entry_rsi": c.get("rsi", 50), "entry_bull": c["bull"],
                "entry_bear": c["bear"], "entry_volume_ratio": c.get("volume_ratio", 1),
                "entry_category": categorize_coin(c["coin_id"]),
                "source": "auto-pilot",
            })
            bought.append(c["coin_name"])
            cfg["trades_today"].append(str(datetime.now())[:19])
            cfg["log"].insert(0, str(datetime.now())[:19] + " · BOUGHT " + c["coin_name"] + " @ $" + str(round(entry_price, 4)) + " · bull " + str(c["bull"]) + " · " + str(c["confidence"]) + "%")
            send_telegram("🤖 <b>AUTO-PILOT BOUGHT</b>\nCoin: " + c["coin_name"] + "\nPrice: $" + str(round(entry_price, 4)) + "\nBull: " + str(c["bull"]) + " · Confidence: " + str(c["confidence"]) + "%\nSL: $" + str(round(sl_px, 4)) + "\nTP: $" + str(round(tp_px, 4)))
        if not bought:
            cfg["log"].insert(0, str(datetime.now())[:19] + " · Scan complete: no qualifying signals")
        # ── Signal-based selling: check held positions for SELL signals ──
        sold = []
        for coin_name_held in list(held):
            coin_id_held = COINS.get(coin_name_held, "")
            if not coin_id_held:
                continue
            held_result = quick_analyze(coin_id_held, days=90, coin_keywords=COIN_KEYWORDS_FULL)
            if not held_result.get("success"):
                continue
            if held_result["signal"] in ("SELL", "STRONG SELL"):
                pos_held = paper_d["positions"].get(coin_name_held)
                if not pos_held:
                    continue
                sell_price = held_result["price"]
                sale_value = pos_held["coins"] * sell_price
                profit_usd = sale_value - pos_held["cost"]
                profit_pct = (profit_usd / pos_held["cost"]) * 100
                paper_d["balance"] += sale_value
                paper_d["trades"].append({
                    "type": "SELL", "coin": coin_name_held, "price": sell_price,
                    "amount": sale_value, "coins": pos_held["coins"],
                    "date": str(datetime.now())[:19],
                    "profit_usd": profit_usd, "profit_pct": profit_pct,
                    "reason": "SIGNAL-SELL (" + held_result["signal"] + ")",
                    "entry_rsi": 0, "entry_bull": 0, "entry_bear": 0,
                    "entry_volume_ratio": 0, "entry_category": categorize_coin(coin_id_held),
                    "source": "auto-pilot",
                })
                del paper_d["positions"][coin_name_held]
                sold.append(coin_name_held)
                cfg["log"].insert(0, str(datetime.now())[:19] + " · SIGNAL SOLD " + coin_name_held + " @ $" + str(round(sell_price, 4)) + " · " + held_result["signal"] + " · P&L: " + ("+" if profit_usd >= 0 else "") + "$" + str(round(profit_usd, 2)))
                if profit_usd >= 0:
                    send_telegram("🤖 <b>AUTO-PILOT SIGNAL SELL ✅</b>\nCoin: " + coin_name_held + "\nSignal: " + held_result["signal"] + "\nPrice: $" + str(round(sell_price, 4)) + "\nProfit: +$" + str(round(profit_usd, 2)) + " (+" + str(round(profit_pct, 2)) + "%)")
                else:
                    send_telegram("🤖 <b>AUTO-PILOT SIGNAL SELL ❌</b>\nCoin: " + coin_name_held + "\nSignal: " + held_result["signal"] + "\nPrice: $" + str(round(sell_price, 4)) + "\nLoss: -$" + str(round(abs(profit_usd), 2)) + " (" + str(round(profit_pct, 2)) + "%)")
            time.sleep(0.4)
        save_paper_trades(paper_d)
        cfg["last_scan"] = datetime.now().isoformat()
        cfg["log"] = cfg["log"][:30]
        save_autopilot(cfg)
        return {"action": "traded" if bought or sold else "no_signals", "coins": bought, "sold": sold}

    # Auto-trigger if enabled and due
    if autopilot["enabled"]:
        should_run = False
        if autopilot.get("last_scan") is None:
            should_run = True
        else:
            last = datetime.fromisoformat(autopilot["last_scan"])
            if (datetime.now() - last).total_seconds() >= autopilot["scan_every_hours"] * 3600:
                should_run = True
        if should_run:
            with st.spinner("🤖 Auto-Pilot is scanning..."):
                result = run_autopilot_scan()
                if result and result.get("coins"):
                    st.success("🤖 Auto-Pilot bought: " + ", ".join(result["coins"]))
                if result and result.get("sold"):
                    st.warning("🤖 Auto-Pilot signal-sold: " + ", ".join(result["sold"]))
                if result and (result.get("coins") or result.get("sold")):
                    st.rerun()

    # Manual trigger
    ap_btn1, ap_btn2 = st.columns(2)
    with ap_btn1:
        if st.button("⚡ Run Auto-Pilot Now", key="run_ap_now", disabled=not autopilot["enabled"]):
            with st.spinner("Scanning..."):
                result = run_autopilot_scan()
                if result:
                    if result.get("coins"):
                        st.success("🤖 Bought: " + ", ".join(result["coins"]))
                    if result.get("sold"):
                        st.warning("🤖 Signal-sold: " + ", ".join(result["sold"]))
                    if not result.get("coins") and not result.get("sold"):
                        if result["action"] == "no_signals":
                            st.info("No qualifying signals right now.")
                        else:
                            st.warning("Skipped: " + result.get("reason", "unknown"))
                    st.rerun()
    with ap_btn2:
        if st.button("📊 Send Daily Report to Telegram", key="daily_report"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            recent_closes = [t for t in paper_trades if t["type"] == "SELL" and (t["date"].startswith(today_str) or t["date"].startswith(yesterday_str))]
            wins = len([t for t in recent_closes if t["profit_usd"] > 0])
            losses = len([t for t in recent_closes if t["profit_usd"] <= 0])
            total_pnl_recent = sum(t["profit_usd"] for t in recent_closes)
            report = "🤖 <b>DAILY REPORT</b>\n"
            report += "Closed trades (24h): " + str(len(recent_closes)) + "\n"
            report += "Wins: " + str(wins) + " · Losses: " + str(losses) + "\n"
            report += "P&L: " + ("+" if total_pnl_recent >= 0 else "") + "$" + str(round(total_pnl_recent, 2)) + "\n"
            report += "Account balance: $" + str(round(paper_balance, 2)) + "\n"
            report += "Open positions: " + str(len(paper_positions))
            ok = send_telegram(report)
            if ok: st.success("Report sent!")
            else: st.error("Failed to send")

    if autopilot.get("log"):
        with st.expander("📜 Auto-Pilot Activity Log"):
            for entry in autopilot["log"][:15]:
                st.text(entry)

    st.divider()
    st.subheader("📍 Open Positions")
    position_data = []
    auto_closed = []
    if paper_positions:
        total_position_value = 0
        total_pnl = 0
        positions_to_close = []
        for coin_name_pos, pos in paper_positions.items():
            try:
                coin_id_pos = COINS.get(coin_name_pos, "bitcoin")
                market_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + coin_id_pos
                market_res = requests.get(market_url, headers=HEADERS, timeout=10)
                current_px = market_res.json()[0]["current_price"]
                position_value = pos["coins"] * current_px
                pnl = position_value - pos["cost"]
                pnl_pct = (pnl / pos["cost"]) * 100
                entry_px = pos["entry_price"]
                sl_price = pos.get("sl_price", entry_px * (1 - stop_loss_pct / 100))
                tp_price = pos.get("tp_price", entry_px * (1 + stop_loss_pct * take_profit_ratio / 100))
                trailing_sl = pos.get("trailing_sl", sl_price)
                highest_price = pos.get("highest_price", entry_px)
                if current_px > highest_price:
                    highest_price = current_px
                    gain_from_entry = ((current_px - entry_px) / entry_px) * 100
                    if gain_from_entry >= 2:
                        new_trailing = current_px * (1 - stop_loss_pct / 100)
                        if new_trailing > trailing_sl:
                            trailing_sl = new_trailing
                    pos["highest_price"] = highest_price
                    pos["trailing_sl"] = trailing_sl
                active_sl = max(sl_price, trailing_sl)
                close_reason = ""
                if current_px <= active_sl:
                    close_reason = "STOP-LOSS"
                elif current_px >= tp_price:
                    close_reason = "TAKE-PROFIT"
                if close_reason:
                    positions_to_close.append({
                        "coin": coin_name_pos, "price": current_px,
                        "reason": close_reason, "pos": pos
                    })
                else:
                    total_position_value += position_value
                    total_pnl += pnl
                    position_data.append({
                        "coin": coin_name_pos, "value": position_value, "cost": pos["cost"],
                        "pnl": pnl, "pnl_pct": pnl_pct,
                    })
                    sl_dist = ((current_px - active_sl) / current_px) * 100
                    tp_dist = ((tp_price - current_px) / current_px) * 100
                    pos_info = ("**" + coin_name_pos + "** · Entry: $" + str(round(entry_px, 4)) +
                               " · Current: $" + str(round(current_px, 4)) +
                               " · P&L: " + ("+" if pnl >= 0 else "") + "$" + str(round(pnl, 2)) +
                               " (" + ("+" if pnl_pct >= 0 else "") + str(round(pnl_pct, 2)) + "%)")
                    if pnl >= 0:
                        st.success(pos_info)
                    else:
                        st.error(pos_info)
                    sl_label = "🔒 Trailing SL" if trailing_sl > sl_price else "🛑 SL"
                    sc1, sc2, sc3 = st.columns(3)
                    sc1.caption(sl_label + ": $" + str(round(active_sl, 4)) + " (" + str(round(sl_dist, 1)) + "% away)")
                    sc2.caption("🎯 TP: $" + str(round(tp_price, 4)) + " (" + str(round(tp_dist, 1)) + "% away)")
                    if highest_price > entry_px:
                        sc3.caption("📈 Peak: $" + str(round(highest_price, 4)))
                    if sl_dist < 1.5:
                        st.warning("⚠️ " + coin_name_pos + " is very close to stop loss!")
            except:
                st.warning(coin_name_pos + " — Could not fetch current price")
        if positions_to_close:
            for pc in positions_to_close:
                pos = pc["pos"]
                sale_value = pos["coins"] * pc["price"]
                profit_usd = sale_value - pos["cost"]
                profit_pct = (profit_usd / pos["cost"]) * 100
                paper_data["balance"] += sale_value
                paper_data["trades"].append({
                    "type": "SELL", "coin": pc["coin"], "price": pc["price"],
                    "amount": sale_value, "coins": pos["coins"],
                    "date": str(datetime.now())[:19],
                    "profit_usd": profit_usd, "profit_pct": profit_pct,
                    "reason": pc["reason"],
                })
                del paper_data["positions"][pc["coin"]]
                auto_closed.append({
                    "coin": pc["coin"], "reason": pc["reason"],
                    "profit_usd": profit_usd, "profit_pct": profit_pct,
                })
                if profit_usd >= 0:
                    send_telegram("🤖 <b>AUTO-CLOSE: " + pc["reason"] + " ✅</b>\nCoin: " + pc["coin"] + "\nProfit: +$" + str(round(profit_usd, 2)) + " (+" + str(round(profit_pct, 2)) + "%)")
                else:
                    send_telegram("🤖 <b>AUTO-CLOSE: " + pc["reason"] + " ❌</b>\nCoin: " + pc["coin"] + "\nLoss: -$" + str(round(abs(profit_usd), 2)) + " (" + str(round(profit_pct, 2)) + "%)")
            save_paper_trades(paper_data)
            for ac in auto_closed:
                if ac["reason"] == "TAKE-PROFIT":
                    st.success("🎯 **AUTO-CLOSED " + ac["coin"] + " — TAKE PROFIT** · +$" + str(round(ac["profit_usd"], 2)) + " (+" + str(round(ac["profit_pct"], 2)) + "%) 🎉")
                    st.balloons()
                else:
                    st.error("🛑 **AUTO-CLOSED " + ac["coin"] + " — STOP LOSS** · -$" + str(round(abs(ac["profit_usd"]), 2)) + " (" + str(round(ac["profit_pct"], 2)) + "%)")
            st.info("Positions were auto-closed. Refresh to see updated balance.")
        if not positions_to_close:
            st.metric("Total Unrealized P&L", ("+" if total_pnl >= 0 else "") + "$" + str(round(total_pnl, 2)))
    else:
        st.info("No open positions. Place a paper trade below!")

    if position_data:
        st.divider()
        st.subheader("🔥 Portfolio Heat Map")
        import plotly.graph_objects as go
        total_account = paper_balance + sum(p["value"] for p in position_data)
        cash_pct = (paper_balance / total_account) * 100 if total_account > 0 else 0
        labels = [p["coin"] for p in position_data] + ["💵 Cash (unused)"]
        values = [p["value"] for p in position_data] + [paper_balance]
        colors_map = []
        for p in position_data:
            if p["pnl_pct"] > 2:
                colors_map.append("#16a34a")
            elif p["pnl_pct"] > 0:
                colors_map.append("#86efac")
            elif p["pnl_pct"] > -2:
                colors_map.append("#fca5a5")
            else:
                colors_map.append("#dc2626")
        colors_map.append("#6b7280")
        fig = go.Figure(data=[go.Pie(
            labels=labels, values=values, hole=0.45,
            marker=dict(colors=colors_map, line=dict(color="#0e1117", width=2)),
            textinfo="label+percent", textposition="outside",
        )])
        fig.update_layout(
            template="plotly_dark", height=420,
            showlegend=True,
            annotations=[dict(text="$" + str(round(total_account, 0)), x=0.5, y=0.5, font_size=18, showarrow=False)]
        )
        st.plotly_chart(fig, use_container_width=True)
        hm1, hm2, hm3 = st.columns(3)
        hm1.metric("Account Total", "$" + str(round(total_account, 2)))
        hm2.metric("In Positions", "$" + str(round(sum(p["value"] for p in position_data), 2)),
                   delta=str(round(100 - cash_pct, 1)) + "% deployed")
        hm3.metric("Cash Available", "$" + str(round(paper_balance, 2)),
                   delta=str(round(cash_pct, 1)) + "% sitting")
        biggest = max(position_data, key=lambda x: x["value"])
        biggest_pct = (biggest["value"] / total_account) * 100
        if biggest_pct > 40:
            st.warning("⚠️ **" + biggest["coin"] + "** is " + str(round(biggest_pct, 1)) + "% of your account — that's concentrated. Consider reducing.")

    st.divider()
    st.subheader("📊 Place a Paper Trade")
    pt1, pt2, pt3 = st.columns(3)
    with pt1:
        pt_coin = st.selectbox("Coin", list(COINS.keys()), key="pt_coin")
    with pt2:
        pt_amount = st.number_input("Amount ($)", min_value=10.0, max_value=float(max(paper_balance, 10.0)), value=min(100.0, float(max(paper_balance, 10.0))), step=10.0)
    with pt3:
        pt_type = st.selectbox("Action", ["BUY", "SELL (close position)"], key="pt_type")

    if st.button("✅ Execute Paper Trade", type="primary", key="execute_paper"):
        try:
            coin_id_pt = COINS[pt_coin]
            market_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + coin_id_pt
            market_res = requests.get(market_url, headers=HEADERS, timeout=10)
            live_price = market_res.json()[0]["current_price"]

            if "BUY" in pt_type:
                if pt_amount > paper_balance:
                    st.error("Not enough balance!")
                elif pt_coin in paper_positions:
                    st.error("You already have an open position in " + pt_coin + ". Close it first!")
                else:
                    coins_bought = pt_amount / live_price
                    sl_px = live_price * (1 - stop_loss_pct / 100)
                    tp_px = live_price + (live_price - sl_px) * take_profit_ratio
                    paper_data["balance"] -= pt_amount
                    paper_data["positions"][pt_coin] = {
                        "coins": coins_bought,
                        "entry_price": live_price,
                        "cost": pt_amount,
                        "date": str(datetime.now())[:19],
                        "sl_price": sl_px,
                        "tp_price": tp_px,
                        "trailing_sl": sl_px,
                        "highest_price": live_price,
                    }
                    paper_data["trades"].append({
                        "type": "BUY", "coin": pt_coin, "price": live_price,
                        "amount": pt_amount, "coins": coins_bought,
                        "date": str(datetime.now())[:19], "profit_usd": 0, "profit_pct": 0,
                        "entry_rsi": 0, "entry_bull": 0, "entry_bear": 0,
                        "entry_volume_ratio": 0, "entry_category": categorize_coin(coin_id_pt),
                    })
                    save_paper_trades(paper_data)
                    st.success("✅ Bought " + str(round(coins_bought, 6)) + " " + pt_coin + " at $" + str(round(live_price, 4)) + " for $" + str(round(pt_amount, 2)))
                    st.info("🛑 SL: $" + str(round(sl_px, 4)) + " (-" + str(stop_loss_pct) + "%) · 🎯 TP: $" + str(round(tp_px, 4)) + " (+" + str(round(stop_loss_pct * take_profit_ratio, 1)) + "%) · Trailing stop enabled")
                    send_telegram("🤖 <b>PAPER TRADE: BUY</b>\nCoin: " + pt_coin + "\nPrice: $" + str(round(live_price, 4)) + "\nAmount: $" + str(round(pt_amount, 2)) + "\nSL: $" + str(round(sl_px, 4)) + "\nTP: $" + str(round(tp_px, 4)))
                    st.rerun()
            else:
                if pt_coin not in paper_positions:
                    st.error("No open position in " + pt_coin + "!")
                else:
                    pos = paper_positions[pt_coin]
                    sale_value = pos["coins"] * live_price
                    profit_usd = sale_value - pos["cost"]
                    profit_pct = (profit_usd / pos["cost"]) * 100
                    paper_data["balance"] += sale_value
                    paper_data["trades"].append({
                        "type": "SELL", "coin": pt_coin, "price": live_price,
                        "amount": sale_value, "coins": pos["coins"],
                        "date": str(datetime.now())[:19],
                        "profit_usd": profit_usd, "profit_pct": profit_pct,
                    })
                    del paper_data["positions"][pt_coin]
                    save_paper_trades(paper_data)
                    if profit_usd >= 0:
                        st.success("✅ Sold " + pt_coin + " for $" + str(round(sale_value, 2)) + " · Profit: +$" + str(round(profit_usd, 2)) + " (+" + str(round(profit_pct, 2)) + "%)")
                        send_telegram("🤖 <b>PAPER TRADE: SELL ✅</b>\nCoin: " + pt_coin + "\nProfit: +$" + str(round(profit_usd, 2)) + " (+" + str(round(profit_pct, 2)) + "%)")
                    else:
                        st.error("Sold " + pt_coin + " for $" + str(round(sale_value, 2)) + " · Loss: -$" + str(round(abs(profit_usd), 2)) + " (" + str(round(profit_pct, 2)) + "%)")
                        send_telegram("🤖 <b>PAPER TRADE: SELL ❌</b>\nCoin: " + pt_coin + "\nLoss: -$" + str(round(abs(profit_usd), 2)) + " (" + str(round(profit_pct, 2)) + "%)")
                    st.rerun()
        except Exception as e:
            st.error("Error: " + str(e))

    st.divider()
    st.subheader("📊 Performance by Coin")
    sell_trades_perf = [t for t in paper_trades if t["type"] == "SELL"]
    if sell_trades_perf:
        coin_stats = {}
        for t in sell_trades_perf:
            coin = t["coin"]
            if coin not in coin_stats:
                coin_stats[coin] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "best": 0.0, "worst": 0.0}
            coin_stats[coin]["trades"] += 1
            coin_stats[coin]["total_pnl"] += t["profit_usd"]
            if t["profit_usd"] > 0:
                coin_stats[coin]["wins"] += 1
                if t["profit_pct"] > coin_stats[coin]["best"]:
                    coin_stats[coin]["best"] = t["profit_pct"]
            else:
                coin_stats[coin]["losses"] += 1
                if t["profit_pct"] < coin_stats[coin]["worst"]:
                    coin_stats[coin]["worst"] = t["profit_pct"]
        perf_rows = []
        for coin, stats in coin_stats.items():
            win_rate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
            perf_rows.append({
                "Coin": coin,
                "Trades": stats["trades"],
                "Wins": stats["wins"],
                "Losses": stats["losses"],
                "Win Rate": str(round(win_rate, 1)) + "%",
                "Total P&L": ("+" if stats["total_pnl"] >= 0 else "") + "$" + str(round(stats["total_pnl"], 2)),
                "Best": "+" + str(round(stats["best"], 2)) + "%",
                "Worst": str(round(stats["worst"], 2)) + "%",
            })
        perf_df = pd.DataFrame(perf_rows).sort_values("Trades", ascending=False)
        st.dataframe(perf_df, use_container_width=True, hide_index=True)
        best_coin = max(coin_stats.items(), key=lambda x: x[1]["total_pnl"])
        worst_coin = min(coin_stats.items(), key=lambda x: x[1]["total_pnl"])
        if len(coin_stats) > 1:
            pc1, pc2 = st.columns(2)
            pc1.success("🏆 Best: **" + best_coin[0] + "** · +$" + str(round(best_coin[1]["total_pnl"], 2)))
            pc2.error("⚠️ Worst: **" + worst_coin[0] + "** · " + ("+" if worst_coin[1]["total_pnl"] >= 0 else "") + "$" + str(round(worst_coin[1]["total_pnl"], 2)))
    else:
        st.info("Performance per coin appears after you close some trades.")

    # ── EQUITY CURVE ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📈 Equity Curve")
    sell_trades_eq = [t for t in paper_trades if t["type"] == "SELL"]
    if sell_trades_eq:
        sorted_sells = sorted(sell_trades_eq, key=lambda x: x["date"])
        running_balance = 10000.0
        eq_dates = ["Start"]
        eq_balances = [running_balance]
        for t in sorted_sells:
            running_balance += t["profit_usd"]
            eq_dates.append(t["date"][5:16])
            eq_balances.append(round(running_balance, 2))
        import plotly.graph_objects as go
        eq_fig = go.Figure()
        eq_fig.add_trace(go.Scatter(
            x=eq_dates, y=eq_balances, mode="lines+markers",
            line=dict(color="#16a34a" if running_balance >= 10000 else "#dc2626", width=3),
            marker=dict(size=6),
            fill="tozeroy", fillcolor="rgba(22,163,74,0.1)" if running_balance >= 10000 else "rgba(220,38,38,0.1)",
            name="Account Balance"
        ))
        eq_fig.add_hline(y=10000, line_dash="dash", line_color="gray",
                         annotation_text="Starting balance", annotation_position="right")
        eq_fig.update_layout(
            template="plotly_dark", height=380,
            yaxis_title="Account Balance ($)", xaxis_title="",
            showlegend=False,
            margin=dict(l=20, r=20, t=30, b=20),
        )
        st.plotly_chart(eq_fig, use_container_width=True)
        change_total = running_balance - 10000
        change_pct = (change_total / 10000) * 100
        eq_c1, eq_c2, eq_c3 = st.columns(3)
        eq_c1.metric("Starting", "$10,000")
        eq_c2.metric("Current (realized)", "$" + str(round(running_balance, 2)),
                     delta=("+" if change_total >= 0 else "") + "$" + str(round(change_total, 2)))
        eq_c3.metric("Return", ("+" if change_pct >= 0 else "") + str(round(change_pct, 2)) + "%")
        peak = max(eq_balances)
        drawdown_from_peak = ((running_balance - peak) / peak) * 100
        if drawdown_from_peak < -5:
            st.warning("📉 Currently " + str(round(abs(drawdown_from_peak), 2)) + "% below peak of $" + str(round(peak, 2)))

        # ── Calendar Heatmap ─────────────────────────────────────────────
        st.markdown("**📅 Daily P&L Calendar**")
        daily_pnl = {}
        for t in sell_trades_eq:
            day = t["date"][:10]
            daily_pnl[day] = daily_pnl.get(day, 0) + t["profit_usd"]
        if daily_pnl:
            sorted_days = sorted(daily_pnl.keys())
            cal_dates = sorted_days
            cal_values = [daily_pnl[d] for d in sorted_days]
            cal_colors = []
            for v in cal_values:
                if v >= 50: cal_colors.append("#16a34a")
                elif v > 0: cal_colors.append("#86efac")
                elif v == 0: cal_colors.append("#6b7280")
                elif v > -50: cal_colors.append("#fca5a5")
                else: cal_colors.append("#dc2626")
            cal_fig = go.Figure(data=[go.Bar(
                x=cal_dates, y=cal_values,
                marker_color=cal_colors,
                text=["+$" + str(round(v, 2)) if v >= 0 else "-$" + str(round(abs(v), 2)) for v in cal_values],
                textposition="outside",
            )])
            cal_fig.update_layout(
                template="plotly_dark", height=300,
                yaxis_title="Daily P&L ($)", xaxis_title="",
                showlegend=False, margin=dict(l=20, r=20, t=20, b=20),
            )
            cal_fig.add_hline(y=0, line_color="gray", line_width=1)
            st.plotly_chart(cal_fig, use_container_width=True)
            green_days = len([v for v in cal_values if v > 0])
            red_days = len([v for v in cal_values if v < 0])
            best_day = max(daily_pnl.items(), key=lambda x: x[1])
            worst_day = min(daily_pnl.items(), key=lambda x: x[1])
            cal_c1, cal_c2, cal_c3, cal_c4 = st.columns(4)
            cal_c1.metric("🟢 Green Days", green_days)
            cal_c2.metric("🔴 Red Days", red_days)
            cal_c3.metric("Best Day", best_day[0][5:], delta="+$" + str(round(best_day[1], 2)))
            cal_c4.metric("Worst Day", worst_day[0][5:], delta=("+" if worst_day[1] >= 0 else "") + "$" + str(round(worst_day[1], 2)))
    else:
        st.info("Equity curve will appear after your first closed trade.")

    st.divider()
    st.subheader("📜 Paper Trade History")
    if paper_trades:
        sell_trades_p = [t for t in paper_trades if t["type"] == "SELL"]
        if sell_trades_p:
            total_paper_profit = sum(t["profit_usd"] for t in sell_trades_p)
            paper_wins = [t for t in sell_trades_p if t["profit_usd"] > 0]
            paper_win_rate = (len(paper_wins) / len(sell_trades_p) * 100) if sell_trades_p else 0
            h1, h2, h3 = st.columns(3)
            h1.metric("Total Paper P&L", ("+" if total_paper_profit >= 0 else "") + "$" + str(round(total_paper_profit, 2)))
            h2.metric("Paper Win Rate", str(round(paper_win_rate, 1)) + "%")
            h3.metric("Completed Trades", str(len(sell_trades_p)))
        trade_display = []
        for t in reversed(paper_trades):
            trade_display.append({
                "Date": t["date"], "Type": t["type"], "Coin": t["coin"],
                "Price": "$" + str(round(t["price"], 4)),
                "Amount": "$" + str(round(t["amount"], 2)),
                "P&L": ("+" if t["profit_usd"] >= 0 else "") + "$" + str(round(t["profit_usd"], 2)) if t["type"] == "SELL" else "-",
            })
        st.dataframe(pd.DataFrame(trade_display), use_container_width=True)
    else:
        st.info("No paper trades yet. Place your first trade above!")

st.divider()
st.caption("⚠️ For educational purposes only. Not financial advice.")
