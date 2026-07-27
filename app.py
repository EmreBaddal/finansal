import streamlit as st
import yfinance as yf
import requests
import feedparser
from datetime import datetime
import pandas as pd
import google.generativeai as genai

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="Aylooper Finans & AI Paneli",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS STİLLERİ ---
st.markdown("""
    <style>
    .main {
        background-color: #ffffff;
        color: #111111;
    }
    [data-testid="stSidebar"] {
        background-color: #0e1117;
        color: #ffffff;
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
        color: #ffffff !important;
    }
    div.stButton > button {
        background-color: #ff4b4b;
        color: white;
        border-radius: 6px;
        border: none;
        font-weight: bold;
    }
    div.stButton > button:hover {
        background-color: #ff2b2b;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# --- YARDIMCI FONKSİYONLAR ---

def get_tradingview_symbol(ticker):
    """TradingView widget'ı için doğru sembol formatını döner."""
    ticker = ticker.upper().strip()
    if ticker.endswith(".IS"):
        return f"BIST:{ticker.replace('.IS', '')}"
    elif "-" in ticker or "USD" in ticker or "BTC" in ticker or "ETH" in ticker:
        return f"BINANCE:{ticker.replace('-','').replace('/','')}"
    else:
        return ticker

def calculate_pivot_points(ticker, timeframe):
    """Yahoo Finance verileri üzerinden klasik pivot noktalarını hesaplar."""
    try:
        yf_ticker = yf.Ticker(ticker)
        if timeframe == "Günlük":
            df = yf_ticker.history(period="5d", interval="1d")
        elif timeframe == "Haftalık":
            df = yf_ticker.history(period="1mo", interval="1wk")
        else:
            df = yf_ticker.history(period="1y", interval="1mo")
            
        if len(df) < 2:
            return None
        
        prev_row = df.iloc[-2]
        high = prev_row['High']
        low = prev_row['Low']
        close = prev_row['Close']
        
        pivot = (high + low + close) / 3
        r1 = (2 * pivot) - low
        s1 = (2 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        r3 = high + 2 * (pivot - low)
        s3 = low - 2 * (high - pivot)
        
        return {
            "Pivot (P)": round(pivot, 2),
            "Direnç 1 (R1)": round(r1, 2),
            "Direnç 2 (R2)": round(r2, 2),
            "Direnç 3 (R3)": round(r3, 2),
            "Destek 1 (S1)": round(s1, 2),
            "Destek 2 (S2)": round(s2, 2),
            "Destek 3 (S3)": round(s3, 2)
        }
    except Exception:
        return None

def fetch_rss_news_sorted(query):
    """Google Haberler RSS üzerinden arama yapar ve kronolojik sıralar."""
    try:
        url = f"https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"
        feed = feedparser.parse(url)
        news_list = []
        for entry in feed.entries[:8]:
            pub_date = entry.get('published_parsed')
            if pub_date:
                dt_obj = datetime(*pub_date[:6])
                published_str = dt_obj.strftime("%d.%m.%Y %H:%M")
            else:
                published_str = "Tarih Yok"
                dt_obj = datetime.min
                
            news_list.append({
                "title": entry.title,
                "link": entry.link,
                "published_str": published_str,
                "dt": dt_obj
            })
        news_list.sort(key=lambda x: x["dt"], reverse=True)
        return news_list
    except Exception:
        return []

def ask_gemini_analysis(prompt, system_instruction=""):
    """Google Gemini AI modelinden finansal analiz yanıtı alır."""
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
        if not api_key:
            return "⚠️ Gemini API Anahtarı bulunamadı. Lütfen Streamlit secrets ayarlarına ekleyin."
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=system_instruction
        )
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ AI analizi üretilirken hata oluştu: {str(e)}"

# --- YAN MENÜ (SİDEBAR) ---
st.sidebar.title("📊 Hisse Yönetimi")
st.sidebar.caption("Takip Listesi & Arama Paneli")

user_input_ticker = st.sidebar.text_input("Hisse Arayın (Örn: THYAO, IVDA, BTC-USD):", placeholder="THYAO.IS")

# Kayıtlı tüm varlıklar ve tematik listeler
if "watchlist" not in st.session_state:
    st.session_state.watchlist = ["THYAO.IS", "KAPLM.IS", "KONTR.IS", "GARAN.IS", "AAPL", "NVDA", "BTC-USD", "ETH-USD"]

# Tematik Sektör Dikey Seçimleri ve İçerikleri
st.sidebar.markdown("---")
st.sidebar.markdown("### 🌐 Tematik Dikey Filtreler")
sector_filter = st.sidebar.selectbox(
    "Sektör Dikey Seçin:", 
    ["Özel Liste (Manuel)", "Teknoloji & Enerji", "Bankacılık & Holding", "Kripto Varlıklar", "Uzay, Havacılık & Fiziksel AI"]
)

# Tematik seçime göre listeyi dinamik filtreleme veya güncelleme mantığı
if sector_filter == "Teknoloji & Enerji":
    thematic_stocks = ["KONTR.IS", "AAPL", "NVDA"]
    for s in thematic_stocks:
        if s not in st.session_state.watchlist:
            st.session_state.watchlist.append(s)
elif sector_filter == "Bankacılık & Holding":
    thematic_stocks = ["GARAN.IS", "THYAO.IS"]
    for s in thematic_stocks:
        if s not in st.session_state.watchlist:
            st.session_state.watchlist.append(s)
elif sector_filter == "Kripto Varlıklar":
    crypto_stocks = ["BTC-USD", "ETH-USD", "BNB-USD"]
    for s in crypto_stocks:
        if s not in st.session_state.watchlist:
            st.session_state.watchlist.append(s)
elif sector_filter == "Uzay, Havacılık & Fiziksel AI":
    space_stocks = ["THYAO.IS", "NVDA"]
    for s in space_stocks:
        if s not in st.session_state.watchlist:
            st.session_state.watchlist.append(s)

if user_input_ticker:
    formatted_ticker = user_input_ticker.strip().upper()
    if formatted_ticker not in st.session_state.watchlist:
        st.session_state.watchlist.append(formatted_ticker)

selected_stock = st.sidebar.selectbox("Takip Listenizden Seçin:", st.session_state.watchlist)

if st.sidebar.button("❌ Seçili Hisseyi Çıkar"):
    if selected_stock in st.session_state.watchlist:
        st.session_state.watchlist.remove(selected_stock)
        st.rerun()

# --- ANA EKRAN ---
st.title("🚀 Aylooper Finans & AI Paneli")
st.markdown(f"**Aktif Varlık:** `{selected_stock}` | **Zaman:** `{datetime.now().strftime('%d.%m.%Y %H:%M')}`")

clean_ticker = selected_stock.replace(".IS", "")
current_price = 0.0
percent_change = 0.0

try:
    ticker_obj = yf.Ticker(selected_stock)
    todays_data = ticker_obj.history(period="2d")
    if not todays_data.empty:
        current_price = todays_data['Close'].iloc[-1]
        if len(todays_data) >= 2:
            prev_close = todays_data['Close'].iloc[-2]
            percent_change = ((current_price - prev_close) / prev_close) * 100
        else:
            percent_change = 0.0
    else:
        current_price = 0.0
        percent_change = 0.0
except Exception:
    current_price = 0.0
    percent_change = 0.0

col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    st.metric(label="Seçilen Varlık", value=selected_stock)
with col_m2:
    currency_label = "TRY" if selected_stock.endswith(".IS") else "USD"
    st.metric(label="Son Fiyat", value=f"{current_price:,.2f} {currency_label}", delta=f"%{percent_change:.2f}")
with col_m3:
    st.info("💡 Fiyat alarm sistemi devrede. Hedef fiyat takipleri arka planda izlenmektedir.")

st.markdown("---")

# --- SEKMELER (TABS) ---
sub_tab1, sub_tab_chart, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs([
    "🎯 Pivot Noktaları",
    "📉 TradingView Canlı Grafik",
    "🏛️ KAP Bildirimleri (BIST)",
    "📰 Basın Haberleri",
    "🌐 Yahoo Finance",
    "🤖 Hisse Özel AI Soru Paneli"
])

with sub_tab1:
    st.write("##### Standart (Klasik) Pivot Seviyeleri")
    timeframe_choice = st.radio("Zaman Dilimi Seçin:", ["Günlük", "Haftalık", "Aylık"], horizontal=True)
    
    currency = "TRY" if selected_stock.endswith(".IS") else ("USD" if "-" in selected_stock or len(selected_stock) <= 5 else "")
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
        st.warning("Yahoo Finance geçici olarak çok fazla istek aldığından veriler alınamadı. Lütfen 1-2 dakika bekleyip sayfayı yenileyin.")

with sub_tab_chart:
    st.subheader(f"📉 {selected_stock} - TradingView Canlı Teknik Grafiği")
    tv_symbol = get_tradingview_symbol(selected_stock)
    
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:600px;width:100%">
      <iframe scrolling="no" allowtransparency="true" frameborder="0" sandbox="allow-scripts allow-same-origin allow-popups" src="https://s.tradingview.com/widgetembed/?symbol={tv_symbol}&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=light&style=1&timezone=Europe%2FIstanbul&locale=tr" style="height:100%;width:100%;"></iframe>
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
                st.markdown(f"* [{item['title']}]({item['link']}) — <small style='color:gray;'>📅 {item['published_str']}</small>", unsafe_allow_html=True)
        else:
            st.info("KAP bildirimleri bulunamadı.")
    else:
        st.info("KAP bildirimleri sadece BIST hisseleri içindir.")

with sub_tab3:
    g_news = fetch_rss_news_sorted(f"{clean_ticker} hisse haber OR borsa")
    if g_news:
        for item in g_news:
            st.markdown(f"* [{item['title']}]({item['link']}) — *{item['source']}*  \n  <small style='color:gray;'>📅 {item['published_str']}</small>", unsafe_allow_html=True)
    else:
        st.info("İlgili haber bulunamadı.")

with sub_tab4:
    try:
        ticker_obj_yf = yf.Ticker(selected_stock)
        news_list = ticker_obj_yf.news
        if news_list:
            for item in news_list[:7]:
                title = item.get('title') or item.get('content', {}).get('title', 'Başlık Yok')
                link = item.get('link') or item.get('content', {}).get('canonicalUrl', {}).get('url', '#')
                st.markdown(f"* [{title}]({link})")
        else:
            st.info("Yahoo Finance haberi bulunamadı.")
    except Exception:
        st.write("Yahoo haberleri yüklenemedi.")

with sub_tab5:
    st.subheader(f"🤖 {selected_stock} için Gemini AI Asistanı")
    st.caption("Bu hisseyle ilgili güncel durum, beklentiler, teknik seviyeler veya sektör dinamikleri hakkında dilediğin soruyu sorabilirsin.")
    
    stock_user_q = st.text_input(
        f"{selected_stock} hakkında neyi öğrenmek istiyorsun?",
        placeholder="Örn: Bu hissenin son dönemdeki performansını ve teknik görünümünü değerlendir.",
        key="stock_ai_input"
    )
    
    if st.button("💬 Soruyu Gemini'ye İlet", key="stock_ai_btn"):
        if stock_user_q:
            with st.spinner("Gemini analiz ediyor..."):
                stock_context_data = f"Seçilen Hisse: {selected_stock}, Güncel Fiyat: {current_price} {currency}, Değişim: %{percent_change:.2f}"
                stock_ans = ask_gemini_analysis(
                    prompt=stock_user_q,
                    system_instruction=f"Seçilen Hisse: {selected_stock}. Bağlam verileri:\n{stock_context_data}"
                )
                st.markdown(stock_ans)
        else:
            st.warning("Lütfen bir soru yazın.")
