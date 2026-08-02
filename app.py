import json
import os
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
from dateutil import parser
import feedparser
from google import genai
from google.genai import types
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

from alert_engine import (
    fetch_current_price,
    fetch_current_prices,
    process_alerts,
    send_ntfy_notification,
)
from finance_storage import FinanceStorage

# Sayfa Yapılandırması (Mobil Uyumluluk Optimizasyonu)
st.set_page_config(
    page_title="Aylooper Finans & AI Paneli",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="auto",
)

# Masaüstünü etkilemeden mobil ekranlarda yazıları ve boşlukları küçültür.
st.markdown(
    """
    <style>
    /* Masaüstü varsayılanları */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }

    [data-testid="stSidebar"] > div:first-child {
        overflow-y: auto;
        max-height: 100vh;
        padding-bottom: 80px;
    }

    /* Yalnızca telefon ve dar ekranlar */
    @media screen and (max-width: 768px) {
        html {
            font-size: 12px !important;
        }

        .block-container {
            padding-top: 0.45rem !important;
            padding-left: 0.65rem !important;
            padding-right: 0.65rem !important;
            padding-bottom: 1.5rem !important;
        }

        /* Ana başlıklar */
        h1 {
            font-size: 1.55rem !important;
            line-height: 1.15 !important;
            margin-bottom: 0.45rem !important;
        }
        h2 {
            font-size: 1.30rem !important;
            line-height: 1.20 !important;
        }
        h3 {
            font-size: 1.15rem !important;
            line-height: 1.20 !important;
        }

        /* Normal metinler, etiketler ve form alanları */
        p,
        label,
        [data-testid="stMarkdownContainer"],
        [data-testid="stCaptionContainer"],
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        [data-baseweb="select"] *,
        [data-baseweb="input"] input,
        button {
            font-size: 0.92rem !important;
        }

        /* Metrikler */
        [data-testid="stMetricLabel"] {
            font-size: 0.82rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.65rem !important;
            line-height: 1.05 !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.82rem !important;
        }

        /* Sekmeler yatay kayabilsin ve daha az yer kaplasın */
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.12rem !important;
            overflow-x: auto !important;
            scrollbar-width: thin;
        }
        .stTabs [data-baseweb="tab"] {
            min-width: max-content !important;
            min-height: 2.35rem !important;
            padding: 0.28rem 0.48rem !important;
            font-size: 0.82rem !important;
        }

        /* Buton, expander ve bilgi kutuları */
        .stButton button,
        .stDownloadButton button,
        .stFormSubmitButton button {
            min-height: 2.35rem !important;
            padding: 0.30rem 0.58rem !important;
        }
        [data-testid="stExpander"] summary {
            font-size: 0.88rem !important;
        }
        [data-testid="stAlert"] {
            padding: 0.55rem 0.65rem !important;
        }

        /* Sidebar mobilde daha kompakt */
        [data-testid="stSidebar"] {
            min-width: 238px !important;
            max-width: 238px !important;
        }
        [data-testid="stSidebar"] * {
            font-size: 0.90rem !important;
        }
        [data-testid="stSidebar"] h1 {
            font-size: 1.28rem !important;
        }
        [data-testid="stSidebar"] h2 {
            font-size: 1.15rem !important;
        }
        [data-testid="stSidebar"] h3 {
            font-size: 1.05rem !important;
        }

        /* Tablolar */
        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            font-size: 0.78rem !important;
        }
    }

    /* Çok dar telefonlar için bir kademe daha küçük */
    @media screen and (max-width: 430px) {
        html {
            font-size: 11px !important;
        }
        .block-container {
            padding-left: 0.45rem !important;
            padding-right: 0.45rem !important;
        }
        h1 {
            font-size: 1.42rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.48rem !important;
        }
    }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("📈 Aylooper Finans & Yapay Zeka Paneli")

# ---------------------------------------------------------
# GİZLİ ANAHTARLAR, ERİŞİM VE KALICI VERİ KATMANI
# ---------------------------------------------------------


def get_secret(name, default=None):
  """Streamlit secrets veya ortam değişkeninden güvenli değer okur."""
  try:
    return st.secrets.get(name, os.getenv(name, default))
  except Exception:
    return os.getenv(name, default)


FIXED_GEMINI_API_KEY = get_secret("GEMINI_API_KEY", "")
GEMINI_MODEL = get_secret("GEMINI_MODEL", "gemini-3.6-flash")
SUPABASE_URL = get_secret("SUPABASE_URL", "")
SUPABASE_KEY = get_secret("SUPABASE_SERVICE_ROLE_KEY", "")
NTFY_TOPIC = get_secret("NTFY_TOPIC", "")
NTFY_SERVER = get_secret("NTFY_SERVER", "https://ntfy.sh")
APP_PASSWORD = get_secret("APP_PASSWORD", "")


@st.cache_resource
def get_storage():
  return FinanceStorage(
      supabase_url=SUPABASE_URL,
      supabase_key=SUPABASE_KEY,
  )


storage = get_storage()


# İsteğe bağlı basit parola kapısı. APP_PASSWORD boşsa uygulama doğrudan açılır.
def require_app_password():
  if not APP_PASSWORD:
    return
  if st.session_state.get("aylooper_authenticated"):
    return

  st.subheader("🔐 Aylooper Finans Girişi")
  entered = st.text_input("Uygulama parolası", type="password")
  if st.button("Giriş Yap", type="primary"):
    if entered == APP_PASSWORD:
      st.session_state.aylooper_authenticated = True
      st.rerun()
    else:
      st.error("Parola hatalı.")
  st.stop()


require_app_password()

DEFAULT_WATCHLIST = [
    "KONTR.IS",
    "THYAO.IS",
    "GARAN.IS",
    "AAPL",
    "NVDA",
    "BTC-USD",
    "ETH-USD",
]

# Repo ile gelen eski listeyi ilk Supabase kurulumunda otomatik devral.
try:
  legacy_path = "takip_listesi.json"
  if os.path.exists(legacy_path):
    with open(legacy_path, "r", encoding="utf-8") as legacy_file:
      legacy_watchlist = json.load(legacy_file)
    if isinstance(legacy_watchlist, list) and legacy_watchlist:
      DEFAULT_WATCHLIST = [str(item).upper() for item in legacy_watchlist]
except Exception:
  pass

if "watch_list" not in st.session_state:
  st.session_state.watch_list = storage.get_watchlist(DEFAULT_WATCHLIST)

# ---------------------------------------------------------
# TEMATİK SEKTÖR / DİKEY VERİ TABANI (BIST & NASDAQ)
# ---------------------------------------------------------
THEMATIC_SECTORS = {
    "🚀 Uzay ve Havacılık": [
        {"symbol": "ASTS", "name": "AST SpaceMobile (Global)"},
        {"symbol": "RKLB", "name": "Rocket Lab USA (Global)"},
        {"symbol": "BA", "name": "Boeing (Global)"},
        {"symbol": "LMT", "name": "Lockheed Martin (Global)"},
        {"symbol": "AYES.IS", "name": "Ayesaş / BIST Havacılık"},
        {"symbol": "CLEEN", "name": "Clean Earth / Defense"},
    ],
    "🧬 Biyoteknoloji": [
        {"symbol": "MRNA", "name": "Moderna (Global)"},
        {"symbol": "PFE", "name": "Pfizer (Global)"},
        {"symbol": "BNTX", "name": "BioNTech (Global)"},
        {"symbol": "GEPH.IS", "name": "Gen İlaç (BIST)"},
        {"symbol": "SEKFK.IS", "name": "Sağlık Odaklı Varlıklar"},
    ],
    "🤖 Fiziksel Yapay Zeka & Robotik": [
        {"symbol": "NVDA", "name": "NVIDIA (AI Donanım)"},
        {"symbol": "TSLA", "name": "Tesla (Robotaksi & Optimus)"},
        {"symbol": "ISCTR.IS", "name": "İş Bankası (Teknoloji Yatırımları)"},
        {"symbol": "KONTR.IS", "name": "Kontrolmatik (Robotik & Enerji Otomasyonu)"},
        {"symbol": "ABB", "name": "ABB Ltd (Endüstriyel Robotik)"},
    ],
}

# ---------------------------------------------------------
# CANLI KÜRESEL MAKROEKONOMİK TAKVİM
# ---------------------------------------------------------
# Takvim verisi macro_calendar.py içinden FMP stable API ile alınır.
# Başarılı yanıtlar 1 saat önbellekte tutulur; düşük önem olayları gösterilmez.

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------
# CANLI HİSSE ARAMA & PİVOT & KRİPTO YARDIMCILARI
# ---------------------------------------------------------


def search_ticker_global(query):
  if not query or len(query.strip()) < 1:
    return []

  query_clean = query.strip().upper()
  results = []

  try:
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query_clean)}&quotesCount=10"
    resp = requests.get(url, headers=headers, timeout=4)
    if resp.status_code == 200:
      data = resp.json()
      if "quotes" in data:
        for item in data.get("quotes", []):
          symbol = item.get("symbol", "")
          shortname = item.get("shortname") or item.get("longname") or symbol
          exch = item.get("exchDisp", "")
          if symbol:
            results.append(f"{symbol} | {shortname} ({exch})")
  except Exception:
    pass

  if not results:
    if not query_clean.endswith(".IS") and len(query_clean) <= 6:
      results.append(f"{query_clean}.IS | {query_clean} (BIST)")
    results.append(f"{query_clean} | {query_clean} (Global/US)")

  return results


def fetch_rss_news_sorted(query_term):
  try:
    encoded_query = urllib.parse.quote(query_term)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=tr&gl=TR&ceid=TR:tr"
    resp = requests.get(rss_url, headers=headers, timeout=5)
    feed = feedparser.parse(resp.content)

    news = []
    for entry in feed.entries[:15]:
      pub_raw = entry.get("published", "")
      dt_obj = None
      dt_str = "Tarih Belirtilmemiş"
      if pub_raw:
        try:
          dt_obj = parser.parse(pub_raw)
          dt_str = dt_obj.strftime("%d.%m.%Y %H:%M")
        except Exception:
          pass
      news.append({
          "title": entry.title,
          "link": entry.link,
          "source": entry.get("source", {}).get("title", "Finans Basını"),
          "published_str": dt_str,
          "published_dt": dt_obj,
      })
    news.sort(
        key=lambda x: (
            x["published_dt"]
            if x["published_dt"] is not None
            else parser.parse("1970-01-01")
        ),
        reverse=True,
    )
    return news
  except Exception:
    return []


def calculate_pivot_points(ticker_symbol, timeframe):
  try:
    ticker = yf.Ticker(ticker_symbol)

    if timeframe == "Günlük":
      df = ticker.history(period="1mo", interval="1d")
    elif timeframe == "Haftalık":
      df = ticker.history(period="6mo", interval="1wk")
    else:  # Aylık
      df = ticker.history(period="2y", interval="1mo")

    if df.empty or len(df) < 2:
      return None

    last_candle = df.iloc[-2]
    high, low, close = (
        last_candle["High"],
        last_candle["Low"],
        last_candle["Close"],
    )
    pivot = (high + low + close) / 3

    return {
        "Pivot (P)": round(pivot, 2),
        "Direnç 1 (R1)": round((2 * pivot) - low, 2),
        "Direnç 2 (R2)": round(pivot + (high - low), 2),
        "Direnç 3 (R3)": round(high + 2 * (pivot - low), 2),
        "Destek 1 (S1)": round((2 * pivot) - high, 2),
        "Destek 2 (S2)": round(pivot - (high - low), 2),
        "Destek 3 (S3)": round(low - 2 * (high - pivot), 2),
    }
  except Exception:
    return None



# ---------------------------------------------------------
# TRADINGVIEW GRAFİK YARDIMCILARI
# ---------------------------------------------------------
# Borsa İstanbul (.IS) sembollerinde TradingView dış-site veri lisansı
# nedeniyle Plotly kullanılır. Diğer desteklenen piyasalarda doğrudan
# TradingView Advanced Chart açılır.

TV_SYMBOL_OVERRIDES = {
    # NASDAQ
    "AAPL": "NASDAQ:AAPL",
    "NVDA": "NASDAQ:NVDA",
    "TSLA": "NASDAQ:TSLA",
    "ASTS": "NASDAQ:ASTS",
    "RKLB": "NASDAQ:RKLB",
    "MRNA": "NASDAQ:MRNA",
    "BNTX": "NASDAQ:BNTX",
    # NYSE
    "BA": "NYSE:BA",
    "LMT": "NYSE:LMT",
    "PFE": "NYSE:PFE",
    "ABB": "NYSE:ABB",
}

YAHOO_EXCHANGE_TO_TV = {
    "NMS": "NASDAQ",
    "NGM": "NASDAQ",
    "NCM": "NASDAQ",
    "NAS": "NASDAQ",
    "NYQ": "NYSE",
    "ASE": "AMEX",
    "PCX": "AMEX",
    "BTS": "CBOE",
    "PNK": "OTC",
    "OBB": "OTC",
    "LSE": "LSE",
    "TOR": "TSX",
    "VAN": "TSXV",
    "GER": "XETR",
    "FRA": "FWB",
    "PAR": "EURONEXT",
    "AMS": "EURONEXT",
    "BRU": "EURONEXT",
    "MIL": "MIL",
    "SWX": "SIX",
    "HKG": "HKEX",
    "JPX": "TSE",
    "ASX": "ASX",
}

YAHOO_SUFFIX_TO_TV = {
    ".L": "LSE",
    ".TO": "TSX",
    ".V": "TSXV",
    ".DE": "XETR",
    ".F": "FWB",
    ".PA": "EURONEXT",
    ".AS": "EURONEXT",
    ".BR": "EURONEXT",
    ".MI": "MIL",
    ".SW": "SIX",
    ".HK": "HKEX",
    ".T": "TSE",
    ".AX": "ASX",
}


def requires_plotly_chart(symbol):
  """TradingView dış-site lisansı nedeniyle yerel grafik gereken semboller."""
  return symbol.strip().upper().endswith(".IS")


def tradingview_interval(timeframe):
  return {
      "Günlük": "D",
      "Haftalık": "W",
      "Aylık": "M",
  }.get(timeframe, "D")


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_tradingview_symbol(yahoo_symbol):
  """Yahoo Finance sembolünü TradingView EXCHANGE:TICKER biçimine çevirir."""
  symbol = yahoo_symbol.strip().upper()

  if requires_plotly_chart(symbol):
    return None

  # Yahoo kripto sembolü: BTC-USD -> BINANCE:BTCUSDT
  if symbol.endswith("-USD"):
    base = symbol[:-4].replace("-", "")
    return f"BINANCE:{base}USDT"

  # Yahoo döviz çifti: EURUSD=X -> FX_IDC:EURUSD
  if symbol.endswith("=X"):
    pair = symbol[:-2].replace("-", "")
    return f"FX_IDC:{pair}"

  if symbol in TV_SYMBOL_OVERRIDES:
    return TV_SYMBOL_OVERRIDES[symbol]

  for suffix, tv_exchange in YAHOO_SUFFIX_TO_TV.items():
    if symbol.endswith(suffix):
      ticker = symbol[:-len(suffix)]
      return f"{tv_exchange}:{ticker}"

  try:
    fast_info = yf.Ticker(symbol).fast_info
    try:
      yahoo_exchange = fast_info["exchange"]
    except Exception:
      yahoo_exchange = getattr(fast_info, "exchange", None)

    tv_exchange = YAHOO_EXCHANGE_TO_TV.get(str(yahoo_exchange).upper())
    if tv_exchange:
      tv_ticker = symbol.replace("-", ".")
      return f"{tv_exchange}:{tv_ticker}"
  except Exception:
    pass

  # Yahoo borsa kodu çözülemezse ABD hissesi için NASDAQ varsayımı.
  return f"NASDAQ:{symbol.replace('-', '.')}"


def render_tradingview_chart(yahoo_symbol, timeframe="Günlük", height=720):
  """TradingView Advanced Chart widget'ını Streamlit içinde gösterir."""
  tv_symbol = resolve_tradingview_symbol(yahoo_symbol)
  if not tv_symbol:
    return False

  config = {
      "autosize": True,
      "symbol": tv_symbol,
      "interval": tradingview_interval(timeframe),
      "timezone": "Europe/Istanbul",
      "theme": "light",
      "style": "1",
      "locale": "tr",
      "allow_symbol_change": True,
      "calendar": False,
      "details": True,
      "hide_side_toolbar": False,
      "hide_top_toolbar": False,
      "hide_legend": False,
      "hide_volume": False,
      "hotlist": False,
      "save_image": True,
      "withdateranges": True,
      "support_host": "https://www.tradingview.com",
  }

  safe_config = json.dumps(config, ensure_ascii=False)
  safe_link_symbol = tv_symbol.replace(":", "-").replace(".", "-")

  widget_html = f"""
  <!doctype html>
  <html lang="tr">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }}
        .tradingview-widget-container {{ width: 100%; height: {height - 6}px; }}
        .tradingview-widget-container__widget {{ width: 100%; height: calc(100% - 26px); }}
        .tradingview-widget-copyright {{
          height: 20px;
          font: 11px Arial, sans-serif;
          padding-top: 3px;
        }}
        .tradingview-widget-copyright a {{ color: #2962ff; text-decoration: none; }}
      </style>
    </head>
    <body>
      <div class="tradingview-widget-container">
        <div class="tradingview-widget-container__widget"></div>
        <div class="tradingview-widget-copyright">
          <a href="https://www.tradingview.com/symbols/{safe_link_symbol}/"
             rel="noopener nofollow" target="_blank">{tv_symbol} grafiği</a>
          <span> TradingView tarafından sağlanır</span>
        </div>
        <script type="text/javascript"
                src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
                async>{safe_config}</script>
      </div>
    </body>
  </html>
  """

  components.html(widget_html, height=height, scrolling=False)
  return True


# ---------------------------------------------------------
# GELİŞMİŞ PLOTLY TEKNİK GRAFİK YARDIMCILARI
# ---------------------------------------------------------
# Bu grafik yalnızca TradingView dış-site lisansı nedeniyle açılamayan
# Borsa İstanbul (.IS) sembollerinde kullanılır. Plotly araç çubuğundaki
# çizim düğmeleriyle kullanıcı grafiğin üzerine manuel trend çizgisi,
# dikdörtgen ve serbest çizgi ekleyebilir.

CHART_RANGE_OPTIONS = {
    "1 Ay": ("1mo", "1h"),
    "3 Ay": ("3mo", "1d"),
    "6 Ay": ("6mo", "1d"),
    "1 Yıl": ("1y", "1d"),
    "2 Yıl": ("2y", "1wk"),
    "5 Yıl": ("5y", "1wk"),
}


@st.cache_data(ttl=300, show_spinner=False)
def get_chart_history(ticker_symbol, range_label):
  """Teknik grafik için OHLCV fiyat geçmişini getirir."""
  period, interval = CHART_RANGE_OPTIONS.get(range_label, ("6mo", "1d"))

  try:
    df = yf.Ticker(ticker_symbol).history(
        period=period,
        interval=interval,
        auto_adjust=False,
    )
  except Exception:
    return pd.DataFrame()

  if df is None or df.empty:
    return pd.DataFrame()

  needed = ["Open", "High", "Low", "Close", "Volume"]
  for column in needed:
    if column not in df.columns:
      if column == "Volume":
        df[column] = 0
      else:
        return pd.DataFrame()

  df = df[needed].copy()
  df = df.dropna(subset=["Open", "High", "Low", "Close"])

  # Plotly ve farklı borsaların saat dilimi verilerinin sorunsuz çalışması için.
  try:
    if getattr(df.index, "tz", None) is not None:
      df.index = df.index.tz_localize(None)
  except Exception:
    pass

  return df


def add_technical_indicators(df):
  """EMA ve Bollinger Bantlarını hesaplar."""
  result = df.copy()
  result["EMA20"] = result["Close"].ewm(span=20, adjust=False).mean()
  result["EMA50"] = result["Close"].ewm(span=50, adjust=False).mean()

  result["BB_MID"] = result["Close"].rolling(window=20).mean()
  rolling_std = result["Close"].rolling(window=20).std()
  result["BB_UPPER"] = result["BB_MID"] + (rolling_std * 2)
  result["BB_LOWER"] = result["BB_MID"] - (rolling_std * 2)
  return result


def render_technical_chart(
    ticker_symbol,
    range_label,
    chart_type,
    pivot_timeframe,
    selected_indicators,
    currency,
):
  """Mum/çizgi, hacim, pivot ve indikatörleri tek interaktif grafikte gösterir."""
  df = get_chart_history(ticker_symbol, range_label)
  if df.empty:
    st.warning("Grafik verisi alınamadı. Birkaç dakika sonra tekrar deneyin.")
    return

  df = add_technical_indicators(df)
  show_volume = "Hacim" in selected_indicators

  if show_volume:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.76, 0.24],
    )
    price_row = 1
  else:
    fig = make_subplots(rows=1, cols=1)
    price_row = 1

  if chart_type == "Mum":
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Fiyat",
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
        ),
        row=price_row,
        col=1,
    )
  else:
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Close"],
            mode="lines",
            name="Kapanış",
            line=dict(width=2),
        ),
        row=price_row,
        col=1,
    )

  if "EMA 20" in selected_indicators:
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA20"],
            mode="lines",
            name="EMA 20",
            line=dict(width=1.5),
        ),
        row=price_row,
        col=1,
    )

  if "EMA 50" in selected_indicators:
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA50"],
            mode="lines",
            name="EMA 50",
            line=dict(width=1.5),
        ),
        row=price_row,
        col=1,
    )

  if "Bollinger Bantları" in selected_indicators:
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["BB_UPPER"],
            mode="lines",
            name="Bollinger Üst",
            line=dict(width=1, dash="dot"),
        ),
        row=price_row,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["BB_LOWER"],
            mode="lines",
            name="Bollinger Alt",
            line=dict(width=1, dash="dot"),
            fill="tonexty",
            fillcolor="rgba(100, 116, 139, 0.08)",
        ),
        row=price_row,
        col=1,
    )

  if "Pivot Seviyeleri" in selected_indicators:
    pivot_data = calculate_pivot_points(ticker_symbol, pivot_timeframe)
    if pivot_data:
      pivot_lines = [
          ("R3", pivot_data.get("Direnç 3 (R3)"), "#991b1b"),
          ("R2", pivot_data.get("Direnç 2 (R2)"), "#dc2626"),
          ("R1", pivot_data.get("Direnç 1 (R1)"), "#ef4444"),
          ("P", pivot_data.get("Pivot (P)"), "#64748b"),
          ("S1", pivot_data.get("Destek 1 (S1)"), "#22c55e"),
          ("S2", pivot_data.get("Destek 2 (S2)"), "#16a34a"),
          ("S3", pivot_data.get("Destek 3 (S3)"), "#15803d"),
      ]

      for label, value, color in pivot_lines:
        if value is None:
          continue
        fig.add_hline(
            y=float(value),
            row=price_row,
            col=1,
            line_dash="dot",
            line_width=1.2,
            line_color=color,
            annotation_text=f"{label} {float(value):.2f}",
            annotation_position="top right",
            annotation_font_color=color,
            annotation_font_size=11,
        )

  if show_volume:
    volume_colors = [
        "rgba(22, 163, 74, 0.55)" if close >= open_price
        else "rgba(220, 38, 38, 0.55)"
        for close, open_price in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["Volume"],
            name="Hacim",
            marker_color=volume_colors,
        ),
        row=2,
        col=1,
    )
    fig.update_yaxes(title_text="Hacim", row=2, col=1, side="right")

  chart_height = 700 if show_volume else 610
  fig.update_layout(
      title=f"{ticker_symbol} — {range_label}",
      height=chart_height,
      margin=dict(l=8, r=18, t=55, b=8),
      template="plotly_white",
      hovermode="x unified",
      showlegend=True,
      legend=dict(
          orientation="h",
          yanchor="bottom",
          y=1.02,
          xanchor="left",
          x=0,
      ),
      dragmode="pan",
      newshape=dict(
          line=dict(color="#7c3aed", width=2),
          fillcolor="rgba(124, 58, 237, 0.08)",
      ),
  )

  fig.update_xaxes(
      rangeslider_visible=False,
      showgrid=True,
      gridcolor="rgba(148, 163, 184, 0.18)",
  )
  fig.update_yaxes(
      title_text=currency or "Fiyat",
      showgrid=True,
      gridcolor="rgba(148, 163, 184, 0.18)",
      side="right",
      row=price_row,
      col=1,
  )

  st.caption(
      "Grafiğin sağ üst araç çubuğundan çizgi, serbest çizim veya dikdörtgen "
      "ekleyebilirsin. Çizimleri silmek için silgi simgesini kullan."
  )

  st.plotly_chart(
      fig,
      use_container_width=True,
      key=f"technical_chart_{ticker_symbol}_{range_label}_{chart_type}_{pivot_timeframe}",
      config={
          "displaylogo": False,
          "scrollZoom": True,
          "responsive": True,
          "modeBarButtonsToAdd": [
              "drawline",
              "drawopenpath",
              "drawrect",
              "eraseshape",
          ],
      },
  )


def get_crypto_yf_stats(symbol="BTC-USD"):
  yf_symbol = symbol.replace("USDT", "-USD")
  try:
    t = yf.Ticker(yf_symbol)
    fi = t.fast_info
    price = fi.get("lastPrice", 0)
    prev_close = fi.get("previousClose", 0)
    if price and prev_close:
      change = ((price - prev_close) / prev_close) * 100
      return {"lastPrice": price, "priceChangePercent": change}
  except Exception:
    pass

  try:
    df = yf.download(yf_symbol, period="2d", interval="1d", progress=False)
    if not df.empty and len(df) >= 2:
      price = float(df["Close"].iloc[-1])
      prev_close = float(df["Close"].iloc[-2])
      change = ((price - prev_close) / prev_close) * 100
      return {"lastPrice": price, "priceChangePercent": change}
  except Exception:
    pass

  return None


@st.cache_data(ttl=50, show_spinner=False)
def get_market_snapshot(symbol):
  """Seçili varlık için fiyat, önceki kapanış ve günlük değişimi getirir."""
  symbol = symbol.strip().upper()
  current_price = fetch_current_price(symbol)
  previous_close = None

  try:
    fast_info = yf.Ticker(symbol).fast_info
    try:
      previous_close = fast_info["previousClose"]
    except Exception:
      previous_close = getattr(fast_info, "previousClose", None)
    previous_close = float(previous_close) if previous_close else None
  except Exception:
    previous_close = None

  if previous_close is None:
    try:
      daily = yf.Ticker(symbol).history(period="5d", interval="1d")
      closes = daily["Close"].dropna() if daily is not None and not daily.empty else []
      if len(closes) >= 2:
        previous_close = float(closes.iloc[-2])
      elif len(closes) == 1:
        previous_close = float(closes.iloc[-1])
    except Exception:
      previous_close = None

  if current_price is None:
    return {
        "current_price": None,
        "previous_close": previous_close,
        "price_change": 0.0,
        "percent_change": 0.0,
    }

  price_change = (
      float(current_price) - float(previous_close)
      if previous_close not in (None, 0)
      else 0.0
  )
  percent_change = (
      (price_change / float(previous_close)) * 100
      if previous_close not in (None, 0)
      else 0.0
  )
  return {
      "current_price": float(current_price),
      "previous_close": previous_close,
      "price_change": price_change,
      "percent_change": percent_change,
  }


def istanbul_now_text():
  return datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M:%S")


# ---------------------------------------------------------
# SOL MENÜ - HİSSE YÖNETİMİ & TEMATİK DİKEYLER
# ---------------------------------------------------------
st.sidebar.header("⚙️ Hisse Yönetimi")

search_input = st.sidebar.text_input("Hisse Arayın (Örn: THYAO, NVDA, BTC-USD):")

if search_input:
  suggestions = search_ticker_global(search_input)
  if suggestions:
    selected_suggestion = st.sidebar.selectbox(
        "Arama Sonuçları:", suggestions
    )
    ticker_to_add = selected_suggestion.split(" | ")[0].strip()

    if st.sidebar.button("➕ Listeye Ekle", key="add_btn"):
      if ticker_to_add not in st.session_state.watch_list:
        if storage.add_watchlist_symbol(ticker_to_add):
          st.session_state.watch_list.append(ticker_to_add)
          st.sidebar.success(f"{ticker_to_add} eklendi!")
          st.rerun()
        else:
          st.sidebar.error(f"Kayıt başarısız: {storage.last_error}")

st.sidebar.markdown("---")
selected_stock = st.sidebar.selectbox(
    "Takip Listenizden Seçin:", st.session_state.watch_list
)

if st.sidebar.button("❌ Seçili Hisseyi Çıkar"):
  if len(st.session_state.watch_list) > 1:
    if storage.remove_watchlist_symbol(selected_stock):
      st.session_state.watch_list.remove(selected_stock)
      st.sidebar.warning(
          f"{selected_stock} listeden çıkarıldı. Günlük ve alarm geçmişi korunuyor."
      )
      st.rerun()
    else:
      st.sidebar.error(f"Silme başarısız: {storage.last_error}")
  else:
    st.sidebar.error("Listenizde en az 1 hisse kalmalıdır.")

st.sidebar.markdown("---")

# Tematik Dikey Filtre Seçimi
st.sidebar.subheader("🎯 Tematik Dikey Filtreler")
selected_sector_key = st.sidebar.selectbox(
    "Sektör Dikey Seçin:", ["Özel Liste (Manuel)"] + list(THEMATIC_SECTORS.keys())
)

if selected_sector_key != "Özel Liste (Manuel)":
  sector_items = THEMATIC_SECTORS[selected_sector_key]
  st.sidebar.markdown(f"**{selected_sector_key} Hisseleri:**")
  sec_choice = st.sidebar.selectbox(
      "Dikey İçi Şirket Seçin:", [i["symbol"] + " - " + i["name"] for i in sector_items]
  )
  quick_add_ticker = sec_choice.split(" - ")[0].strip()
  if st.sidebar.button("➕ Dikey Hisseyi Listeye Ekle"):
    if quick_add_ticker not in st.session_state.watch_list:
      if storage.add_watchlist_symbol(quick_add_ticker):
        st.session_state.watch_list.append(quick_add_ticker)
        st.sidebar.success(f"{quick_add_ticker} eklendi!")
        st.rerun()
      else:
        st.sidebar.error(f"Kayıt başarısız: {storage.last_error}")

st.sidebar.markdown("---")
if storage.is_supabase:
  st.sidebar.success("☁️ Kalıcı veri: Supabase aktif")
else:
  st.sidebar.warning(
      "💾 Yerel kayıt modu aktif. Supabase kurulana kadar bulut yeniden "
      "başlatmalarında kayıtlar kaybolabilir."
  )
if FIXED_GEMINI_API_KEY:
  st.sidebar.success("🤖 Gemini API aktif")
else:
  st.sidebar.info("🤖 Gemini API anahtarı tanımlı değil")
if NTFY_TOPIC:
  st.sidebar.success("🔔 ntfy bildirimi aktif")
else:
  st.sidebar.info("🔕 ntfy konusu henüz tanımlanmadı")

# ---------------------------------------------------------
# GEMINI ANALİZ FONKSİYONU
# ---------------------------------------------------------
import time


def ask_gemini_analysis(prompt, system_instruction):
  if not FIXED_GEMINI_API_KEY:
    return "Gemini API anahtarı tanımlı değil."

  max_retries = 3
  for attempt in range(max_retries):
    try:
      client = genai.Client(api_key=FIXED_GEMINI_API_KEY)
      response = client.models.generate_content(
          model=GEMINI_MODEL,
          contents=prompt,
          config=types.GenerateContentConfig(
              system_instruction=system_instruction,
          ),
      )
      return response.text or "Gemini boş yanıt döndürdü."
    except Exception as exc:
      error_text = str(exc)
      retryable = any(code in error_text for code in ("429", "RESOURCE_EXHAUSTED", "503"))
      if retryable and attempt < max_retries - 1:
        time.sleep(5 * (attempt + 1))
        continue
      if retryable:
        return "Kota veya servis yoğunluğu hatası: Lütfen birkaç dakika sonra tekrar deneyin."
      return f"Hata oluştu: {error_text}"


def optional_price(value):
  try:
    number = float(value)
    return number if number > 0 else None
  except (TypeError, ValueError):
    return None


def parse_tags(tags_text):
  return [item.strip() for item in str(tags_text).split(",") if item.strip()]


def tags_to_text(tags):
  if isinstance(tags, list):
    return ", ".join(str(item) for item in tags)
  if tags is None:
    return ""
  return str(tags)


def format_record_datetime(value):
  if not value:
    return "Tarih yok"
  try:
    dt = parser.parse(str(value))
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")
  except Exception:
    return str(value)


def render_journal_tab(symbol, current_price, currency):
  st.subheader(f"📝 {symbol} Varlık Günlüğü")
  st.caption(
      "Buraya eklenen kayıtlar takip listesinden bağımsızdır. Varlığı listeden "
      "çıkarıp yeniden eklesen de Supabase üzerinde korunur."
  )

  with st.expander("➕ Yeni analiz / not ekle", expanded=True):
    with st.form(f"new_journal_{symbol}", clear_on_submit=True):
      form_col1, form_col2 = st.columns(2)
      with form_col1:
        entry_type = st.selectbox(
            "Kayıt türü",
            ["Analiz", "İşlem Planı", "Bilanço Notu", "Haber Notu", "Genel Not"],
        )
        title = st.text_input("Başlık", placeholder="Örn: Orta vadeli kırılım planı")
        status = st.selectbox("Durum", ["Açık", "İzlemede", "Gerçekleşti", "İptal"])
        tags_text = st.text_input(
            "Etiketler",
            placeholder="orta vade, teknik analiz, bilanço",
        )
      with form_col2:
        market_price_at_note = st.number_input(
            f"Not anındaki piyasa fiyatı ({currency or 'fiyat'})",
            min_value=0.0,
            value=float(current_price or 0.0),
            step=0.01,
            format="%.4f",
            help="Kaydı oluşturduğun sıradaki piyasa fiyatının sabit görüntüsüdür.",
        )
        price_at_entry = st.number_input(
            f"İşleme giriş fiyatım ({currency or 'fiyat'})",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.4f",
            help="İşlemi gerçekten açtığın ortalama maliyet/giriş fiyatıdır.",
        )
        target_price = st.number_input(
            "Hedef fiyat (boş bırakmak için 0)",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.4f",
        )
        stop_price = st.number_input(
            "Stop fiyatı (boş bırakmak için 0)",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.4f",
        )

      content = st.text_area(
          "Analiz / not",
          height=180,
          placeholder=(
              "Beklentini, dayanaklarını, destek-direnç seviyelerini, riskleri "
              "ve daha sonra kontrol etmek istediğin noktaları yaz."
          ),
      )

      alert_col1, alert_col2, alert_col3 = st.columns(3)
      with alert_col1:
        create_target_alert = st.checkbox("Hedef için alarm oluştur")
      with alert_col2:
        create_stop_alert = st.checkbox("Stop için alarm oluştur")
      with alert_col3:
        notify_ntfy = st.checkbox(
            "Telefona ntfy bildirimi",
            value=bool(NTFY_TOPIC),
            disabled=not bool(NTFY_TOPIC),
        )

      submitted = st.form_submit_button("💾 Günlüğe Kaydet", type="primary")

    if submitted:
      if not title.strip() or not content.strip():
        st.error("Başlık ve analiz/not alanı zorunludur.")
      else:
        created = storage.create_journal_entry(
            {
                "symbol": symbol,
                "title": title,
                "content": content,
                "entry_type": entry_type,
                "market_price_at_note": optional_price(market_price_at_note),
                "price_at_entry": optional_price(price_at_entry),
                "target_price": optional_price(target_price),
                "stop_price": optional_price(stop_price),
                "status": status,
                "tags": parse_tags(tags_text),
            }
        )
        if created:
          created_alerts = 0
          if create_target_alert and optional_price(target_price):
            if storage.create_alert(
                {
                    "symbol": symbol,
                    "label": f"{title} — Hedef",
                    "target_price": optional_price(target_price),
                    "condition": "above",
                    "repeat_mode": "once",
                    "last_checked_price": None,
                    "journal_entry_id": created.get("id"),
                    "notify_ntfy": notify_ntfy,
                }
            ):
              created_alerts += 1
          if create_stop_alert and optional_price(stop_price):
            if storage.create_alert(
                {
                    "symbol": symbol,
                    "label": f"{title} — Stop",
                    "target_price": optional_price(stop_price),
                    "condition": "below",
                    "repeat_mode": "once",
                    "last_checked_price": None,
                    "journal_entry_id": created.get("id"),
                    "notify_ntfy": notify_ntfy,
                }
            ):
              created_alerts += 1
          st.success(
              f"Günlük kaydı oluşturuldu. Eklenen alarm sayısı: {created_alerts}."
          )
          st.rerun()
        else:
          st.error(f"Kayıt oluşturulamadı: {storage.last_error}")

  entries = storage.list_journal_entries(symbol)
  st.markdown(f"### Geçmiş kayıtlar ({len(entries)})")
  if not entries:
    st.info("Bu varlık için henüz günlük kaydı bulunmuyor.")
    return

  for entry in entries:
    entry_id = str(entry.get("id"))
    heading = (
        f"{format_record_datetime(entry.get('created_at'))} · "
        f"{entry.get('title', 'Başlıksız')} · {entry.get('status', 'Açık')}"
    )
    with st.expander(heading):
      st.markdown(str(entry.get("content", "")))
      price_row1_col1, price_row1_col2 = st.columns(2)
      price_row1_col1.metric(
          "Not anındaki piyasa fiyatı",
          f"{float(entry.get('market_price_at_note') or 0):.4f} {currency}"
          if entry.get("market_price_at_note") is not None else "—",
      )
      price_row1_col2.metric(
          "İşleme giriş fiyatım",
          f"{float(entry.get('price_at_entry') or 0):.4f} {currency}"
          if entry.get("price_at_entry") is not None else "—",
      )
      price_row2_col1, price_row2_col2 = st.columns(2)
      price_row2_col1.metric(
          "Hedef",
          f"{float(entry.get('target_price') or 0):.4f} {currency}"
          if entry.get("target_price") is not None else "—",
      )
      price_row2_col2.metric(
          "Stop",
          f"{float(entry.get('stop_price') or 0):.4f} {currency}"
          if entry.get("stop_price") is not None else "—",
      )
      if entry.get("tags"):
        st.caption(f"Etiketler: {tags_to_text(entry.get('tags'))}")

      with st.form(f"edit_journal_{entry_id}"):
        edit_col1, edit_col2 = st.columns(2)
        with edit_col1:
          edit_title = st.text_input("Başlık", value=str(entry.get("title", "")))
          types_list = ["Analiz", "İşlem Planı", "Bilanço Notu", "Haber Notu", "Genel Not"]
          current_type = str(entry.get("entry_type", "Analiz"))
          edit_type = st.selectbox(
              "Kayıt türü",
              types_list,
              index=types_list.index(current_type) if current_type in types_list else 0,
          )
          statuses = ["Açık", "İzlemede", "Gerçekleşti", "İptal"]
          current_status = str(entry.get("status", "Açık"))
          edit_status = st.selectbox(
              "Durum",
              statuses,
              index=statuses.index(current_status) if current_status in statuses else 0,
          )
          edit_tags = st.text_input("Etiketler", value=tags_to_text(entry.get("tags")))
        with edit_col2:
          edit_market_price = st.number_input(
              "Not anındaki piyasa fiyatı",
              min_value=0.0,
              value=float(entry.get("market_price_at_note") or 0.0),
              step=0.01,
              format="%.4f",
          )
          edit_entry_price = st.number_input(
              "İşleme giriş fiyatım",
              min_value=0.0,
              value=float(entry.get("price_at_entry") or 0.0),
              step=0.01,
              format="%.4f",
          )
          edit_target = st.number_input(
              "Hedef",
              min_value=0.0,
              value=float(entry.get("target_price") or 0.0),
              step=0.01,
              format="%.4f",
          )
          edit_stop = st.number_input(
              "Stop",
              min_value=0.0,
              value=float(entry.get("stop_price") or 0.0),
              step=0.01,
              format="%.4f",
          )
        edit_content = st.text_area(
            "Analiz / not",
            value=str(entry.get("content", "")),
            height=180,
        )
        action_col1, action_col2 = st.columns(2)
        with action_col1:
          update_clicked = st.form_submit_button("💾 Değişiklikleri Kaydet")
        with action_col2:
          delete_clicked = st.form_submit_button("🗑️ Kaydı Sil")

      if update_clicked:
        ok = storage.update_journal_entry(
            entry_id,
            {
                "title": edit_title,
                "content": edit_content,
                "entry_type": edit_type,
                "market_price_at_note": optional_price(edit_market_price),
                "price_at_entry": optional_price(edit_entry_price),
                "target_price": optional_price(edit_target),
                "stop_price": optional_price(edit_stop),
                "status": edit_status,
                "tags": parse_tags(edit_tags),
            },
        )
        if ok:
          st.success("Kayıt güncellendi.")
          st.rerun()
        st.error(f"Güncelleme başarısız: {storage.last_error}")

      if delete_clicked:
        if storage.delete_journal_entry(entry_id):
          st.warning("Günlük kaydı silindi.")
          st.rerun()
        st.error(f"Silme başarısız: {storage.last_error}")


def render_alerts_tab(symbol, current_price, currency):
  st.subheader(f"🔔 {symbol} Fiyat Alarmları")
  st.caption(
      "Uygulama açıkken bütün aktif alarmlar ve seçili varlığın fiyatı 60 saniyede "
      "bir yenilenir. GitHub Actions etkinleştirildiğinde uygulama kapalıyken de "
      "yaklaşık 30 dakikada bir ücretsiz arka plan kontrolü çalışır."
  )

  top_col1, top_col2 = st.columns(2)
  with top_col1:
    if st.button("🔄 Tüm Aktif Alarmları Şimdi Kontrol Et", key=f"check_alerts_{symbol}"):
      active_now = storage.list_alerts(active_only=True)
      results = process_alerts(
          storage=storage,
          alerts=active_now,
          ntfy_topic=NTFY_TOPIC,
          ntfy_server=NTFY_SERVER,
          price_overrides={symbol: current_price} if current_price is not None else None,
      )
      if results:
        st.success(f"{len(results)} alarm tetiklendi.")
      else:
        st.info(f"{len(active_now)} aktif alarm kontrol edildi; tetiklenen olmadı.")
      get_market_snapshot.clear()
      st.rerun()
  with top_col2:
    if NTFY_TOPIC:
      if st.button("📲 Test Bildirimi Gönder", key=f"test_ntfy_{symbol}"):
        sent, detail = send_ntfy_notification(
            topic=NTFY_TOPIC,
            server=NTFY_SERVER,
            title="Aylooper test bildirimi",
            message=f"{symbol} için ntfy bağlantısı başarıyla test edildi.",
        )
        if sent:
          st.success("Test bildirimi gönderildi.")
        else:
          st.error(f"Bildirim gönderilemedi: {detail}")
    else:
      st.info("Test için önce NTFY_TOPIC secret değerini tanımla.")

  with st.expander("➕ Yeni bağımsız alarm oluştur", expanded=True):
    with st.form(f"new_alert_{symbol}", clear_on_submit=True):
      alert_col1, alert_col2 = st.columns(2)
      with alert_col1:
        label = st.text_input("Alarm adı", value=f"{symbol} fiyat alarmı")
        target = st.number_input(
            f"Hedef fiyat ({currency or 'fiyat'})",
            min_value=0.0001,
            value=float(current_price or 1.0),
            step=0.01,
            format="%.4f",
        )
        condition_text = st.selectbox("Koşul", ["Üzerine çıkınca", "Altına düşünce"])
      with alert_col2:
        repeat_text = st.selectbox("Tekrar", ["Bir kez", "Her seviye geçişinde"])
        notify = st.checkbox(
            "ntfy telefon bildirimi",
            value=bool(NTFY_TOPIC),
            disabled=not bool(NTFY_TOPIC),
        )
        st.caption(f"Başlangıç karşılaştırma fiyatı: {float(current_price or 0):.4f}")
      create_clicked = st.form_submit_button("🔔 Alarmı Kaydet", type="primary")

    if create_clicked:
      created = storage.create_alert(
          {
              "symbol": symbol,
              "label": label,
              "target_price": float(target),
              "condition": "above" if condition_text == "Üzerine çıkınca" else "below",
              "repeat_mode": "once" if repeat_text == "Bir kez" else "cross",
              "last_checked_price": None,
              "notify_ntfy": notify,
          }
      )
      if created:
        immediate_results = process_alerts(
            storage=storage,
            alerts=[created],
            ntfy_topic=NTFY_TOPIC,
            ntfy_server=NTFY_SERVER,
            price_overrides={symbol: current_price} if current_price is not None else None,
        )
        if immediate_results:
          st.warning("Koşul zaten sağlandığı için alarm hemen tetiklendi ve bildirim gönderildi.")
        else:
          st.success("Alarm kaydedildi; otomatik kontrole alındı.")
        st.rerun()
      st.error(f"Alarm kaydedilemedi: {storage.last_error}")

  alerts = storage.list_alerts(symbol=symbol)
  st.markdown(f"### Kayıtlı alarmlar ({len(alerts)})")
  if not alerts:
    st.info("Bu varlık için kayıtlı alarm bulunmuyor.")
  for alert in alerts:
    alert_id = str(alert.get("id"))
    condition_label = "≥" if alert.get("condition") == "above" else "≤"
    state_label = "Aktif" if alert.get("is_active") else "Pasif"
    with st.expander(
        f"{state_label} · {alert.get('label', 'Alarm')} · "
        f"{condition_label} {float(alert.get('target_price') or 0):.4f} {currency}"
    ):
      st.caption(
          f"Son kontrol fiyatı: {alert.get('last_checked_price') or '—'} · "
          f"Son tetiklenme: {format_record_datetime(alert.get('last_triggered_at'))}"
      )
      with st.form(f"edit_alert_{alert_id}"):
        alert_edit_col1, alert_edit_col2 = st.columns(2)
        with alert_edit_col1:
          edit_label = st.text_input("Alarm adı", value=str(alert.get("label", "")))
          edit_target = st.number_input(
              "Hedef fiyat",
              min_value=0.0001,
              value=float(alert.get("target_price") or 0.0001),
              step=0.01,
              format="%.4f",
          )
          conditions = ["Üzerine çıkınca", "Altına düşünce"]
          edit_condition = st.selectbox(
              "Koşul",
              conditions,
              index=0 if alert.get("condition") == "above" else 1,
          )
        with alert_edit_col2:
          repeats = ["Bir kez", "Her seviye geçişinde"]
          edit_repeat = st.selectbox(
              "Tekrar",
              repeats,
              index=0 if alert.get("repeat_mode") == "once" else 1,
          )
          edit_active = st.checkbox("Aktif", value=bool(alert.get("is_active", True)))
          edit_notify = st.checkbox(
              "ntfy bildirimi",
              value=bool(alert.get("notify_ntfy", False) and NTFY_TOPIC),
              disabled=not bool(NTFY_TOPIC),
          )
        edit_action1, edit_action2 = st.columns(2)
        with edit_action1:
          alert_update = st.form_submit_button("💾 Alarmı Güncelle")
        with edit_action2:
          alert_delete = st.form_submit_button("🗑️ Alarmı Sil")

      if alert_update:
        ok = storage.update_alert(
            alert_id,
            {
                "label": edit_label,
                "target_price": float(edit_target),
                "condition": "above" if edit_condition == "Üzerine çıkınca" else "below",
                "repeat_mode": "once" if edit_repeat == "Bir kez" else "cross",
                "is_active": edit_active,
                "notify_ntfy": edit_notify,
                # Yeniden aktif edilen alarm için yeni başlangıç noktası.
                "last_checked_price": current_price if edit_active else alert.get("last_checked_price"),
            },
        )
        if ok:
          st.success("Alarm güncellendi.")
          st.rerun()
        st.error(f"Güncelleme başarısız: {storage.last_error}")

      if alert_delete:
        if storage.delete_alert(alert_id):
          st.warning("Alarm silindi.")
          st.rerun()
        st.error(f"Silme başarısız: {storage.last_error}")

  history = storage.list_alert_history(symbol=symbol, limit=50)
  st.markdown(f"### Alarm geçmişi ({len(history)})")
  if history:
    history_df = pd.DataFrame(
        [
            {
                "Tarih": format_record_datetime(item.get("triggered_at")),
                "Alarm": item.get("label"),
                "Hedef": item.get("target_price"),
                "Tetiklenen Fiyat": item.get("triggered_price"),
                "Bildirim": item.get("notification_status"),
            }
            for item in history
        ]
    )
    st.dataframe(history_df, use_container_width=True, hide_index=True)
  else:
    st.info("Henüz tetiklenmiş alarm bulunmuyor.")


@st.fragment(run_every="60s")
def live_market_and_alert_checker(symbol, currency):
  """Açık oturumda fiyatı ve bütün aktif alarmları dakikada bir yeniler."""
  # TTL 50 saniye olduğu için her fragment çalışmasında yeni fiyat alınır; aynı
  # dakika içinde gereksiz tekrar istekleri önlenir.
  snapshot = get_market_snapshot(symbol)
  current_price = snapshot.get("current_price")
  price_change = float(snapshot.get("price_change") or 0.0)
  percent_change = float(snapshot.get("percent_change") or 0.0)

  all_active_alerts = storage.list_alerts(active_only=True)
  selected_active_count = sum(
      1 for alert in all_active_alerts
      if str(alert.get("symbol", "")).upper() == symbol.upper()
  )
  journal_count = len(storage.list_journal_entries(symbol))

  metric_col1, metric_col2, metric_col3 = st.columns(3)
  with metric_col1:
    if current_price is not None:
      st.metric(
          label=f"Anlık Fiyat ({symbol})",
          value=f"{current_price:.2f} {currency}",
          delta=f"{price_change:+.2f} {currency} (%{percent_change:+.2f})",
      )
    else:
      st.metric(label=f"Anlık Fiyat ({symbol})", value="Veri alınamadı")
  with metric_col2:
    st.metric("Aktif Alarm", selected_active_count)
  with metric_col3:
    st.metric("Günlük Kaydı", journal_count)

  price_overrides = {symbol: current_price} if current_price is not None else None
  triggered = process_alerts(
      storage=storage,
      alerts=all_active_alerts,
      ntfy_topic=NTFY_TOPIC,
      ntfy_server=NTFY_SERVER,
      price_overrides=price_overrides,
  )

  st.caption(
      f"Son otomatik yenileme: {istanbul_now_text()} · "
      f"Kontrol edilen aktif alarm: {len(all_active_alerts)} · "
      "Otomatik aralık: 60 saniye"
  )

  for result in triggered:
    triggered_symbol = str(result["alert"].get("symbol", symbol))
    st.toast(
        f"🚨 {triggered_symbol}: {result['current_price']:.4f} seviyesinde alarm tetiklendi!",
        icon="🚨",
    )
    st.error(result["message"].replace("\n", "  \n"))
    # Tarayıcı izin verirse kısa bir ses üretir.
    components.html(
        """
        <script>
        try {
          const AudioContext = window.AudioContext || window.webkitAudioContext;
          const ctx = new AudioContext();
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.connect(gain); gain.connect(ctx.destination);
          osc.frequency.value = 880;
          gain.gain.value = 0.08;
          osc.start();
          setTimeout(() => { osc.stop(); ctx.close(); }, 450);
        } catch (e) {}
        </script>
        """,
        height=0,
    )



# ---------------------------------------------------------
# TÜM PLANLARIM - TOPLU GÜNLÜK GÖRÜNÜMÜ
# ---------------------------------------------------------


def journal_currency(symbol):
  symbol = str(symbol or "").strip().upper()
  if symbol.endswith(".IS"):
    return "TRY"
  if symbol.endswith("-USD") or symbol.endswith("=X") or len(symbol) <= 5:
    return "USD"
  return ""


def price_value(value):
  try:
    number = float(value)
    return number if number > 0 else None
  except (TypeError, ValueError):
    return None


def percent_change_between(base, value):
  base_value = price_value(base)
  target_value = price_value(value)
  if base_value is None or target_value is None:
    return None
  return ((target_value - base_value) / base_value) * 100


def risk_reward_ratio(entry_price, target_price, stop_price):
  entry_value = price_value(entry_price)
  target_value = price_value(target_price)
  stop_value = price_value(stop_price)
  if entry_value is None or target_value is None or stop_value is None:
    return None
  reward = target_value - entry_value
  risk = entry_value - stop_value
  if reward <= 0 or risk <= 0:
    return None
  return reward / risk


def format_optional_price(value, currency=""):
  number = price_value(value)
  if number is None:
    return "—"
  suffix = f" {currency}" if currency else ""
  return f"{number:,.4f}{suffix}"


@st.cache_data(ttl=300, show_spinner=False)
def get_all_plan_current_prices(symbols_tuple):
  """Planlar görünümü için sembolleri toplu ve beş dakika önbellekli çeker."""
  return fetch_current_prices(symbols_tuple)


def render_all_plans_tab():
  st.subheader("📚 Tüm Planlarım")
  st.caption(
      "Her varlığın kendi günlüğü yalnız o varlığa özel kalır. Bu ekran ise "
      "bütün analiz ve işlem planlarını tek yerde toplar."
  )

  # Streamlit Cloud bazen eski FinanceStorage sınıfını önbellekten yükleyebilir.
  # Yeni yardımcı metot bulunmazsa aynı veriyi doğrudan mevcut Supabase
  # bağlantısından okuyarak Planlarım ekranının çalışmasını sürdür.
  list_all_method = getattr(storage, "list_all_journal_entries", None)
  if callable(list_all_method):
    entries = list_all_method()
  elif storage.is_supabase and getattr(storage, "client", None) is not None:
    try:
      response = (
          storage.client.table("journal_entries")
          .select("*")
          .order("created_at", desc=True)
          .execute()
      )
      entries = list(response.data or [])
    except Exception as exc:
      st.error(f"Plan kayıtları alınamadı: {exc}")
      entries = []
  else:
    # Yerel modda eski sınıf kullanılıyorsa sembol bazlı kayıtları birleştir.
    entries = []
    for symbol in st.session_state.get("watch_list", []):
      try:
        entries.extend(storage.list_journal_entries(symbol))
      except Exception:
        continue
    entries.sort(key=lambda item: item.get("created_at", ""), reverse=True)

  if not entries:
    st.info("Henüz herhangi bir varlık için günlük kaydı bulunmuyor.")
    return

  all_symbols = sorted({str(item.get("symbol", "")).upper() for item in entries if item.get("symbol")})
  all_statuses = ["Açık", "İzlemede", "Gerçekleşti", "İptal"]
  all_types = ["Analiz", "İşlem Planı", "Bilanço Notu", "Haber Notu", "Genel Not"]

  active_count = sum(str(item.get("status", "Açık")) in {"Açık", "İzlemede"} for item in entries)
  completed_count = sum(str(item.get("status", "")) == "Gerçekleşti" for item in entries)

  metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
  metric_col1.metric("Toplam kayıt", len(entries))
  metric_col2.metric("Aktif / izlenen", active_count)
  metric_col3.metric("Gerçekleşen", completed_count)
  metric_col4.metric("Varlık sayısı", len(all_symbols))

  st.markdown("#### 🔎 Filtreler")
  filter_col1, filter_col2 = st.columns(2)
  with filter_col1:
    symbol_filter = st.multiselect(
        "Hisse / varlık",
        all_symbols,
        placeholder="Boş bırakırsan tümü gösterilir",
        key="all_plans_symbol_filter",
    )
    status_filter = st.multiselect(
        "Durum",
        all_statuses,
        default=all_statuses,
        key="all_plans_status_filter",
    )
  with filter_col2:
    type_filter = st.multiselect(
        "Kayıt türü",
        all_types,
        default=all_types,
        key="all_plans_type_filter",
    )
    text_filter = st.text_input(
        "Başlık, analiz veya etikette ara",
        placeholder="Örn: bilanço, orta vade, kırılım",
        key="all_plans_text_filter",
    ).strip().lower()

  filtered_entries = []
  for entry in entries:
    symbol = str(entry.get("symbol", "")).upper()
    status = str(entry.get("status", "Açık"))
    entry_type = str(entry.get("entry_type", "Analiz"))
    searchable = " ".join([
        symbol,
        str(entry.get("title", "")),
        str(entry.get("content", "")),
        tags_to_text(entry.get("tags")),
    ]).lower()

    if symbol_filter and symbol not in symbol_filter:
      continue
    if status_filter and status not in status_filter:
      continue
    if type_filter and entry_type not in type_filter:
      continue
    if text_filter and text_filter not in searchable:
      continue
    filtered_entries.append(entry)

  st.caption(f"Gösterilen kayıt: {len(filtered_entries)} / {len(entries)}")
  if not filtered_entries:
    st.info("Seçilen filtrelere uygun plan bulunamadı.")
    return

  filtered_symbols = tuple(sorted({str(item.get("symbol", "")).upper() for item in filtered_entries if item.get("symbol")}))
  current_prices = get_all_plan_current_prices(filtered_symbols)

  summary_rows = []
  for entry in filtered_entries:
    symbol = str(entry.get("symbol", "")).upper()
    entry_price = price_value(entry.get("price_at_entry"))
    current_price = price_value(current_prices.get(symbol))
    target_price = price_value(entry.get("target_price"))
    stop_price = price_value(entry.get("stop_price"))
    summary_rows.append({
        "Varlık": symbol,
        "Başlık": str(entry.get("title", "Başlıksız")),
        "Tür": str(entry.get("entry_type", "Analiz")),
        "Durum": str(entry.get("status", "Açık")),
        "Giriş": entry_price,
        "Güncel": current_price,
        "Hedef": target_price,
        "Stop": stop_price,
        "Güncel K/Z %": percent_change_between(entry_price, current_price),
        "Hedef Pot. %": percent_change_between(entry_price, target_price),
        "Stop Riski %": percent_change_between(entry_price, stop_price),
        "Risk/Getiri": risk_reward_ratio(entry_price, target_price, stop_price),
        "Tarih": format_record_datetime(entry.get("created_at")),
    })

  st.markdown("#### 📋 Toplu görünüm")
  summary_df = pd.DataFrame(summary_rows)
  st.dataframe(
      summary_df,
      use_container_width=True,
      hide_index=True,
      height=min(620, 44 + len(summary_df) * 36),
      column_config={
          "Giriş": st.column_config.NumberColumn(format="%.4f"),
          "Güncel": st.column_config.NumberColumn(format="%.4f"),
          "Hedef": st.column_config.NumberColumn(format="%.4f"),
          "Stop": st.column_config.NumberColumn(format="%.4f"),
          "Güncel K/Z %": st.column_config.NumberColumn(format="%.2f%%"),
          "Hedef Pot. %": st.column_config.NumberColumn(format="%.2f%%"),
          "Stop Riski %": st.column_config.NumberColumn(format="%.2f%%"),
          "Risk/Getiri": st.column_config.NumberColumn(format="%.2f"),
      },
  )

  st.markdown("#### 🗂️ Plan ayrıntıları")
  for entry in filtered_entries:
    entry_id = str(entry.get("id"))
    symbol = str(entry.get("symbol", "")).upper()
    currency = journal_currency(symbol)
    current_price = price_value(current_prices.get(symbol))
    entry_price = price_value(entry.get("price_at_entry"))
    target_price = price_value(entry.get("target_price"))
    stop_price = price_value(entry.get("stop_price"))
    current_pnl = percent_change_between(entry_price, current_price)
    target_potential = percent_change_between(entry_price, target_price)
    stop_risk = percent_change_between(entry_price, stop_price)
    rr_ratio = risk_reward_ratio(entry_price, target_price, stop_price)

    heading = (
        f"{symbol} · {entry.get('title', 'Başlıksız')} · "
        f"{entry.get('status', 'Açık')}"
    )
    with st.expander(heading):
      st.caption(
          f"{format_record_datetime(entry.get('created_at'))} · "
          f"{entry.get('entry_type', 'Analiz')}"
      )
      st.markdown(str(entry.get("content", "")))
      if entry.get("tags"):
        st.caption(f"Etiketler: {tags_to_text(entry.get('tags'))}")

      price_col1, price_col2, price_col3 = st.columns(3)
      price_col1.metric("İşleme giriş", format_optional_price(entry_price, currency))
      price_col2.metric("Güncel fiyat", format_optional_price(current_price, currency))
      price_col3.metric("Not anındaki fiyat", format_optional_price(entry.get("market_price_at_note"), currency))

      plan_col1, plan_col2 = st.columns(2)
      plan_col1.metric("Hedef", format_optional_price(target_price, currency))
      plan_col2.metric("Stop", format_optional_price(stop_price, currency))

      ratio_col1, ratio_col2, ratio_col3, ratio_col4 = st.columns(4)
      ratio_col1.metric("Güncel K/Z", f"{current_pnl:+.2f}%" if current_pnl is not None else "—")
      ratio_col2.metric("Hedef potansiyeli", f"{target_potential:+.2f}%" if target_potential is not None else "—")
      ratio_col3.metric("Stop mesafesi", f"{stop_risk:+.2f}%" if stop_risk is not None else "—")
      ratio_col4.metric("Risk / getiri", f"{rr_ratio:.2f}" if rr_ratio is not None else "—")

      show_edit = st.checkbox(
          "Bu kaydı düzenle",
          key=f"all_plans_show_edit_{entry_id}",
      )
      if show_edit:
        with st.form(f"all_plans_edit_journal_{entry_id}"):
          edit_col1, edit_col2 = st.columns(2)
          with edit_col1:
            edit_title = st.text_input(
                "Başlık",
                value=str(entry.get("title", "")),
                key=f"all_plans_title_{entry_id}",
            )
            current_type = str(entry.get("entry_type", "Analiz"))
            edit_type = st.selectbox(
                "Kayıt türü",
                all_types,
                index=all_types.index(current_type) if current_type in all_types else 0,
                key=f"all_plans_type_{entry_id}",
            )
            current_status = str(entry.get("status", "Açık"))
            edit_status = st.selectbox(
                "Durum",
                all_statuses,
                index=all_statuses.index(current_status) if current_status in all_statuses else 0,
                key=f"all_plans_status_{entry_id}",
            )
            edit_tags = st.text_input(
                "Etiketler",
                value=tags_to_text(entry.get("tags")),
                key=f"all_plans_tags_{entry_id}",
            )
          with edit_col2:
            edit_market_price = st.number_input(
                "Not anındaki piyasa fiyatı",
                min_value=0.0,
                value=float(entry.get("market_price_at_note") or 0.0),
                step=0.01,
                format="%.4f",
                key=f"all_plans_market_{entry_id}",
            )
            edit_entry_price = st.number_input(
                "İşleme giriş fiyatım",
                min_value=0.0,
                value=float(entry.get("price_at_entry") or 0.0),
                step=0.01,
                format="%.4f",
                key=f"all_plans_entry_{entry_id}",
            )
            edit_target = st.number_input(
                "Hedef",
                min_value=0.0,
                value=float(entry.get("target_price") or 0.0),
                step=0.01,
                format="%.4f",
                key=f"all_plans_target_{entry_id}",
            )
            edit_stop = st.number_input(
                "Stop",
                min_value=0.0,
                value=float(entry.get("stop_price") or 0.0),
                step=0.01,
                format="%.4f",
                key=f"all_plans_stop_{entry_id}",
            )
          edit_content = st.text_area(
              "Analiz / not",
              value=str(entry.get("content", "")),
              height=170,
              key=f"all_plans_content_{entry_id}",
          )
          action_col1, action_col2 = st.columns(2)
          with action_col1:
            update_clicked = st.form_submit_button("💾 Değişiklikleri Kaydet")
          with action_col2:
            delete_clicked = st.form_submit_button("🗑️ Kaydı Sil")

        if update_clicked:
          ok = storage.update_journal_entry(
              entry_id,
              {
                  "title": edit_title,
                  "content": edit_content,
                  "entry_type": edit_type,
                  "market_price_at_note": optional_price(edit_market_price),
                  "price_at_entry": optional_price(edit_entry_price),
                  "target_price": optional_price(edit_target),
                  "stop_price": optional_price(edit_stop),
                  "status": edit_status,
                  "tags": parse_tags(edit_tags),
              },
          )
          if ok:
            st.success("Kayıt güncellendi.")
            st.rerun()
          else:
            st.error(f"Güncelleme başarısız: {storage.last_error}")

        if delete_clicked:
          if storage.delete_journal_entry(entry_id):
            st.success("Kayıt silindi.")
            st.rerun()
          else:
            st.error(f"Silme başarısız: {storage.last_error}")

# ---------------------------------------------------------
# YATIRIM TERCİH PROFİLİ — TAKİP LİSTESİNDEN VERİYE DAYALI ÖZET
# ---------------------------------------------------------
PROFILE_MAX_SYMBOLS = 20
PROFILE_CACHE_SECONDS = 21600  # 6 saat

SECTOR_TR_MAP = {
    "Technology": "Teknoloji",
    "Industrials": "Sanayi",
    "Healthcare": "Sağlık",
    "Financial Services": "Finansal Hizmetler",
    "Consumer Cyclical": "Döngüsel Tüketim",
    "Consumer Defensive": "Temel Tüketim",
    "Energy": "Enerji",
    "Utilities": "Altyapı / Kamu Hizmetleri",
    "Real Estate": "Gayrimenkul",
    "Basic Materials": "Temel Malzemeler",
    "Communication Services": "İletişim Hizmetleri",
}

MARKET_SUFFIX_MAP = {
    ".IS": "Türkiye / BIST",
    ".T": "Japonya",
    ".L": "İngiltere",
    ".DE": "Almanya",
    ".F": "Almanya",
    ".PA": "Fransa",
    ".AS": "Hollanda",
    ".BR": "Belçika",
    ".MI": "İtalya",
    ".SW": "İsviçre",
    ".HK": "Hong Kong",
    ".AX": "Avustralya",
    ".TO": "Kanada",
    ".V": "Kanada",
}


def profile_float(value):
  try:
    number = float(value)
    if pd.isna(number):
      return None
    return number
  except (TypeError, ValueError):
    return None


def profile_percent(value):
  number = profile_float(value)
  return None if number is None else number * 100


def profile_market(symbol, info):
  symbol = str(symbol or "").upper()
  if symbol.endswith("-USD"):
    return "Kripto Piyasası"
  for suffix, market_name in MARKET_SUFFIX_MAP.items():
    if symbol.endswith(suffix):
      return market_name
  country = str(info.get("country") or "").strip()
  exchange = str(info.get("exchange") or info.get("fullExchangeName") or "").strip()
  if country:
    return country
  if exchange:
    return exchange
  return "ABD / Global"


def profile_asset_class(symbol, quote_type):
  symbol = str(symbol or "").upper()
  quote_type = str(quote_type or "").upper()
  if symbol.endswith("-USD") or quote_type == "CRYPTOCURRENCY":
    return "Kripto"
  if quote_type in {"ETF", "MUTUALFUND"}:
    return "Fon / ETF"
  if symbol.endswith("=X") or quote_type == "CURRENCY":
    return "Döviz"
  if quote_type in {"INDEX", "FUTURE"}:
    return "Endeks / Vadeli"
  return "Hisse"


def profile_sector(symbol, info, asset_class):
  if asset_class == "Kripto":
    return "Kripto Varlık"
  if asset_class == "Fon / ETF":
    return "Fon / ETF"
  if asset_class == "Döviz":
    return "Döviz"
  if asset_class == "Endeks / Vadeli":
    return "Endeks / Vadeli"
  raw_sector = str(info.get("sector") or info.get("industry") or "").strip()
  if not raw_sector:
    return "Sektör verisi yok"
  return SECTOR_TR_MAP.get(raw_sector, raw_sector)


def profile_listing_years(info):
  epoch = info.get("firstTradeDateEpochUtc")
  if epoch is None:
    milliseconds = profile_float(info.get("firstTradeDateMilliseconds"))
    if milliseconds:
      epoch = milliseconds / 1000
  epoch_value = profile_float(epoch)
  if not epoch_value:
    return None
  try:
    listed_at = datetime.fromtimestamp(epoch_value, tz=ZoneInfo("UTC"))
    now_utc = datetime.now(ZoneInfo("UTC"))
    return max(0.0, (now_utc - listed_at).days / 365.25)
  except Exception:
    return None


def profile_volatility_band(volatility, asset_class):
  value = profile_float(volatility)
  if value is None:
    return "Veri yok"
  if asset_class == "Kripto":
    if value < 45:
      return "Orta"
    if value < 75:
      return "Yüksek"
    return "Çok yüksek"
  if value < 20:
    return "Düşük"
  if value < 35:
    return "Orta"
  if value < 55:
    return "Yüksek"
  return "Çok yüksek"


def profile_stage_signal(asset_class, listed_years, revenue_growth, profit_margin):
  """Sadece sayısal büyüme/kârlılık ve işlem geçmişinden sınırlı evre sinyali."""
  if asset_class != "Hisse":
    return "Uygulanmaz"
  growth = profile_float(revenue_growth)
  margin = profile_float(profit_margin)
  age = profile_float(listed_years)

  if age is not None and age < 5 and (growth is None or growth >= 5):
    return "Yeni halka açık / kısa piyasa geçmişi"
  if growth is not None and growth >= 20 and margin is not None and margin < 0:
    return "Büyüme / kârlılık öncesi"
  if growth is not None and growth >= 15 and margin is not None and margin >= 0:
    return "Kârlı büyüme"
  if growth is not None and growth <= -5:
    return "Daralma / dönüşüm sinyali"
  if margin is not None and margin >= 10 and growth is not None and -5 < growth < 15:
    return "Olgun / istikrarlı görünüm"
  return "Geçiş / veri sınırlı"


@st.cache_data(ttl=PROFILE_CACHE_SECONDS, show_spinner=False)
def fetch_preference_profile_symbol(symbol):
  """Tek varlık için ücretsiz Yahoo verilerinden profil göstergeleri üretir."""
  symbol = str(symbol or "").strip().upper()
  info = {}
  history = pd.DataFrame()
  errors = []

  try:
    ticker = yf.Ticker(symbol)
    try:
      info = ticker.get_info() or {}
    except Exception:
      try:
        info = ticker.info or {}
      except Exception as exc:
        errors.append(f"temel veri: {exc}")
    try:
      history = ticker.history(period="1y", interval="1d", auto_adjust=True)
    except Exception as exc:
      errors.append(f"fiyat geçmişi: {exc}")
  except Exception as exc:
    errors.append(str(exc))

  quote_type = info.get("quoteType")
  asset_class = profile_asset_class(symbol, quote_type)
  sector = profile_sector(symbol, info, asset_class)

  annual_volatility = None
  max_drawdown = None
  one_year_return = None
  if history is not None and not history.empty and "Close" in history.columns:
    closes = history["Close"].dropna()
    if len(closes) >= 20:
      daily_returns = closes.pct_change().dropna()
      if not daily_returns.empty:
        annual_volatility = profile_float(daily_returns.std() * (252 ** 0.5) * 100)
      running_max = closes.cummax()
      drawdowns = (closes / running_max) - 1
      max_drawdown = profile_float(drawdowns.min() * 100)
      if closes.iloc[0] not in (None, 0):
        one_year_return = profile_float(((closes.iloc[-1] / closes.iloc[0]) - 1) * 100)

  listing_years = profile_listing_years(info)
  revenue_growth = profile_percent(info.get("revenueGrowth"))
  profit_margin = profile_percent(info.get("profitMargins"))
  return_on_equity = profile_percent(info.get("returnOnEquity"))
  debt_to_equity = profile_float(info.get("debtToEquity"))
  current_ratio = profile_float(info.get("currentRatio"))
  free_cashflow = profile_float(info.get("freeCashflow"))
  operating_cashflow = profile_float(info.get("operatingCashflow"))

  return {
      "symbol": symbol,
      "name": str(info.get("shortName") or info.get("longName") or symbol),
      "asset_class": asset_class,
      "market": profile_market(symbol, info),
      "sector": sector,
      "currency": str(info.get("currency") or ""),
      "listing_years": listing_years,
      "annual_volatility": annual_volatility,
      "volatility_band": profile_volatility_band(annual_volatility, asset_class),
      "max_drawdown": max_drawdown,
      "one_year_return": one_year_return,
      "beta": profile_float(info.get("beta")),
      "market_cap": profile_float(info.get("marketCap")),
      "revenue_growth": revenue_growth,
      "profit_margin": profit_margin,
      "return_on_equity": return_on_equity,
      "debt_to_equity": debt_to_equity,
      "current_ratio": current_ratio,
      "free_cashflow": free_cashflow,
      "operating_cashflow": operating_cashflow,
      "stage_signal": profile_stage_signal(
          asset_class,
          listing_years,
          revenue_growth,
          profit_margin,
      ),
      "data_error": " | ".join(errors),
  }


@st.cache_data(ttl=PROFILE_CACHE_SECONDS, show_spinner=False)
def build_preference_profile(symbols_tuple):
  return [fetch_preference_profile_symbol(symbol) for symbol in symbols_tuple]


def profile_all_journal_entries():
  """Eski/yeni FinanceStorage sürümlerinde bütün günlük kayıtlarını güvenli getirir."""
  list_all_method = getattr(storage, "list_all_journal_entries", None)
  if callable(list_all_method):
    try:
      return list_all_method()
    except Exception:
      pass

  if storage.is_supabase and getattr(storage, "client", None) is not None:
    try:
      response = (
          storage.client.table("journal_entries")
          .select("*")
          .order("created_at", desc=True)
          .execute()
      )
      return list(response.data or [])
    except Exception:
      return []

  entries = []
  for symbol in st.session_state.get("watch_list", []):
    try:
      entries.extend(storage.list_journal_entries(symbol))
    except Exception:
      continue
  return entries


def profile_median(values):
  clean_values = [profile_float(value) for value in values]
  clean_values = [value for value in clean_values if value is not None]
  return float(pd.Series(clean_values).median()) if clean_values else None


def profile_fmt_pct(value, digits=1):
  number = profile_float(value)
  return "—" if number is None else f"%{number:.{digits}f}"


def profile_fmt_number(value, digits=2):
  number = profile_float(value)
  return "—" if number is None else f"{number:,.{digits}f}"


def profile_market_cap_text(value, currency):
  number = profile_float(value)
  if number is None:
    return "—"
  units = [(1_000_000_000_000, "T"), (1_000_000_000, "Mr"), (1_000_000, "Mn")]
  for divisor, label in units:
    if abs(number) >= divisor:
      return f"{number / divisor:,.2f} {label} {currency}".strip()
  return f"{number:,.0f} {currency}".strip()


def build_profile_attention_items(rows, journal_entries):
  """Yorum değil; eşiklere dayalı dikkat başlıkları üretir."""
  items = []
  total = len(rows)
  if total == 0:
    return items

  sector_counts = pd.Series([row["sector"] for row in rows]).value_counts()
  if not sector_counts.empty:
    top_sector = str(sector_counts.index[0])
    top_count = int(sector_counts.iloc[0])
    share = (top_count / total) * 100
    if total >= 3 and share >= 40:
      items.append({
          "title": "Sektör yoğunlaşması",
          "observation": f"{top_sector}: {top_count}/{total} varlık (%{share:.0f}, adet bazında).",
          "why": "Aynı sektördeki şirketler faiz, emtia, regülasyon veya talep değişikliklerine birlikte tepki verebilir.",
          "monitor": "Sektör dağılımı ve aynı sektörde eş zamanlı açık plan sayısı.",
      })

  market_counts = pd.Series([row["market"] for row in rows]).value_counts()
  if not market_counts.empty:
    top_market = str(market_counts.index[0])
    top_count = int(market_counts.iloc[0])
    share = (top_count / total) * 100
    if total >= 3 and share >= 70:
      items.append({
          "title": "Tek piyasa yoğunlaşması",
          "observation": f"{top_market}: {top_count}/{total} varlık (%{share:.0f}).",
          "why": "Aynı ülke, para birimi ve piyasa düzenine bağlı varlıklar ortak makro koşullardan etkilenebilir.",
          "monitor": "Kur, ülke faizi, yerel endeks ve piyasa likiditesi.",
      })

  vol_rows = [row for row in rows if profile_float(row.get("annual_volatility")) is not None]
  high_vol_rows = [row for row in vol_rows if row.get("volatility_band") in {"Yüksek", "Çok yüksek"}]
  if vol_rows and len(high_vol_rows) / len(vol_rows) >= 0.40:
    median_vol = profile_median([row.get("annual_volatility") for row in vol_rows])
    items.append({
        "title": "Yüksek fiyat dalgalanması",
        "observation": f"Verisi olan varlıkların {len(high_vol_rows)}/{len(vol_rows)} adedi yüksek veya çok yüksek volatilite grubunda. Medyan: {profile_fmt_pct(median_vol)}.",
        "why": "Geniş fiyat aralığı, aynı nominal yatırımla görülebilecek geçici zarar ve kazanç büyüklüğünü artırır.",
        "monitor": "Pozisyon büyüklüğü, stop mesafesi ve bir yıllık maksimum düşüş.",
    })

  drawdown_values = [row.get("max_drawdown") for row in rows]
  median_drawdown = profile_median(drawdown_values)
  if median_drawdown is not None and median_drawdown <= -25:
    items.append({
        "title": "Tarihsel düşüş kapasitesi",
        "observation": f"Bir yıllık maksimum düşüşlerin medyanı {profile_fmt_pct(median_drawdown)}.",
        "why": "Maksimum düşüş, varlıkların geçmişte zirveden ne kadar gerileyebildiğini gösterir; geleceği garanti etmez.",
        "monitor": "Portföy toplam düşüş toleransı ve aynı dönemde birlikte gerileyen varlıklar.",
    })

  stock_rows = [row for row in rows if row.get("asset_class") == "Hisse"]
  young_rows = [row for row in stock_rows if profile_float(row.get("listing_years")) is not None and row["listing_years"] < 5]
  if stock_rows and len(young_rows) / len(stock_rows) >= 0.30:
    items.append({
        "title": "Kısa borsa geçmişi",
        "observation": f"Hisselerin {len(young_rows)}/{len(stock_rows)} adedi beş yıldan kısa işlem geçmişine sahip.",
        "why": "Kısa piyasa geçmişi farklı faiz, kriz ve ekonomik döngülerde fiyat davranışını karşılaştırmayı sınırlar.",
        "monitor": "Halka arz sonrası finansallar, pay satışı/sermaye işlemleri ve likidite değişimi.",
    })

  fundamental_rows = [
      row for row in stock_rows
      if profile_float(row.get("profit_margin")) is not None
  ]
  negative_margin = [row for row in fundamental_rows if row["profit_margin"] < 0]
  if fundamental_rows and len(negative_margin) / len(fundamental_rows) >= 0.30:
    items.append({
        "title": "Kârlılık öncesi veya zarar yazan şirket ağırlığı",
        "observation": f"Kâr marjı verisi olan hisselerin {len(negative_margin)}/{len(fundamental_rows)} adedinde marj negatif.",
        "why": "Zarar dönemindeki büyümenin finansman ihtiyacı, nakit akışı ve sermaye artırımı olasılığını daha önemli hale getirir.",
        "monitor": "Faaliyet nakit akışı, serbest nakit akışı, borç vadesi ve sermaye işlemleri.",
    })

  non_financial = [
      row for row in stock_rows
      if row.get("sector") != "Finansal Hizmetler"
      and profile_float(row.get("debt_to_equity")) is not None
  ]
  high_leverage = [row for row in non_financial if row["debt_to_equity"] >= 150]
  if non_financial and len(high_leverage) / len(non_financial) >= 0.30:
    items.append({
        "title": "Borçluluk hassasiyeti",
        "observation": f"Finans dışı ve verisi olan şirketlerin {len(high_leverage)}/{len(non_financial)} adedinde borç/özkaynak %150 veya üzerinde.",
        "why": "Yüksek borçluluk, faiz ve refinansman koşullarının şirket sonuçlarına etkisini büyütebilir.",
        "monitor": "Net borç, faiz gideri, borç vadesi ve faaliyet nakit akışı.",
    })

  data_complete = [
      row for row in rows
      if profile_float(row.get("annual_volatility")) is not None
      and (row.get("asset_class") != "Hisse" or row.get("sector") != "Sektör verisi yok")
  ]
  if len(data_complete) / total < 0.70:
    items.append({
        "title": "Veri kapsamı sınırlı",
        "observation": f"Temel profil verisi {len(data_complete)}/{total} varlıkta yeterli düzeyde alınabildi.",
        "why": "Eksik Yahoo verisi, ortak özelliklerin tüm listeyi aynı güven düzeyinde temsil etmesini engeller.",
        "monitor": "Eksik sektör, finansal oran ve fiyat geçmişi satırları.",
    })

  active_entries = [entry for entry in journal_entries if str(entry.get("status", "")) in {"Açık", "İzlemede"}]
  if active_entries:
    missing_stop = [entry for entry in active_entries if price_value(entry.get("stop_price")) is None]
    missing_target = [entry for entry in active_entries if price_value(entry.get("target_price")) is None]
    if (len(missing_stop) + len(missing_target)) > 0:
      items.append({
          "title": "Plan kayıtlarında eksik sınırlar",
          "observation": f"{len(active_entries)} aktif/izlenen kaydın {len(missing_stop)} tanesinde stop, {len(missing_target)} tanesinde hedef bulunmuyor.",
          "why": "Hedef ve stop alanları, planın beklenen getiri ile tanımlanan risk tarafını sayısal olarak karşılaştırmayı sağlar.",
          "monitor": "Giriş, hedef ve stop alanlarının birlikte doldurulması.",
      })

  if not items:
    items.append({
        "title": "Belirgin eşik aşımı yok",
        "observation": "Mevcut listede tanımlı yoğunlaşma, volatilite, borçluluk ve plan tamlığı eşiklerinden belirgin biçimde aşan ortak bir yapı saptanmadı.",
        "why": "Bu sonuç risk bulunmadığı anlamına gelmez; yalnızca kullanılan ilk sürüm eşiklerinde güçlü bir ortak sinyal oluşmadığını gösterir.",
        "monitor": "Liste değiştikçe profili yeniden çalıştırmak.",
    })

  return items


def render_investment_preference_profile():
  st.subheader("🧭 Yatırım Tercih Profilim")
  st.caption(
      "Bu ekran kişilik veya risk iştahı tahmini yapmaz. Takip listesi ve kayıtlı "
      "planların ortak veri özelliklerini gösterir; alım-satım yorumu üretmez."
  )

  symbols = [str(symbol).strip().upper() for symbol in st.session_state.get("watch_list", []) if str(symbol).strip()]
  if not symbols:
    st.info("Profil oluşturmak için takip listesine en az bir varlık ekle.")
    return

  if len(symbols) > PROFILE_MAX_SYMBOLS:
    st.warning(
        f"İlk sürüm performans ve ücretsiz veri sınırı için en fazla {PROFILE_MAX_SYMBOLS} "
        "varlığı analiz eder. Listenin ilk kısmı kullanılacak."
    )
  analyzed_symbols = tuple(symbols[:PROFILE_MAX_SYMBOLS])

  action_col1, action_col2 = st.columns([1, 3])
  with action_col1:
    create_profile = st.button(
        "🔄 Profili Oluştur / Güncelle",
        type="primary",
        use_container_width=True,
        key="build_preference_profile",
    )
  with action_col2:
    st.caption(
        "Yahoo verileri 6 saat önbellekte tutulur. Aynı listeyle tekrar basmak "
        "ücretsiz veri kaynağına gereksiz istek göndermez."
    )

  if create_profile:
    with st.spinner("Takip listesinin ortak özellikleri hesaplanıyor..."):
      st.session_state["preference_profile_rows"] = build_preference_profile(analyzed_symbols)
      st.session_state["preference_profile_symbols"] = analyzed_symbols
      st.session_state["preference_profile_created_at"] = istanbul_now_text()

  rows = st.session_state.get("preference_profile_rows")
  stored_symbols = tuple(st.session_state.get("preference_profile_symbols", ()))
  if not rows:
    st.info("İlk profili görmek için ‘Profili Oluştur / Güncelle’ düğmesine bas.")
    return

  if stored_symbols != analyzed_symbols:
    st.warning("Takip listesi profil oluşturulduktan sonra değişmiş. Güncel sonuç için profili yeniden oluştur.")

  rows = list(rows)
  journal_entries = profile_all_journal_entries()
  total = len(rows)
  sector_counts = pd.Series([row["sector"] for row in rows]).value_counts()
  market_counts = pd.Series([row["market"] for row in rows]).value_counts()
  top_sector = str(sector_counts.index[0]) if not sector_counts.empty else "—"
  top_sector_share = (float(sector_counts.iloc[0]) / total * 100) if total and not sector_counts.empty else None
  median_volatility = profile_median([row.get("annual_volatility") for row in rows])
  active_plans = sum(str(entry.get("status", "")) in {"Açık", "İzlemede"} for entry in journal_entries)
  usable_rows = sum(
      profile_float(row.get("annual_volatility")) is not None
      and (row.get("asset_class") != "Hisse" or row.get("sector") != "Sektör verisi yok")
      for row in rows
  )

  st.markdown("#### Profil özeti")
  summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
  summary_col1.metric("İncelenen varlık", total)
  summary_col2.metric(
      "Baskın sektör",
      top_sector,
      f"%{top_sector_share:.0f} adet payı" if top_sector_share is not None else None,
  )
  summary_col3.metric("Medyan yıllık volatilite", profile_fmt_pct(median_volatility))
  summary_col4.metric("Aktif / izlenen plan", active_plans)
  st.caption(
      f"Son profil: {st.session_state.get('preference_profile_created_at', '—')} · "
      f"Yeterli temel veri: {usable_rows}/{total} · Sektör ve piyasa oranları adet bazındadır."
  )

  overview_col1, overview_col2 = st.columns(2)
  with overview_col1:
    st.markdown("#### Sektör dağılımı")
    sector_frame = sector_counts.rename_axis("Sektör").reset_index(name="Varlık sayısı")
    sector_frame["Pay (%)"] = (sector_frame["Varlık sayısı"] / total * 100).round(1)
    st.dataframe(sector_frame, use_container_width=True, hide_index=True)
  with overview_col2:
    st.markdown("#### Piyasa dağılımı")
    market_frame = market_counts.rename_axis("Piyasa / ülke").reset_index(name="Varlık sayısı")
    market_frame["Pay (%)"] = (market_frame["Varlık sayısı"] / total * 100).round(1)
    st.dataframe(market_frame, use_container_width=True, hide_index=True)

  st.markdown("#### Dikkate değer ortak noktalar")
  attention_items = build_profile_attention_items(rows, journal_entries)
  for item in attention_items:
    with st.expander(f"• {item['title']}", expanded=True):
      st.markdown(f"**Gözlem:** {item['observation']}")
      st.markdown(f"**Neden önemlidir:** {item['why']}")
      st.markdown(f"**Takip edilecek veri:** {item['monitor']}")

  st.markdown("#### Varlık bazında karşılaştırma")
  comparison_rows = []
  for row in rows:
    comparison_rows.append({
        "Sembol": row["symbol"],
        "Varlık": row["name"],
        "Sınıf": row["asset_class"],
        "Sektör": row["sector"],
        "Piyasa": row["market"],
        "Borsa geçmişi (yıl)": round(row["listing_years"], 1) if profile_float(row.get("listing_years")) is not None else None,
        "Volatilite (%)": round(row["annual_volatility"], 1) if profile_float(row.get("annual_volatility")) is not None else None,
        "Volatilite grubu": row["volatility_band"],
        "Maks. düşüş (%)": round(row["max_drawdown"], 1) if profile_float(row.get("max_drawdown")) is not None else None,
        "1Y getiri (%)": round(row["one_year_return"], 1) if profile_float(row.get("one_year_return")) is not None else None,
        "Evre göstergesi": row["stage_signal"],
    })
  st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)

  st.markdown("#### Anlamlı finansal ayrımlar")
  st.caption(
      "Oranlar sektörler arasında doğrudan kıyaslanmayabilir. Banka/finans şirketlerinde "
      "borç/özkaynak ve cari oran klasik sanayi şirketleriyle aynı anlamı taşımaz."
  )
  financial_rows = []
  for row in rows:
    if row.get("asset_class") != "Hisse":
      continue
    financial_rows.append({
        "Sembol": row["symbol"],
        "Sektör": row["sector"],
        "Ciro büyümesi (%)": round(row["revenue_growth"], 1) if profile_float(row.get("revenue_growth")) is not None else None,
        "Kâr marjı (%)": round(row["profit_margin"], 1) if profile_float(row.get("profit_margin")) is not None else None,
        "Özkaynak kârlılığı (%)": round(row["return_on_equity"], 1) if profile_float(row.get("return_on_equity")) is not None else None,
        "Borç / özkaynak (%)": round(row["debt_to_equity"], 1) if profile_float(row.get("debt_to_equity")) is not None else None,
        "Cari oran": round(row["current_ratio"], 2) if profile_float(row.get("current_ratio")) is not None else None,
        "Serbest nakit akışı": profile_fmt_number(row.get("free_cashflow"), 0),
        "Piyasa değeri": profile_market_cap_text(row.get("market_cap"), row.get("currency", "")),
    })
  if financial_rows:
    st.dataframe(pd.DataFrame(financial_rows), use_container_width=True, hide_index=True)
  else:
    st.info("Takip listesinde karşılaştırılabilir şirket finansalı bulunamadı.")

  with st.expander("📘 Yeni yatırımcı için kullanılan kavramlar"):
    st.markdown(
        """
- **Sektör yoğunlaşması:** Takip listesindeki şirketlerin aynı ekonomik etkene bağlı olma oranıdır. Burada pozisyon büyüklüğü bilinmediği için adet bazında hesaplanır.
- **Yıllık volatilite:** Günlük fiyat değişimlerinin yıllıklaştırılmış dalgalanma ölçüsüdür. Yön belirtmez; hareket aralığını anlatır.
- **Maksimum düşüş:** İncelenen dönemde bir zirveden sonraki en büyük gerilemedir. Gelecekte aynı düşüşün olacağını göstermez.
- **Borsa geçmişi:** Şirketin kuruluş yaşı değil, Yahoo verisinde erişilebilen ilk işlem tarihinden itibaren geçen süredir.
- **Borç/özkaynak:** Finans dışı şirketlerde borç yükünün özkaynağa oranını gösterir. Bankalarda farklı yorumlanır.
- **Serbest nakit akışı:** Şirketin faaliyet ve yatırım harcamaları sonrasında kalan nakit üretimini gösterir.
- **Evre göstergesi:** Ciro büyümesi, kâr marjı ve borsada işlem süresinden üretilen sınırlı bir veri etiketidir; şirket hakkında kesin hüküm değildir.
        """
    )

  st.caption(
      "Veri kaynakları: mevcut Supabase günlük kayıtları ve ücretsiz Yahoo Finance/yfinance verileri. "
      "Bu bölüm yatırım tavsiyesi veya yatırımcı kişiliği değerlendirmesi değildir."
  )


# ---------------------------------------------------------
# ÜST DÜZEY ANA SEKMELER
# ---------------------------------------------------------
main_tab1, main_tab_plans, main_tab_profile, main_tab2, main_tab3 = st.tabs([
    "📊 Hisse Analiz Paneli",
    "📚 Planlarım",
    "🧭 Tercih Profilim",
    "📅 Makro Finansal Takvim & AI",
    "🪙 Kripto Piyasası",
])

# =========================================================
# ANA SEKMELER 1: HİSSE ANALİZ PANELİ
# =========================================================
with main_tab1:
  if selected_stock:
    currency = (
        "TRY"
        if selected_stock.endswith(".IS")
        else ("USD" if "-" in selected_stock or len(selected_stock) <= 5 else "")
    )

    # Formların başlangıç fiyatı için ilk anlık görüntü. Üst metrik ve tüm aktif
    # alarmlar aşağıdaki fragment içinde 60 saniyede bir kendiliğinden yenilenir.
    initial_snapshot = get_market_snapshot(selected_stock)
    current_price = initial_snapshot.get("current_price")
    previous_close = initial_snapshot.get("previous_close")
    price_change = float(initial_snapshot.get("price_change") or 0.0)
    percent_change = float(initial_snapshot.get("percent_change") or 0.0)

    live_market_and_alert_checker(selected_stock, currency)

    st.markdown("---")
    clean_ticker = selected_stock.replace(".IS", "")

    (
        sub_tab1,
        sub_tab_chart,
        sub_tab_journal,
        sub_tab_alerts,
        sub_tab2,
        sub_tab3,
        sub_tab4,
        sub_tab5,
    ) = st.tabs([
        "🎯 Pivot Noktaları",
        "📈 Grafik",
        "📝 Varlık Günlüğü",
        "🔔 Alarmlar",
        "🏛️ KAP Bildirimleri (BIST)",
        "📰 Basın Haberleri",
        "🌐 Yahoo Finance",
        "🤖 Hisse Özel AI Soru Paneli",
    ])

    currency = (
        "TRY"
        if selected_stock.endswith(".IS")
        else ("USD" if "-" in selected_stock or len(selected_stock) <= 5 else "")
    )

    with sub_tab1:
      st.write("##### Standart (Klasik) Pivot Seviyeleri")
      timeframe_choice = st.radio(
          "Zaman Dilimi Seçin:",
          ["Günlük", "Haftalık", "Aylık"],
          horizontal=True,
          key=f"pivot_timeframe_{selected_stock}",
      )

      p_data = calculate_pivot_points(selected_stock, timeframe_choice)

      if p_data and isinstance(p_data, dict):
        c1, c2, c3 = st.columns(3)
        with c1:
          st.markdown("### 🔴 Dirençler")
          st.error(f"**R3:** {p_data.get('Direnç 3 (R3)', 'N/A')} {currency}")
          st.error(f"**R2:** {p_data.get('Direnç 2 (R2)', 'N/A')} {currency}")
          st.error(f"**R1:** {p_data.get('Direnç 1 (R1)', 'N/A')} {currency}")
        with c2:
          st.markdown("### ⚪ Pivot Seviyesi")
          st.info(f"**Pivot (P):** {p_data.get('Pivot (P)', 'N/A')} {currency}")
        with c3:
          st.markdown("### 🟢 Destekler")
          st.success(f"**S1:** {p_data.get('Destek 1 (S1)', 'N/A')} {currency}")
          st.success(f"**S2:** {p_data.get('Destek 2 (S2)', 'N/A')} {currency}")
          st.success(f"**S3:** {p_data.get('Destek 3 (S3)', 'N/A')} {currency}")
      else:
        st.warning(
            "Yahoo Finance geçici olarak çok fazla istek aldığından veriler "
            "alınamadı. Lütfen 1-2 dakika bekleyip sayfayı yenileyin."
        )

    with sub_tab_chart:
      if requires_plotly_chart(selected_stock):
        st.write("##### İnteraktif Teknik Fiyat Grafiği")
        st.caption(
            "Bu BIST sembolü TradingView'in dış-site veri lisansı nedeniyle "
            "widget içinde açılamadığı için Plotly grafik kullanılıyor."
        )

        control_col1, control_col2, control_col3 = st.columns(3)
        with control_col1:
          chart_range = st.selectbox(
              "Grafik Aralığı:",
              list(CHART_RANGE_OPTIONS.keys()),
              index=2,
              key=f"chart_range_{selected_stock}",
          )
        with control_col2:
          chart_type = st.radio(
              "Grafik Tipi:",
              ["Mum", "Çizgi"],
              horizontal=True,
              key=f"chart_type_{selected_stock}",
          )
        with control_col3:
          chart_pivot_timeframe = st.selectbox(
              "Pivot Çizgisi Dönemi:",
              ["Günlük", "Haftalık", "Aylık"],
              key=f"chart_pivot_timeframe_{selected_stock}",
          )

        selected_indicators = st.multiselect(
            "Grafikte Göster:",
            [
                "Pivot Seviyeleri",
                "EMA 20",
                "EMA 50",
                "Bollinger Bantları",
                "Hacim",
            ],
            default=["Pivot Seviyeleri", "EMA 20", "EMA 50", "Hacim"],
            key=f"chart_indicators_{selected_stock}",
        )

        render_technical_chart(
            ticker_symbol=selected_stock,
            range_label=chart_range,
            chart_type=chart_type,
            pivot_timeframe=chart_pivot_timeframe,
            selected_indicators=selected_indicators,
            currency=currency,
        )
      else:
        st.write("##### TradingView Gelişmiş Grafik")
        tv_timeframe = st.radio(
            "Başlangıç Zaman Dilimi:",
            ["Günlük", "Haftalık", "Aylık"],
            horizontal=True,
            key=f"tv_timeframe_{selected_stock}",
        )
        st.caption(
            "Grafik TradingView üzerinden açılır. Zaman aralığı, indikatör ve "
            "çizim araçlarını grafiğin kendi araç çubuğundan değiştirebilirsin."
        )

        rendered = render_tradingview_chart(
            yahoo_symbol=selected_stock,
            timeframe=tv_timeframe,
            height=720,
        )
        if not rendered:
          st.error("Bu sembol için TradingView grafik eşleştirmesi yapılamadı.")

    with sub_tab_journal:
      render_journal_tab(
          symbol=selected_stock,
          current_price=current_price,
          currency=currency,
      )

    with sub_tab_alerts:
      render_alerts_tab(
          symbol=selected_stock,
          current_price=current_price,
          currency=currency,
      )

    with sub_tab2:
      if selected_stock.endswith(".IS"):
        kap_news = fetch_rss_news_sorted(f"site:kap.org.tr {clean_ticker}")
        if not kap_news:
          kap_news = fetch_rss_news_sorted(f"{clean_ticker} KAP bildirimi")
        if kap_news:
          for item in kap_news:
            st.markdown(
                f"* [{item['title']}]({item['link']}) — <small"
                f" style='color:gray;'>📅 {item['published_str']}</small>",
                unsafe_allow_html=True,
            )
        else:
          st.info("KAP bildirimleri bulunamadı.")
      else:
        st.info("KAP bildirimleri sadece BIST hisseleri içindir.")

    with sub_tab3:
      g_news = fetch_rss_news_sorted(f"{clean_ticker} hisse haber OR borsa")
      if g_news:
        for item in g_news:
          st.markdown(
              f"* [{item['title']}]({item['link']}) — *{item['source']}*  \n "
              f" <small style='color:gray;'>📅 {item['published_str']}</small>",
              unsafe_allow_html=True,
          )
      else:
        st.info("İlgili haber bulunamadı.")

    with sub_tab4:
      try:
        ticker_obj_yf = yf.Ticker(selected_stock)
        news_list = ticker_obj_yf.news
        if news_list:
          for item in news_list[:7]:
            title = (
                item.get("title")
                or item.get("content", {}).get("title", "Başlık Yok")
            )
            link = (
                item.get("link")
                or item.get("content", {})
                .get("canonicalUrl", {})
                .get("url", "#")
            )
            st.markdown(f"* [{title}]({link})")
        else:
          st.info("Yahoo Finance haberi bulunamadı.")
      except Exception:
        st.write("Yahoo haberleri yüklenemedi.")

    with sub_tab5:
      st.subheader(f"🤖 {selected_stock} için Gemini AI Asistanı")
      st.caption(
          "Bu hisseyle ilgili güncel durum, beklentiler, teknik seviyeler veya"
          " sektör dinamikleri hakkında dilediğin soruyu sorabilirsin."
      )

      stock_user_q = st.text_input(
          f"{selected_stock} hakkında neyi öğrenmek istiyorsun?",
          placeholder=(
              "Örn: Bu hissenin son dönemdeki performansını ve teknik"
              " görünümünü değerlendir."
          ),
          key="stock_ai_input",
      )

      if st.button("💬 Soruyu Gemini'ye İlet", key="stock_ai_btn"):
        if stock_user_q:
          with st.spinner("Gemini analiz ediyor..."):
            stock_context_data = f"Seçilen Hisse: {selected_stock}, Güncel Fiyat: {current_price} {currency}, Değişim: %{percent_change:.2f}"
            stock_ans = ask_gemini_analysis(
                prompt=stock_user_q,
                system_instruction=(
                    f"Seçilen Hisse: {selected_stock}. Bağlam"
                    f" verileri:\n{stock_context_data}"
                ),
            )
            st.markdown(stock_ans)
        else:
          st.warning("Lütfen bir soru yazın.")

# =========================================================
# ANA SEKMELER 2: TÜM PLANLARIM
# =========================================================
with main_tab_plans:
  render_all_plans_tab()

# =========================================================
# ANA SEKMELER 3: YATIRIM TERCİH PROFİLİ
# =========================================================
with main_tab_profile:
  render_investment_preference_profile()

# =========================================================
# ANA SEKMELER 4: ÜCRETSİZ KÜRESEL TAKVİM & AI CHAT
# =========================================================
with main_tab2:
  st.subheader("📅 Küresel Makroekonomik Takvim")
  st.caption(
      "Türkiye, ABD, Euro Bölgesi, büyük Avrupa ve Asya ekonomilerindeki "
      "yüksek ve orta önem düzeyindeki gelişmeler. Filtreleri takvimdeki "
      "ayar simgesinden değiştirebilirsin."
  )

  calendar_config = {
      "colorTheme": "light",
      "isTransparent": True,
      "locale": "tr",
      "countryFilter": "tr,us,eu,de,fr,it,es,nl,gb,jp,cn,ca,au,ch,kr,in",
      "importanceFilter": "0,1",
      "width": "100%",
      "height": 760,
  }
  calendar_config_json = json.dumps(calendar_config, ensure_ascii=False)
  calendar_html = f"""
  <!doctype html>
  <html lang="tr">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        html, body {{
          margin: 0;
          padding: 0;
          width: 100%;
          height: 100%;
          overflow: hidden;
          background: transparent;
        }}
        .calendar-viewport {{
          width: 100%;
          height: 650px;
          overflow: hidden;
        }}
        .calendar-scale {{
          width: 111.12%;
          height: 720px;
          transform: scale(0.90);
          transform-origin: top left;
        }}
        .tradingview-widget-container {{
          width: 100%;
          height: 720px;
        }}
        .tradingview-widget-container__widget {{
          width: 100%;
          height: calc(100% - 22px);
        }}
        .tradingview-widget-copyright {{
          height: 18px;
          padding-top: 2px;
          text-align: right;
          font: 9px Arial, sans-serif;
        }}
        .tradingview-widget-copyright a {{
          color: #2962ff;
          text-decoration: none;
        }}

        @media (max-width: 768px) {{
          .calendar-viewport {{
            height: 560px;
          }}
          .calendar-scale {{
            width: 128.21%;
            height: 710px;
            transform: scale(0.78);
          }}
          .tradingview-widget-container {{
            height: 710px;
          }}
          .tradingview-widget-copyright {{
            font-size: 8px;
          }}
        }}

        @media (max-width: 430px) {{
          .calendar-viewport {{
            height: 525px;
          }}
          .calendar-scale {{
            width: 138.89%;
            height: 720px;
            transform: scale(0.72);
          }}
          .tradingview-widget-container {{
            height: 720px;
          }}
        }}
      </style>
    </head>
    <body>
      <div class="calendar-viewport">
        <div class="calendar-scale">
          <div class="tradingview-widget-container">
            <div class="tradingview-widget-container__widget"></div>
            <div class="tradingview-widget-copyright">
              <a href="https://www.tradingview.com/economic-calendar/"
                 rel="noopener nofollow" target="_blank">Ekonomik Takvim</a>
              <span> · TradingView</span>
            </div>
            <script type="text/javascript"
                    src="https://s3.tradingview.com/external-embedding/embed-widget-events.js"
                    async>{calendar_config_json}</script>
          </div>
        </div>
      </div>
    </body>
  </html>
  """
  components.html(calendar_html, height=655, scrolling=False)

  st.caption(
      "Gemini analizi için takvimde gördüğün gelişmenin bilgilerini aşağıya yaz."
  )

  st.markdown("---")
  st.subheader("🤖 Gemini Makro Gelişme Analizi")

  ai_col1, ai_col2 = st.columns(2)
  with ai_col1:
    macro_event_title = st.text_input(
        "Ekonomik gelişme",
        placeholder="Örn: ABD Tarım Dışı İstihdam",
        key="macro_event_title_free",
    )
    macro_region = st.selectbox(
        "Ülke / Bölge",
        [
            "Türkiye",
            "ABD",
            "Euro Bölgesi",
            "Almanya",
            "Fransa",
            "İtalya",
            "İspanya",
            "İngiltere",
            "Japonya",
            "Çin",
            "Kanada",
            "Avustralya",
            "İsviçre",
            "Güney Kore",
            "Hindistan",
            "Diğer",
        ],
        key="macro_region_free",
    )
    macro_importance = st.selectbox(
        "Önem derecesi",
        ["🔴 Yüksek", "🟡 Orta"],
        key="macro_importance_free",
    )
    macro_datetime = st.text_input(
        "Tarih / saat (isteğe bağlı)",
        placeholder="Örn: 01.08.2026 15:30",
        key="macro_datetime_free",
    )
  with ai_col2:
    macro_actual = st.text_input(
        "Açıklanan değer (isteğe bağlı)",
        placeholder="Örn: 185K",
        key="macro_actual_free",
    )
    macro_forecast = st.text_input(
        "Beklenti (isteğe bağlı)",
        placeholder="Örn: 170K",
        key="macro_forecast_free",
    )
    macro_previous = st.text_input(
        "Önceki değer (isteğe bağlı)",
        placeholder="Örn: 147K",
        key="macro_previous_free",
    )

  macro_question = st.text_area(
      "Gemini'ye soracağın soru",
      placeholder=(
          "Örn: Bu veri BIST, Nasdaq, dolar/TL, altın ve faiz beklentileri için "
          "hangi senaryoları oluşturabilir?"
      ),
      height=120,
      key="macro_question_free",
  )

  if st.button("🚀 Makro Gelişmeyi Gemini ile Analiz Et", type="primary"):
    if not macro_event_title.strip():
      st.warning("Önce ekonomik gelişmenin adını yaz.")
    elif not macro_question.strip():
      st.warning("Gemini'ye soracağın soruyu yaz.")
    else:
      macro_context = {
          "Gelişme": macro_event_title.strip(),
          "Ülke/Bölge": macro_region,
          "Önem": macro_importance,
          "Tarih/Saat": macro_datetime.strip() or "Belirtilmedi",
          "Açıklanan": macro_actual.strip() or "Henüz açıklanmadı/belirtilmedi",
          "Beklenti": macro_forecast.strip() or "Belirtilmedi",
          "Önceki": macro_previous.strip() or "Belirtilmedi",
      }
      with st.spinner("Gemini piyasa etkilerini değerlendiriyor..."):
        macro_answer = ask_gemini_analysis(
            prompt=(
                f"Kullanıcının sorusu: {macro_question.strip()}\n\n"
                f"Ekonomik gelişme bilgileri: {json.dumps(macro_context, ensure_ascii=False)}"
            ),
            system_instruction=(
                "Finansal piyasa analisti gibi yaz. Verilen ekonomik gelişmenin "
                "Türkiye, küresel hisse piyasaları, döviz, faiz, altın ve ilgili "
                "sektörler üzerindeki olası etkilerini senaryolar halinde değerlendir. "
                "Açıklanan değer verilmişse beklenti ve önceki değerle karşılaştır. "
                "Eksik veriyi uydurma, belirsizliği açıkça belirt ve kesin getiri vaadi verme."
            ),
        )
        st.markdown(macro_answer)

# =========================================================
# ANA SEKMELER 5: KRİPTO PİYASASI (YFINANCE)
# =========================================================
with main_tab3:
  st.header("🪙 Kripto Piyasası Canlı Takibi")
  st.caption("Yahoo Finance altyapısı üzerinden anlık kripto para takibi.")

  crypto_options = [
      "BTC-USD",
      "ETH-USD",
      "SOL-USD",
      "AVAX-USD",
      "BNB-USD",
      "XRP-USD",
      "ADA-USD",
      "DOGE-USD",
  ]
  selected_crypto = st.selectbox("İşlem Çifti Seçin:", crypto_options)

  if selected_crypto:
    stats = get_crypto_yf_stats(selected_crypto)
    if stats and stats["lastPrice"] > 0:
      fiyat = stats["lastPrice"]
      degisim = stats["priceChangePercent"]

      c1, c2 = st.columns(2)
      c1.metric("Anlık Fiyat", f"${fiyat:,.2f}")
      c2.metric(
          "24 Saatlik Değişim",
          f"%{degisim:.2f}",
          delta=f"{degisim:.2f}%",
      )
    else:
      st.error(
          "Veriler alınamadı veya ağ bağlantısında geçici bir sorun oluştu."
      )
