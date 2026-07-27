import json
import os
import urllib.parse
from dateutil import parser
import feedparser
import google.generativeai as genai
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

# Sayfa Yapılandırması (Mobil Uyumluluk Optimizasyonu)
st.set_page_config(
    page_title="Aylooper Finans & AI Paneli",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="auto",
)

# Mobil Ekranlar İçin Yazı Boyutu, Padding ve Üst Boşluğu Azaltma (Özel CSS)
st.markdown(
    """
    <style>
    /* Sayfa üstündeki boşluğu ve header padding'ini azaltır */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }

    /* Sidebar içerisinin mobilde taşmasını önlemek ve scroll kazandırmak */
    [data-testid="stSidebar"] > div:first-child {
        overflow-y: auto;
        max-height: 100vh;
        padding-bottom: 80px;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.8rem !important;
        }
        .stMetric {
            font-size: 14px !important;
        }
        h1 {
            font-size: 22px !important;
        }
        h2 {
            font-size: 18px !important;
        }
        h3 {
            font-size: 16px !important;
        }
        .stTabs [data-baseweb="tab"] {
            font-size: 12px !important;
            padding: 6px 8px !important;
        }
    }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("📈 Aylooper Finans & Yapay Zeka Paneli")

# ---------------------------------------------------------
# SABİT API KEY TANIMLAMASI
# ---------------------------------------------------------
FIXED_GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# ---------------------------------------------------------
# KALICI TAKİP LİSTESİ & ALARM YÖNETİMİ
# ---------------------------------------------------------
JSON_FILE = "takip_listesi.json"
ALARM_FILE = "alarmlar.json"

DEFAULT_WATCHLIST = [
    "KONTR.IS",
    "THYAO.IS",
    "GARAN.IS",
    "AAPL",
    "NVDA",
    "BTC-USD",
    "ETH-USD",
]


def load_watchlist():
  if os.path.exists(JSON_FILE):
    try:
      with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list) and len(data) > 0:
          if "BTC-USD" not in data:
            data.append("BTC-USD")
          return data
    except Exception:
      pass
  return DEFAULT_WATCHLIST


def save_watchlist(watchlist):
  try:
    with open(JSON_FILE, "w", encoding="utf-8") as f:
      json.dump(watchlist, f, ensure_ascii=False, indent=2)
  except Exception:
    pass


def load_alarms():
  if os.path.exists(ALARM_FILE):
    try:
      with open(ALARM_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      pass
  return {}


def save_alarms(alarms):
  try:
    with open(ALARM_FILE, "w", encoding="utf-8") as f:
      json.dump(alarms, f, ensure_ascii=False, indent=2)
  except Exception:
    pass


if "watch_list" not in st.session_state:
  st.session_state.watch_list = load_watchlist()

if "alarms" not in st.session_state:
  st.session_state.alarms = load_alarms()

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
# KÜRESEL FİNANSAL TAKVİM VERİ TABANI
# ---------------------------------------------------------
FINANCIAL_CALENDAR_EVENTS = [
    {
        "id": "tr_1",
        "country": "🇹🇷 TR",
        "title": "TCMB Politika Faizi Kararı (PPK)",
        "importance": "🔴 Yüksek",
        "date": "2026-07-30 14:00",
        "forecast": "%45.00",
        "previous": "%45.00",
        "impact_desc": (
            "BIST 100, Bankacılık (XBANK) ve Dolar/TL'yi anlık sarsar."
        ),
        "summary": "Faiz kararı ve açıklama metni borsa ve döviz yönünü belirler.",
    },
    {
        "id": "tr_2",
        "country": "🇹🇷 TR",
        "title": "Türkiye Enflasyon Verisi (TÜFE Yıllık)",
        "importance": "🔴 Yüksek",
        "date": "2026-08-03 10:00",
        "forecast": "%38.20",
        "previous": "%41.60",
        "impact_desc": (
            "BIST perakende, gıda ve faiz beklentilerini doğrudan etkiler."
        ),
        "summary": (
            "Düşüş trendinin sürmesi borsaya yabancı girişini artırabilir."
        ),
    },
    {
        "id": "us_1",
        "country": "🇺🇸 US",
        "title": "ABD Tarım Dışı İstihdam (NFP)",
        "importance": "🔴 Yüksek",
        "date": "2026-08-07 15:30",
        "forecast": "180K",
        "previous": "206K",
        "impact_desc": "Dolar Endeksi (DXY), Altın ve S&P 500/NASDAQ'ı etkiler.",
        "summary": "İşgücü piyasasının durumu Fed'in faiz patikasını çizer.",
    },
    {
        "id": "us_2",
        "country": "🇺🇸 US",
        "title": "ABD Tüketici Fiyat Endeksi (CPI Enflasyon)",
        "importance": "🔴 Yüksek",
        "date": "2026-08-12 15:30",
        "forecast": "%3.10",
        "previous": "%3.30",
        "impact_desc": (
            "Küresel borsalar ve teknoloji hisseleri (NVDA, AAPL) için en kritik"
            " veri."
        ),
        "summary": "Beklenti altı enflasyon faiz indirim beklentisini kuvvetlendirir.",
    },
]

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
        st.session_state.watch_list.append(ticker_to_add)
        save_watchlist(st.session_state.watch_list)
        st.sidebar.success(f"{ticker_to_add} eklendi!")
        st.rerun()

st.sidebar.markdown("---")
selected_stock = st.sidebar.selectbox(
    "Takip Listenizden Seçin:", st.session_state.watch_list
)

if st.sidebar.button("❌ Seçili Hisseyi Çıkar"):
  if len(st.session_state.watch_list) > 1:
    st.session_state.watch_list.remove(selected_stock)
    save_watchlist(st.session_state.watch_list)
    st.sidebar.warning(f"{selected_stock} çıkarıldı.")
    st.rerun()
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
      st.session_state.watch_list.append(quick_add_ticker)
      save_watchlist(st.session_state.watch_list)
      st.sidebar.success(f"{quick_add_ticker} eklendi!")
      st.rerun()

st.sidebar.markdown("---")
st.sidebar.success("🔑 Sabit API Key Aktif")

# ---------------------------------------------------------
# GEMINI ANALİZ FONKSİYONU
# ---------------------------------------------------------
import time
from google.api_core import exceptions


def ask_gemini_analysis(prompt, system_instruction):
  max_retries = 3
  for attempt in range(max_retries):
    try:
      model = genai.GenerativeModel(
          model_name="gemini-2.0-flash", system_instruction=system_instruction
      )
      response = model.generate_content(prompt)
      return response.text
    except exceptions.ResourceExhausted as e:
      if attempt < max_retries - 1:
        time.sleep(5 * (attempt + 1))
        continue
      else:
        return "Kota Sınırı Hatası: Lütfen birkaç dakika sonra tekrar deneyin."
    except Exception as e:
      return f"Hata oluştu: {e}"


# ---------------------------------------------------------
# ÜST DÜZEY ANA SEKMELER
# ---------------------------------------------------------
main_tab1, main_tab2, main_tab3 = st.tabs([
    "📊 Hisse Analiz Paneli",
    "📅 Makro Finansal Takvim & AI",
    "🪙 Kripto Piyasası",
])

# =========================================================
# ANA SEKMELER 1: HİSSE ANALİZ PANELİ
# =========================================================
with main_tab1:
  if selected_stock:
    try:
      if "-" in selected_stock:
        crypto_data = get_crypto_yf_stats(selected_stock)
        if crypto_data:
          current_price = crypto_data["lastPrice"]
          percent_change = crypto_data["priceChangePercent"]
          previous_close = current_price / (1 + percent_change / 100)
          price_change = current_price - previous_close
        else:
          raise Exception("Kripto verisi alınamadı.")
      else:
        ticker_obj = yf.Ticker(selected_stock)
        fast_info = ticker_obj.fast_info
        current_price = fast_info["lastPrice"]
        previous_close = fast_info["previousClose"]
        price_change = current_price - previous_close
        percent_change = (price_change / previous_close) * 100

      currency = (
          "TRY"
          if selected_stock.endswith(".IS")
          else ("USD" if "-" in selected_stock or len(selected_stock) <= 5 else "")
      )

      col1, col2 = st.columns([1, 2])

      with col1:
        st.metric(
            label=f"Anlık Fiyat ({selected_stock})",
            value=f"{current_price:.2f} {currency}",
            delta=f"{price_change:+.2f} {currency} (%{percent_change:+.2f})",
        )

      with col2:
        st.subheader("🔔 Fiyat Alarmı Yönetimi")

        # Mevcut hisse için kayıtlı alarm varsa çek
        existing_alarm = st.session_state.alarms.get(selected_stock, {})
        default_target = existing_alarm.get(
            "target", float(round(current_price, 2))
        )
        default_cond_idx = (
            0
            if existing_alarm.get("condition", "Üzerine Çıkınca")
            == "Üzerine Çıkınca"
            else 1
        )

        target_price = st.number_input(
            "Hedef Fiyat:",
            value=float(default_target),
            step=0.5,
            key=f"alarm_input_{selected_stock}",
        )
        condition = st.selectbox(
            "Koşul:",
            ["Üzerine Çıkınca", "Altına Düşünce"],
            index=default_cond_idx,
            key=f"alarm_cond_{selected_stock}",
        )

        col_a, col_b = st.columns(2)
        with col_a:
          if st.button("💾 Alarmı Kaydet", key=f"save_alarm_{selected_stock}"):
            st.session_state.alarms[selected_stock] = {
                "target": target_price,
                "condition": condition,
            }
            save_alarms(st.session_state.alarms)
            st.success(f"✅ {selected_stock} için alarm kaydedildi!")
            st.rerun()

        with col_b:
          if selected_stock in st.session_state.alarms:
            if st.button("🗑️ Alarmı Sil", key=f"del_alarm_{selected_stock}"):
              del st.session_state.alarms[selected_stock]
              save_alarms(st.session_state.alarms)
              st.warning("Alarm silindi.")
              st.rerun()

        # Kayıtlı Alarm Durum Kontrolü
        if selected_stock in st.session_state.alarms:
          saved_t = st.session_state.alarms[selected_stock]["target"]
          saved_c = st.session_state.alarms[selected_stock]["condition"]

          st.info(
              f"📌 Aktif Kayıtlı Alarm: **{saved_t} {currency}** ({saved_c})"
          )

          if saved_c == "Üzerine Çıkınca" and current_price >= saved_t:
            st.error(
                f"🚨 **ALARM TETİKLENDİ!** {selected_stock} fiyatı ({current_price:.2f}"
                f" {currency}) hedef seviyeyi geçti!"
            )
          elif saved_c == "Altına Düşünce" and current_price <= saved_t:
            st.warning(
                f"🚨 **ALARM TETİKLENDİ!** {selected_stock} fiyatı ({current_price:.2f}"
                f" {currency}) hedef seviyenin altına düştü!"
            )
        else:
          st.caption(
              "Bu varlık için kayıtlı aktif bir alarm bulunmuyor. Hedef"
              " belirleyip 'Alarmı Kaydet'e basın."
          )

    except Exception as e:
      st.error(f"Veri çekilemedi: {e}")

    st.markdown("---")
    clean_ticker = selected_stock.replace(".IS", "")

    sub_tab1, sub_tab_chart, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs([
        "🎯 Pivot Noktaları",
        "📈 Grafik",
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
# ANA SEKMELER 2: KÜRESEL TAKVİM & AI CHAT
# =========================================================
with main_tab2:
  st.header("📅 Küresel Makroekonomik Takvim & Gemini AI Portal")
  f_col1, f_col2 = st.columns(2)

  with f_col1:
    country_filter = st.selectbox(
        "🌎 Ülke / Bölge Filtresi:",
        ["Tümü", "🇹🇷 TR", "🇺🇸 US", "🇪🇺 EU", "🇬🇧 UK", "🇨🇳 CN", "🇯🇵 JP"],
    )
  with f_col2:
    importance_filter = st.selectbox(
        "🎯 Önem Derecesi Filtresi:", ["Tümü", "🔴 Yüksek", "🟡 Orta"]
    )

  filtered_events = FINANCIAL_CALENDAR_EVENTS
  if country_filter != "Tümü":
    filtered_events = [
        e for e in filtered_events if e["country"] == country_filter
    ]
  if importance_filter != "Tümü":
    filtered_events = [
        e for e in filtered_events if e["importance"] == importance_filter
    ]

  st.subheader("📋 Genel Takvim Görünümü")
  if filtered_events:
    df_cal = pd.DataFrame(filtered_events)[
        ["date", "country", "title", "importance", "forecast", "previous"]
    ]
    df_cal.columns = [
        "Tarih / Saat",
        "Ülke",
        "Açıklama / Gelişme",
        "Önem",
        "Beklenti",
        "Önceki",
    ]
    st.dataframe(df_cal, use_container_width=True, hide_index=True)

  st.markdown("---")
  st.subheader("🤖 AI Analiz Ve Soru Paneli")

  event_options = [
      f"{e['country']} | {e['title']} ({e['date']})" for e in filtered_events
  ]
  if event_options:
    selected_event_str = st.selectbox(
        "Analiz Edilecek Veya Soru Sorulacak Gelişmeyi Seçin:", event_options
    )
    matched_event = next(
        (
            e
            for e in filtered_events
            if f"{e['country']} | {e['title']} ({e['date']})"
            == selected_event_str
        ),
        filtered_events[0],
    )

    with st.expander("📌 Seçili Gelişme Detaylarını Gör", expanded=True):
      mc1, mc2, mc3 = st.columns(3)
      mc1.info(f"**Tarih:** {matched_event['date']}")
      mc2.warning(f"**Önem:** {matched_event['importance']}")
      mc3.success(
          f"**Beklenen / Önceki:** {matched_event['forecast']} /"
          f" {matched_event['previous']}"
      )
      st.caption(f"**Genel Etki Özeti:** {matched_event['impact_desc']}")

    st.markdown("### 🤖 Gemini Otomatik Piyasa Analizi")
    if st.button("🚀 Bu Gelişmeyi Gemini ile Analiz Et"):
      with st.spinner("Gemini piyasa analizini hazırlıyor..."):
        analysis_res = ask_gemini_analysis(
            matched_event["title"], str(matched_event)
        )
        st.markdown(analysis_res)

    st.markdown("### 💬 Gemini'ye Soru Sorun")
    user_q = st.text_input(
        f"'{matched_event['title']}' gelişmesiyle ilgili sorunuz:",
        placeholder=(
            "Örn: Bu enflasyon verisi BIST bankacılık ve perakende hisselerine"
            " nasıl yansır?"
        ),
    )

    if st.button("Soruyu Gemini'ye Gönder", type="primary"):
      if user_q:
        with st.spinner("Gemini yanıtlıyor..."):
          ans = ask_gemini_analysis(user_q, str(matched_event))
          st.markdown(ans)
      else:
        st.warning("Lütfen soru alanını doldurun.")

# =========================================================
# ANA SEKMELER 3: KRİPTO PİYASASI (YFINANCE)
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
