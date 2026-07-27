import json
import os
import urllib.parse
from dateutil import parser
import feedparser
import google.generativeai as genai
import pandas as pd
import requests
import streamlit as st
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
# TRADINGVIEW SEMBOL YARDIMCISI
# ---------------------------------------------------------
# MEVCUT FONKSİYONU DEĞİŞTİRİN:
def get_tradingview_symbol(ticker):
  ticker = ticker.upper().strip()
  if ticker.endswith(".IS"):
    # .IS ekini kaldırıp sadece BIST:KOD şeklinde veriyoruz
    clean_code = ticker.replace(".IS", "")
    return f"BIST:{clean_code}"
  elif "-" in ticker or "USD" in ticker or "BTC" in ticker or "ETH" in ticker:
    return f"BINANCE:{ticker.replace('-','').replace('/','')}"
  else:
    return ticker


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
        "📉 TradingView Canlı Grafik",
        "🏛️ KAP Bildirimleri (BIST)",
        "📰 Basın Haberleri",
        "🌐 Yahoo Finance",
        "🤖 Hisse Özel AI Soru Paneli",
    ])

    with sub_tab1:
      st.write("##### Standart (Klasik) Pivot Seviyeleri")
      timeframe_choice = st.radio(
          "Zaman Dilimi Seçin:", ["Günlük", "Haftalık", "Aylık"], horizontal=True
      )

      currency = (
          "TRY"
          if selected_stock.endswith(".IS")
          else ("USD" if "-" in selected_stock or len(selected_stock) <= 5 else "")
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
            "Yahoo Finance geçici olarak çok fazla istek aldığından veriler"
            " alınamadı. Lütfen 1-2 dakika bekleyip sayfayı yenileyin."
        )

with sub_tab_chart:
      st.subheader(f"📉 {selected_stock} - TradingView Canlı Teknik Grafiği")
      tv_symbol = get_tradingview_symbol(selected_stock)

      theme_mode = st.radio(
          "Grafik Modu:",
          ["Koyu Mod (Dark)", "Beyaz Mod (Light)"],
          horizontal=True,
          key="tv_theme_radio",
      )
      t_theme = "light" if "Beyaz" in theme_mode else "dark"

      tv_html = f"""
      <div class="tradingview-widget-container" style="height:600px;width:100%">
        <iframe scrolling="no" allowtransparency="true" frameborder="0" sandbox="allow-scripts allow-same-origin allow-popups" src="https://s.tradingview.com/widgetembed/?symbol={tv_symbol}&interval=D&hidesidetoolbar=1&symboledit=0&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme={t_theme}&style=1&timezone=Europe%2FIstanbul&locale=tr" style="height:100%;width:100%;"></iframe>
      </div>
      """
      st.components.v1.html(tv_html, height=620)

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
