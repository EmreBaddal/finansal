# Aylooper Finans – Varlık Günlüğü ve Ücretsiz Fiyat Alarmı Kurulumu

Bu sürüm mevcut uygulamanın üzerine aşağıdaki özellikleri ekler:

- Her hisse ve coin için kalıcı **Varlık Günlüğü**
- Günlük kaydı ekleme, düzenleme, durum değiştirme ve silme
- Günlük kaydından otomatik hedef/stop alarmı üretme
- Bağımsız fiyat alarmı oluşturma
- Tek seferlik veya her seviye geçişinde çalışan alarm
- Alarm geçmişi
- Uygulama açıkken 60 saniyede bir kontrol
- Uygulama kapalıyken GitHub Actions ile 30 dakikada bir ücretsiz kontrol
- ntfy ile telefon bildirimi
- Takip listesinden çıkarılan varlığın günlük ve alarm geçmişini koruma
- Supabase kurulana kadar yerel JSON yedek modu

## Proje dosyaları

- `app.py`: Streamlit uygulaması
- `finance_storage.py`: Supabase ve yerel veri katmanı
- `alert_engine.py`: Fiyat kontrolü ve ntfy bildirimi
- `alarm_worker.py`: GitHub Actions arka plan görevi
- `supabase_schema.sql`: Veritabanı tabloları
- `requirements.txt`: Streamlit uygulaması paketleri
- `requirements-worker.txt`: Arka plan görevinin minimal paketleri
- `.github/workflows/price-alerts.yml`: 30 dakikalık alarm kontrolü
- `.streamlit/secrets.toml.example`: Gizli ayar şablonu

---

## 1. Supabase ücretsiz proje oluştur

1. Supabase hesabına gir ve yeni bir ücretsiz proje oluştur.
2. Proje açılınca sol menüden **SQL Editor** bölümüne gir.
3. `supabase_schema.sql` dosyasının tamamını kopyala.
4. SQL Editor içine yapıştır ve **Run** düğmesine bas.
5. **Project Settings > API** bölümünden şu iki değeri al:
   - Project URL
   - `service_role` key

`service_role` anahtarını GitHub koduna veya normal bir dosyaya yazma. Yalnızca Streamlit ve GitHub Secrets içinde sakla.

## 2. ntfy telefon bildirimi

1. Telefona ntfy uygulamasını kur.
2. Çok uzun ve tahmin edilmesi zor bir konu adı oluştur. Örnek:
   `aylooper-8f7d2c91-uzun-gizli-konu`
3. Telefonda bu konuya abone ol.
4. Aynı konu adını aşağıdaki `NTFY_TOPIC` alanına yaz.

Ücretsiz ntfy.sh konusu gizli parola değildir. Bu nedenle kısa ve tahmin edilebilir konu adı kullanma.

## 3. Streamlit Secrets ayarları

Streamlit Community Cloud uygulamasında:

**App settings > Secrets** bölümüne gir ve aşağıdaki yapıyı kendi değerlerinle ekle:

```toml
GEMINI_API_KEY = "mevcut-gemini-api-anahtariniz"
GEMINI_MODEL = "gemini-3.6-flash"

SUPABASE_URL = "https://PROJE_KODUNUZ.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "supabase-service-role-key"

NTFY_TOPIC = "aylooper-uzun-rastgele-gizli-konu-adi"
NTFY_SERVER = "https://ntfy.sh"

APP_PASSWORD = "guclu-uygulama-parolasi"
```

`APP_PASSWORD` zorunlu değildir ancak finans günlüğünün başkaları tarafından görülmemesi için kullanılması önerilir.

## 4. GitHub Actions Secrets ayarları

GitHub deposunda:

**Settings > Secrets and variables > Actions > New repository secret**

Şu secret değerlerini ayrı ayrı ekle:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `NTFY_TOPIC`
- `NTFY_SERVER` → `https://ntfy.sh`

`GEMINI_API_KEY` arka plan alarm görevi için gerekli değildir.

## 5. GitHub Actions alarmını ilk kez test et

1. GitHub deposunda **Actions** sekmesine gir.
2. **Aylooper Fiyat Alarmları** iş akışını seç.
3. **Run workflow** düğmesine bas.
4. İşlem yeşil tamamlanırsa arka plan kontrolü hazırdır.

İş akışı bundan sonra yaklaşık 30 dakikada bir çalışır. GitHub zamanlanmış görevleri yoğunluk nedeniyle birkaç dakika gecikebilir.

## 6. Uygulamayı yayınla

Tüm proje klasörünü GitHub deposuna yükle. Streamlit ana dosyası olarak `app.py` seçili olmalıdır.

Uygulama ilk açıldığında:

- Sidebar’da `☁️ Kalıcı veri: Supabase aktif` yazmalı.
- `🔔 ntfy bildirimi aktif` yazmalı.
- Her varlığın altında `📝 Varlık Günlüğü` ve `🔔 Alarmlar` sekmeleri görünmeli.

## Alarm çalışma mantığı

Üzerine çıkma alarmı:

```text
önceki fiyat < hedef <= güncel fiyat
```

Altına düşme alarmı:

```text
önceki fiyat > hedef >= güncel fiyat
```

Bu yöntem, fiyat hedefin üzerinde veya altında kaldığı sürece alarmın her kontrolde tekrar etmesini önler.

## Ücretsiz kullanım tasarımı

- Streamlit Community Cloud ücretsiz katmanı
- Supabase Free veritabanı
- ntfy.sh ücretsiz bildirim
- GitHub Actions 30 dakikalık minimal görev
- Plotly ücretsiz
- TradingView desteklenen widget sembolleri
- Yahoo Finance/yfinance fiyat verisi

Yahoo Finance verisi kişisel takip içindir; garantili, borsa lisanslı veya saniyelik işlem terminali verisi değildir.

## Yerel mod uyarısı

Supabase secrets eksikse uygulama çalışmaya devam eder ve `.aylooper_data` klasöründe JSON dosyaları oluşturur. Bu mod bilgisayarda test için uygundur. Streamlit Cloud yeniden başlatıldığında bu yerel dosyalar kaybolabileceğinden kalıcı kullanımda Supabase kurulmalıdır.
