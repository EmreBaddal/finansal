"""Ücretsiz FMP ekonomik takvim istemcisi.

- Stable economic-calendar endpoint'ini kullanır.
- Veriyi bir saat Streamlit önbelleğinde tutar.
- Yalnız büyük ekonomilerdeki yüksek ve orta önem olaylarını normalleştirir.
- API geçici olarak çalışmazsa son başarılı yerel kopyayı kullanır.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from dateutil import parser


FMP_ECONOMIC_CALENDAR_URL = (
    "https://financialmodelingprep.com/stable/economic-calendar"
)
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
LOCAL_CACHE_PATH = Path(".aylooper_data/economic_calendar_cache.json")
CACHE_TTL_SECONDS = 3600

REGION_ORDER = [
    "Türkiye",
    "ABD",
    "Euro Bölgesi",
    "Avrupa",
    "İngiltere",
    "Japonya",
    "Çin",
    "Kanada",
    "Avustralya",
    "İsviçre",
    "Güney Kore",
    "Hindistan",
]

COUNTRY_ALIASES = {
    # Türkiye
    "TR": ("Türkiye", "🇹🇷 Türkiye"),
    "TURKEY": ("Türkiye", "🇹🇷 Türkiye"),
    "TÜRKIYE": ("Türkiye", "🇹🇷 Türkiye"),
    "TURKIYE": ("Türkiye", "🇹🇷 Türkiye"),
    # ABD
    "US": ("ABD", "🇺🇸 ABD"),
    "USA": ("ABD", "🇺🇸 ABD"),
    "UNITED STATES": ("ABD", "🇺🇸 ABD"),
    # Euro Bölgesi
    "EU": ("Euro Bölgesi", "🇪🇺 Euro Bölgesi"),
    "EA": ("Euro Bölgesi", "🇪🇺 Euro Bölgesi"),
    "EMU": ("Euro Bölgesi", "🇪🇺 Euro Bölgesi"),
    "EURO AREA": ("Euro Bölgesi", "🇪🇺 Euro Bölgesi"),
    "EUROZONE": ("Euro Bölgesi", "🇪🇺 Euro Bölgesi"),
    "EURO ZONE": ("Euro Bölgesi", "🇪🇺 Euro Bölgesi"),
    # Büyük Avrupa ekonomileri
    "DE": ("Avrupa", "🇩🇪 Almanya"),
    "GERMANY": ("Avrupa", "🇩🇪 Almanya"),
    "FR": ("Avrupa", "🇫🇷 Fransa"),
    "FRANCE": ("Avrupa", "🇫🇷 Fransa"),
    "IT": ("Avrupa", "🇮🇹 İtalya"),
    "ITALY": ("Avrupa", "🇮🇹 İtalya"),
    "ES": ("Avrupa", "🇪🇸 İspanya"),
    "SPAIN": ("Avrupa", "🇪🇸 İspanya"),
    "NL": ("Avrupa", "🇳🇱 Hollanda"),
    "NETHERLANDS": ("Avrupa", "🇳🇱 Hollanda"),
    # İngiltere
    "GB": ("İngiltere", "🇬🇧 İngiltere"),
    "UK": ("İngiltere", "🇬🇧 İngiltere"),
    "UNITED KINGDOM": ("İngiltere", "🇬🇧 İngiltere"),
    # Asya ve diğer büyük ekonomiler
    "JP": ("Japonya", "🇯🇵 Japonya"),
    "JAPAN": ("Japonya", "🇯🇵 Japonya"),
    "CN": ("Çin", "🇨🇳 Çin"),
    "CHINA": ("Çin", "🇨🇳 Çin"),
    "CA": ("Kanada", "🇨🇦 Kanada"),
    "CANADA": ("Kanada", "🇨🇦 Kanada"),
    "AU": ("Avustralya", "🇦🇺 Avustralya"),
    "AUSTRALIA": ("Avustralya", "🇦🇺 Avustralya"),
    "CH": ("İsviçre", "🇨🇭 İsviçre"),
    "SWITZERLAND": ("İsviçre", "🇨🇭 İsviçre"),
    "KR": ("Güney Kore", "🇰🇷 Güney Kore"),
    "SOUTH KOREA": ("Güney Kore", "🇰🇷 Güney Kore"),
    "KOREA, SOUTH": ("Güney Kore", "🇰🇷 Güney Kore"),
    "IN": ("Hindistan", "🇮🇳 Hindistan"),
    "INDIA": ("Hindistan", "🇮🇳 Hindistan"),
}

HIGH_IMPACT_KEYWORDS = (
    "interest rate decision",
    "rate decision",
    "policy rate",
    "fomc",
    "fed funds",
    "ecb",
    "boe",
    "boj",
    "central bank",
    "consumer price index",
    "cpi",
    "inflation rate",
    "non farm payroll",
    "nonfarm payroll",
    "nfp",
    "unemployment rate",
    "gross domestic product",
    "gdp",
    "core pce",
    "pce price",
)

MEDIUM_IMPACT_KEYWORDS = (
    "pmi",
    "retail sales",
    "industrial production",
    "producer price",
    "ppi",
    "consumer confidence",
    "consumer sentiment",
    "jobless claims",
    "employment change",
    "trade balance",
    "current account",
    "manufacturing",
    "services",
    "factory orders",
    "durable goods",
    "housing starts",
    "building permits",
    "existing home sales",
    "new home sales",
    "business confidence",
    "economic sentiment",
    "wage",
    "earnings",
)

TR_HIGH_KEYWORDS = (
    "faiz kararı",
    "politika faizi",
    "enflasyon",
    "tüfe",
    "işsizlik",
    "gayri safi",
    "gsyh",
)

TR_MEDIUM_KEYWORDS = (
    "pmi",
    "perakende",
    "sanayi üretimi",
    "üfe",
    "güven",
    "dış ticaret",
    "cari denge",
    "imalat",
    "hizmet",
    "konut",
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_country(value: Any) -> Optional[tuple[str, str]]:
    key = _clean_text(value).upper()
    return COUNTRY_ALIASES.get(key)


def _normalize_impact(value: Any, event_name: str) -> Optional[str]:
    raw = _clean_text(value).lower()
    if raw in {"high", "3", "high impact"}:
        return "🔴 Yüksek"
    if raw in {"medium", "moderate", "2", "medium impact"}:
        return "🟡 Orta"
    if raw in {"low", "1", "low impact", "holiday", "none"}:
        return None

    event_lower = event_name.lower()
    if any(keyword in event_lower for keyword in HIGH_IMPACT_KEYWORDS + TR_HIGH_KEYWORDS):
        return "🔴 Yüksek"
    if any(keyword in event_lower for keyword in MEDIUM_IMPACT_KEYWORDS + TR_MEDIUM_KEYWORDS):
        return "🟡 Orta"
    return None


def _parse_utc_datetime(value: Any) -> Optional[datetime]:
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = parser.parse(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def _number_or_none(value: Any) -> Optional[float]:
    if value in (None, "", "null", "None", "N/A"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _format_value(value: Any, unit: Any) -> str:
    number = _number_or_none(value)
    if number is None:
        text = _clean_text(value)
        return text if text else "—"

    if abs(number) >= 1_000_000:
        formatted = f"{number:,.0f}"
    elif abs(number) >= 100:
        formatted = f"{number:,.1f}".rstrip("0").rstrip(".")
    else:
        formatted = f"{number:,.3f}".rstrip("0").rstrip(".")

    unit_text = _clean_text(unit)
    if not unit_text:
        return formatted
    if unit_text in {"%", "K", "M", "B", "T"}:
        return f"{formatted}{unit_text}"
    return f"{formatted} {unit_text}"


def _market_context(event_name: str, region: str) -> str:
    event_lower = event_name.lower()
    if any(k in event_lower for k in ("interest rate", "policy rate", "faiz", "fomc", "ecb", "boe", "boj")):
        return "Faiz, tahvil getirileri, döviz ve hisse değerlemeleri üzerinde doğrudan etkili olabilir."
    if any(k in event_lower for k in ("inflation", "consumer price", "cpi", "pce", "tüfe", "enflasyon")):
        return "Enflasyon görünümü merkez bankası beklentilerini, tahvil faizlerini ve büyüme hisselerini etkileyebilir."
    if any(k in event_lower for k in ("employment", "payroll", "unemployment", "jobless", "işsizlik")):
        return "İşgücü verisi büyüme ve faiz patikası beklentilerini değiştirebilir."
    if any(k in event_lower for k in ("gdp", "gross domestic", "gsyh")):
        return "Büyüme verisi risk iştahı, döviz ve ülke endekslerinde oynaklık yaratabilir."
    if "pmi" in event_lower or "manufacturing" in event_lower or "services" in event_lower:
        return "Öncü faaliyet göstergesi olarak sektör ve büyüme beklentilerini etkileyebilir."
    if "retail sales" in event_lower or "perakende" in event_lower:
        return "Tüketim eğilimi ve büyüme beklentileri açısından izlenir."
    return f"{region} ekonomisine ilişkin beklentileri ve ilgili piyasa fiyatlamalarını etkileyebilir."


def normalize_fmp_events(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        country_info = _normalize_country(row.get("country"))
        if country_info is None:
            continue
        region, country_label = country_info

        title = _clean_text(row.get("event") or row.get("title") or row.get("name"))
        if not title:
            continue

        importance = _normalize_impact(row.get("impact"), title)
        if importance is None:
            continue

        utc_dt = _parse_utc_datetime(
            row.get("date")
            or row.get("datetime")
            or row.get("timestamp")
        )
        if utc_dt is None:
            continue

        local_dt = utc_dt.astimezone(ISTANBUL_TZ)
        unit = row.get("unit")
        actual_raw = row.get("actual")
        estimate_raw = row.get("estimate")
        previous_raw = row.get("previous")
        actual_value = _number_or_none(actual_raw)
        status = "✅ Açıklandı" if actual_value is not None else "⏳ Bekleniyor"

        event_id = f"{utc_dt.isoformat()}|{country_label}|{title}"
        if event_id in seen:
            continue
        seen.add(event_id)

        events.append(
            {
                "id": event_id,
                "date": local_dt.strftime("%d.%m.%Y %H:%M"),
                "date_iso": local_dt.isoformat(),
                "date_utc": utc_dt.isoformat(),
                "region": region,
                "country": country_label,
                "country_code": _clean_text(row.get("country")).upper(),
                "currency": _clean_text(row.get("currency")),
                "title": title,
                "importance": importance,
                "status": status,
                "actual": _format_value(actual_raw, unit),
                "forecast": _format_value(estimate_raw, unit),
                "previous": _format_value(previous_raw, unit),
                "unit": _clean_text(unit),
                "impact_desc": _market_context(title, region),
                "summary": (
                    "Veri açıklandı; gerçekleşen değer beklenti ve önceki veriyle karşılaştırılabilir."
                    if actual_value is not None
                    else "Veri henüz açıklanmadı; beklenti ve önceki değer piyasa fiyatlamasında referans alınır."
                ),
            }
        )

    events.sort(key=lambda item: item["date_iso"])
    return events


def _write_local_cache(events: list[dict[str, Any]], fetched_at: str) -> None:
    try:
        LOCAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_CACHE_PATH.write_text(
            json.dumps(
                {
                    "fetched_at": fetched_at,
                    "events": events,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _read_local_cache() -> tuple[list[dict[str, Any]], Optional[str]]:
    try:
        payload = json.loads(LOCAL_CACHE_PATH.read_text(encoding="utf-8"))
        events = payload.get("events")
        if isinstance(events, list):
            return events, payload.get("fetched_at")
    except Exception:
        pass
    return [], None


def _is_fresh_cache(fetched_at: Optional[str]) -> bool:
    if not fetched_at:
        return False
    try:
        parsed = parser.parse(fetched_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        return 0 <= age.total_seconds() < CACHE_TTL_SECONDS
    except Exception:
        return False


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_fmp_calendar_cached(
    api_key: str,
    from_date: str,
    to_date: str,
) -> tuple[list[dict[str, Any]], str]:
    response = requests.get(
        FMP_ECONOMIC_CALENDAR_URL,
        params={
            "from": from_date,
            "to": to_date,
            "apikey": api_key,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict):
        detail = (
            payload.get("Error Message")
            or payload.get("error")
            or payload.get("message")
            or str(payload)
        )
        raise RuntimeError(str(detail))
    if not isinstance(payload, list):
        raise RuntimeError("FMP ekonomik takvim yanıtı beklenen listede değil.")

    events = normalize_fmp_events(payload)
    fetched_at = datetime.now(timezone.utc).isoformat()
    _write_local_cache(events, fetched_at)
    return events, fetched_at


def load_economic_calendar(
    api_key: str,
    lookback_days: int = 1,
    lookahead_days: int = 14,
) -> dict[str, Any]:
    """Takvimi yükler; yalnız başarılı çağrılar bir saat önbelleğe alınır."""
    api_key = _clean_text(api_key)
    today_utc = datetime.now(timezone.utc).date()
    from_date = (today_utc - timedelta(days=max(0, lookback_days))).isoformat()
    to_date = (today_utc + timedelta(days=max(1, lookahead_days))).isoformat()

    cached_events, cached_at = _read_local_cache()

    # Uygulama yeniden başlasa bile aynı saat içinde ikinci FMP çağrısını önle.
    if cached_events and _is_fresh_cache(cached_at):
        return {
            "events": cached_events,
            "fetched_at": cached_at,
            "source": "cache",
            "error": "" if api_key else "FMP_API_KEY tanımlı değil.",
            "from_date": from_date,
            "to_date": to_date,
        }

    if not api_key:
        return {
            "events": cached_events,
            "fetched_at": cached_at,
            "source": "cache" if cached_events else "none",
            "error": "FMP_API_KEY tanımlı değil.",
            "from_date": from_date,
            "to_date": to_date,
        }

    try:
        events, fetched_at = _fetch_fmp_calendar_cached(
            api_key,
            from_date,
            to_date,
        )
        return {
            "events": events,
            "fetched_at": fetched_at,
            "source": "fmp",
            "error": "",
            "from_date": from_date,
            "to_date": to_date,
        }
    except Exception as exc:
        cached_events, cached_at = _read_local_cache()
        return {
            "events": cached_events,
            "fetched_at": cached_at,
            "source": "cache" if cached_events else "none",
            "error": str(exc),
            "from_date": from_date,
            "to_date": to_date,
        }


def filter_calendar_events(
    events: Iterable[dict[str, Any]],
    regions: Iterable[str],
    importance_levels: Iterable[str],
    period_label: str,
    only_upcoming: bool = False,
) -> list[dict[str, Any]]:
    selected_regions = set(regions)
    selected_importance = set(importance_levels)
    now = datetime.now(ISTANBUL_TZ)
    today = now.date()

    period_days = {
        "Bugün": 0,
        "Önümüzdeki 3 Gün": 3,
        "Önümüzdeki 7 Gün": 7,
        "Önümüzdeki 14 Gün": 14,
    }.get(period_label)

    filtered: list[dict[str, Any]] = []
    for event in events:
        if selected_regions and event.get("region") not in selected_regions:
            continue
        if selected_importance and event.get("importance") not in selected_importance:
            continue

        try:
            event_dt = parser.parse(str(event.get("date_iso")))
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=ISTANBUL_TZ)
            else:
                event_dt = event_dt.astimezone(ISTANBUL_TZ)
        except Exception:
            continue

        if period_days is not None:
            if event_dt.date() < today:
                continue
            if event_dt.date() > today + timedelta(days=period_days):
                continue

        if only_upcoming and event_dt < now:
            continue

        filtered.append(event)

    filtered.sort(key=lambda item: item.get("date_iso", ""))
    return filtered


def format_fetch_time(value: Optional[str]) -> str:
    if not value:
        return "Henüz başarılı veri alınmadı"
    try:
        parsed = parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ISTANBUL_TZ).strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(value)
