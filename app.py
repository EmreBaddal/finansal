import json
import os
import urllib.parse
from dateutil import parser
import feedparser
import google.generativeai as genai
import pandas as pd
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

# Mobil Ekranlar İçin Özel CSS (Sidebar input genişlik düzeltmesi dahil)
st.markdown(
    """
    <style>
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
    div[data-baseweb="input"] {
        width: 100% !important;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.8rem !important;
        }
        .stMetric {
            font-size: 14px !important;
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
genai.configure(api_key=FIXED_GEMINI_API_KEY)

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
# TEMATİK SEKTÖR / DİKEY VERİ TABANI
# ---------------------------------------------------------
THEMATIC_SECTORS = {
    "🚀 Uzay ve Havacılık": [
        {"symbol": "ASTS", "name": "AST SpaceMobile (Global)"},
        {"symbol": "RKLB", "name": "Rocket Lab USA (Global)"},
        {"symbol": "BA", "name": "Boeing (Global)"},
        {"symbol": "LMT", "name": "Lockheed Martin (Global)"},
        {"symbol": "AYES.IS", "name": "Ayesaş / BIST Havacılık"},
    ],
    "🧬 Biyoteknoloji": [
        {"symbol": "MRNA", "name": "Moderna (Global)"},
        {"symbol": "PFE", "name": "Pfizer (Global)"},
        {"symbol": "BNTX", "name": "BioNTech (Global)"},
        {"symbol": "GEPH.IS", "name": "Gen İlaç (BIST)"},
    ],
    "🤖 Fiziksel Yapay Zeka & Robotik": [
        {"symbol": "NVDA", "name": "NVIDIA (AI Donanım)"},
        {"symbol": "TSLA", "name": "Tesla (Robotaksi & Optimus)"},
        {"symbol": "ISCTR.IS", "name": "İş Bankası (Teknoloji)"},
        {"symbol": "KONTR.IS", "name": "Kontrolmatik (Robotik & Enerji)"},
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
        "title": "ABD TÜFE (Enflasyon) Verisi",
        "importance": "🔴 Yüksek",
        "date": "2026-08-12 15:30",
        "forecast": "%2.9",
        "previous": "%3.0",
        "impact_desc": "Fed'in sonraki toplantı faiz beklentilerini doğrudan fiyatlar.",
        "summary": (
            "Enflasyondaki düşüş veya yapışkanlık küresel borsaların kaderini"
            " tayin eder."
        ),
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
# YARDIMCI FONKSİYONLAR
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
    else:
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
  return None


# ---------------------------------------------------------
# SOL MENÜ
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
selected_sector_key = st.sidebar.selectbox(
    "Sektör Dikey Seçin:", ["Özel Liste (Manuel)"] + list(THEMATIC_SECTORS.keys())
)

if selected_sector_key != "Özel Liste (Manuel)":
  sector_items = THEMATIC_SECTORS[selected_sector_key]
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
    except exceptions.ResourceExhausted:
      if attempt < max_retries - 1:
        time.sleep(5 * (attempt + 1))
        continue
      else:
        return "Kota Sınırı Hatası: Lütfen birkaç dakika sonra tekrar deneyin."
    except Exception as e:
      return f"Hata oluştu: {e}"


# ---------------------------------------------------------
# ANA SEKMELER
# ---------------------------------------------------------
main_tab1, main_tab2, main_tab3 = st.tabs([
    "📊 Hisse Analiz Paneli",
    "📅 Makro Finansal Takvim & AI",
    "🪙 Kripto Piyasası",
])

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
        target_price = st.number_input(
            "Hedef Fiyat:",
            value=float(default_target),
            step=0.5,
            key=f"alarm_input_{selected_stock}",
        )
        condition = st.selectbox(
            "Koşul:",
            ["Üzerine Çıkınca", "Altına Düşünce"],
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
            st.success("Alarm kaydedildi!")
            st.rerun()
        with col_b:
          if selected_stock in st.session_state.alarms:
            if st.button("🗑️ Alarmı Sil", key=f"del_alarm_{selected_stock}"):
              del st.session_state.alarms[selected_stock]
              save_alarms(st.session_state.alarms)
              st.warning("Alarm silindi.")
              st.rerun()

    except Exception as e:
      st.error(f"Veri çekilemedi: {e}")

    st.markdown("---")
    clean_ticker = selected_stock.replace(".IS", "")

    sub_tab1, sub_tab_chart, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
        "🎯 Pivot Noktaları",
        "📉 TradingView Canlı Grafik",
        "🏛️ KAP Bildirimleri (BIST)",
        "📰 Basın Haberleri",
        "🤖 Hisse Özel AI Soru Paneli",
    ])

    with sub_tab1:
      st.write("##### Standart Pivot Seviyeleri")
      timeframe_choice = st.radio(
          "Zaman Dilimi Seçin:", ["Günlük", "Haftalık", "Aylık"], horizontal=True
      )
      p_data = calculate_pivot_points(selected_stock, timeframe_choice)
      if p_data:
        c1, c2, c3 = st.columns(3)
        with c1:
          st.error(f"**R3:** {p_data.get('Direnç 3 (R3)')}")
          st.error(f"**R2:** {p_data.get('Direnç 2 (R2)')}")
          st.error(f"**R1:** {p_data.get('Direnç 1 (R1)')}")
        with c2:
          st.info(f"**Pivot (P):** {p_data.get('Pivot (P)')}")
        with c3:
          st.success(f"**S1:** {p_data.get('Destek 1 (S1)')}")
          st.success(f"**S2:** {p_data.get('Destek 2 (S2)')}")
          st.success(f"**S3:** {p_data.get('Destek 3 (S3)')}")

    with sub_tab_chart:
      st.subheader(f"📉 {selected_stock} - TradingView Grafik Entegrasyonu")

      tv_symbol = selected_stock
      if selected_stock.endswith(".IS"):
        tv_symbol = f"BIST:{selected_stock.replace('.IS', '')}"
      elif "-" in selected_stock:
        tv_symbol = f"BINANCE:{selected_stock.replace('-USD', 'USDT')}"
      else:
        tv_symbol = f"NASDAQ:{selected_stock}"

      tv_url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"

      st.markdown(
          f"""
            <div style="padding: 20px; background-color: #1e222d; border-radius: 10px; text-align: center; color: white; margin-bottom: 15px;">
                <h3>📊 {selected_stock} İçin Gelişmiş Grafik</h3>
                <p>Tam çizim araçları, göstergeler ve esneklik için doğrudan TradingView platformunu açabilirsiniz:</p>
                <a href="{tv_url}" target="_blank" style="background-color: #2962ff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; margin-top: 10px;">🚀 TradingView'de Canlı Aç</a>
            </div>
            """,
          unsafe_allow_html=True,
      )

      theme_mode = st.radio(
          "Gömülü Widget Modu:",
          ["Koyu Mod (Dark)", "Beyaz Mod (Light)"],
          horizontal=True,
          key="tv_theme_radio",
      )
      t_theme = "light" if "Beyaz" in theme_mode else "dark"

      tv_html = f"""
            <div class="tradingview-widget-container" style="height:500px;width:100%">
              <div id="tradingview_chart" style="height:100%;width:100%"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget(
              {{
                "autosize": true,
                "symbol": "{tv_symbol}",
                "interval": "D",
                "timezone": "Europe/Istanbul",
                "theme": "{t_theme}",
                "style": "1",
                "locale": "tr",
                "toolbar_bg": "#f1f3f6",
                "enable_publishing": false,
                "allow_symbol_change": true,
                "container_id": "tradingview_chart"
              }}
              );
              </script>
            </div>
            """
      components.html(tv_html, height=520)

    with sub_tab2:
      if selected_stock.endswith(".IS"):
        kap_news = fetch_rss_news_sorted(f"site:kap.org.tr {clean_ticker}")
        for item in kap_news[:10]:
          st.markdown(f"* [{item['title']}]({item['link']})")
      else:
        st.info("KAP bildirimleri sadece BIST hisseleri içindir.")

    with sub_tab3:
      g_news = fetch_rss_news_sorted(f"{clean_ticker} hisse haber OR borsa")
      for item in g_news[:10]:
        st.markdown(f"* [{item['title']}]({item['link']})")

    with sub_tab4:
      stock_user_q = st.text_input(
          f"{selected_stock} hakkında neyi öğrenmek istiyorsun?",
          key="stock_ai_input",
      )
      if st.button("💬 Soruyu Gemini'ye İlet", key="stock_ai_btn"):
        if stock_user_q:
          ans = ask_gemini_analysis(
              stock_user_q, f"Seçilen Hisse: {selected_stock}"
          )
          st.markdown(ans)

with main_tab2:
  st.header("📅 Küresel Makroekonomik Takvim ve Yapay Zeka Analizi")
  st.write(
      "Önümüzdeki kritik makro verileri inceleyin ve Gemini'ye detaylı etkilerini"
      " sorun."
  )

  df_cal = pd.DataFrame(FINANCIAL_CALENDAR_EVENTS)[
      ["date", "country", "title", "importance", "forecast", "previous"]
  ]
  st.dataframe(df_cal, use_container_width=True, hide_index=True)

  st.markdown("---")
  st.subheader("🔍 Etkinlik Bazlı Yapay Zeka Analizi")

  event_titles = [e["title"] for e in FINANCIAL_CALENDAR_EVENTS]
  selected_event_title = st.selectbox(
      "Analiz Edilecek Veriyi Seçin:", event_titles
  )

  selected_event = next(
      e for e in FINANCIAL_CALENDAR_EVENTS if e["title"] == selected_event_title
  )

  st.info(
      f"**Özet:** {selected_event['summary']} \n\n**Olası Etki:**"
      f" {selected_event['impact_desc']}"
  )

  user_cal_q = st.text_input(
      "Bu makro veri hakkında Gemini'ye özel bir soru sorun:",
      key="cal_ai_input",
  )
  if st.button("🧠 Takvim Verisini Gemini ile Analiz Et", key="cal_ai_btn"):
    prompt = (
        f"Etkinlik: {selected_event['title']}\nTarih:"
        f" {selected_event['date']}\nÜlke: {selected_event['country']}\nÖnem:"
        f" {selected_event['importance']}\nTahmin: {selected_event['forecast']}"
        f"\nÖnceki: {selected_event['previous']}\nAçıklama:"
        f" {selected_event['summary']}\n\nKullanıcı Sorusu:"
        f" {user_cal_q if user_cal_q else 'Bu veri piyasaları nasıl etkiler?'}"
    )
    ans = ask_gemini_analysis(
        prompt,
        "Sen kıdemli bir küresel makroekonomist ve piyasa analistisin.",
    )
    st.markdown(ans)

with main_tab3:
  st.header("🪙 Kripto Piyasası Canlı Takibi")
  selected_crypto = st.selectbox(
      "İşlem Çifti Seçin:", ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD"]
  )
  stats = get_crypto_yf_stats(selected_crypto)
  if stats:
    st.metric("Anlık Fiyat", f"${stats['lastPrice']:,.2f}")
