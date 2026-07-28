"""Fiyat alarmı kontrol motoru ve ntfy bildirimi."""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

import pandas as pd
import requests
import yfinance as yf

from finance_storage import FinanceStorage


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def fetch_current_price(symbol: str) -> Optional[float]:
    """Yahoo Finance üzerinden son erişilebilir fiyatı getirir."""
    symbol = symbol.strip().upper()
    try:
        fast_info = yf.Ticker(symbol).fast_info
        for key in ("lastPrice", "regularMarketPrice"):
            try:
                value = fast_info[key]
            except Exception:
                value = getattr(fast_info, key, None)
            value = normalize_float(value)
            if value and value > 0:
                return value
    except Exception:
        pass

    # fast_info başarısızsa son mum kapanışını kullan.
    for period, interval in (("1d", "1m"), ("5d", "15m"), ("5d", "1d")):
        try:
            history = yf.Ticker(symbol).history(
                period=period,
                interval=interval,
                auto_adjust=False,
            )
            if history is not None and not history.empty:
                value = normalize_float(history["Close"].dropna().iloc[-1])
                if value and value > 0:
                    return value
        except Exception:
            continue
    return None


def _extract_last_close_from_download(
    frame: pd.DataFrame,
    symbol: str,
    multi_symbol: bool,
) -> Optional[float]:
    """yf.download çıktısından son geçerli kapanışı güvenli biçimde çıkarır."""
    try:
        if multi_symbol:
            # yfinance sürümüne göre ilk seviye sembol veya fiyat alanı olabilir.
            if isinstance(frame.columns, pd.MultiIndex):
                level0 = set(map(str, frame.columns.get_level_values(0)))
                level1 = set(map(str, frame.columns.get_level_values(1)))
                if symbol in level0:
                    series = frame[symbol]["Close"]
                elif symbol in level1:
                    series = frame["Close"][symbol]
                else:
                    return None
            else:
                return None
        else:
            if isinstance(frame.columns, pd.MultiIndex):
                if "Close" in frame.columns.get_level_values(0):
                    close_block = frame["Close"]
                    series = (
                        close_block[symbol]
                        if symbol in close_block.columns
                        else close_block.iloc[:, 0]
                    )
                else:
                    series = frame[symbol]["Close"]
            else:
                series = frame["Close"]

        series = series.dropna()
        if series.empty:
            return None
        value = normalize_float(series.iloc[-1])
        return value if value and value > 0 else None
    except Exception:
        return None


def fetch_current_prices(symbols: Iterable[str]) -> dict[str, Optional[float]]:
    """Birden fazla sembolün fiyatını mümkün olduğunca tek Yahoo isteğiyle getirir.

    Toplu istek başarısız olan semboller için tekil güvenli yedek yöntem kullanılır.
    Bu yaklaşım, uygulama açıkken bütün aktif alarmları kontrol ederken Yahoo'ya
    gereksiz sayıda istek gönderilmesini azaltır.
    """
    unique_symbols = list(
        dict.fromkeys(
            str(symbol).strip().upper()
            for symbol in symbols
            if str(symbol).strip()
        )
    )
    result: dict[str, Optional[float]] = {symbol: None for symbol in unique_symbols}
    if not unique_symbols:
        return result

    # Dakikalık veri oran sınırına takılırsa 5 dakikalık veri ve sonra günlük veri denenir.
    for period, interval in (("1d", "5m"), ("5d", "15m"), ("5d", "1d")):
        missing = [symbol for symbol, price in result.items() if price is None]
        if not missing:
            break
        try:
            downloaded = yf.download(
                tickers=" ".join(missing),
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=False,
            )
            if downloaded is None or downloaded.empty:
                continue
            multi_symbol = len(missing) > 1
            for symbol in missing:
                value = _extract_last_close_from_download(
                    downloaded,
                    symbol,
                    multi_symbol=multi_symbol,
                )
                if value is not None:
                    result[symbol] = value
        except Exception:
            continue

    # Hâlâ eksik kalanları tek tek dene.
    for symbol, value in list(result.items()):
        if value is None:
            result[symbol] = fetch_current_price(symbol)

    return result


def should_trigger(
    condition: str,
    previous_price: Optional[float],
    current_price: float,
    target_price: float,
) -> bool:
    """Alarmın hedef seviyesi ilk kez sağlandığında/geçildiğinde tetiklenmesini sağlar."""
    if condition == "below":
        if previous_price is None:
            return current_price <= target_price
        return previous_price > target_price >= current_price

    if previous_price is None:
        return current_price >= target_price
    return previous_price < target_price <= current_price


def build_alert_message(alert: dict[str, Any], current_price: float) -> str:
    symbol = alert.get("symbol", "")
    target = normalize_float(alert.get("target_price")) or 0.0
    label = alert.get("label") or "Fiyat alarmı"
    condition_text = (
        "altına düştü"
        if alert.get("condition") == "below"
        else "üzerine çıktı"
    )
    return (
        f"{symbol} belirlenen seviyenin {condition_text}.\n"
        f"Alarm: {label}\n"
        f"Hedef: {target:,.4f}\n"
        f"Güncel: {current_price:,.4f}"
    )


def send_ntfy_notification(
    topic: str,
    title: str,
    message: str,
    server: str = "https://ntfy.sh",
    priority: str = "high",
) -> tuple[bool, str]:
    """ntfy konu adresine UTF-8 uyumlu JSON gövdesiyle bildirim yollar.

    Emoji ve Türkçe karakterleri HTTP başlıklarına yazmak bazı Python/requests
    sürümlerinde latin-1 kodlama hatasına yol açar. ntfy'nin JSON yayınlama
    biçimi kullanılarak başlık ve mesaj güvenli biçimde UTF-8 gönderilir.
    """
    topic = (topic or "").strip()
    if not topic:
        return False, "NTFY_TOPIC tanımlı değil"

    priority_map = {
        "min": 1,
        "low": 2,
        "default": 3,
        "high": 4,
        "max": 5,
        "urgent": 5,
    }
    priority_value = priority_map.get(str(priority).strip().lower(), 4)

    payload = {
        "topic": topic,
        "title": title,
        "message": message,
        "priority": priority_value,
        "tags": ["chart_with_upwards_trend", "warning"],
    }

    try:
        response = requests.post(
            f"{server.rstrip('/')}/",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return True, "sent"
    except Exception as exc:
        return False, str(exc)


def process_alerts(
    storage: FinanceStorage,
    alerts: Optional[Iterable[dict[str, Any]]] = None,
    ntfy_topic: Optional[str] = None,
    ntfy_server: Optional[str] = None,
    price_overrides: Optional[Mapping[str, Optional[float]]] = None,
) -> list[dict[str, Any]]:
    """Aktif alarmları kontrol eder, tetiklenenleri kaydeder ve bildirir.

    Aynı sembole ait birden fazla alarm için fiyat yalnızca bir kez alınır. Uygulama
    seçili varlığın fiyatını zaten çekmişse ``price_overrides`` ile tekrar kullanabilir.
    """
    if alerts is None:
        alerts = storage.list_alerts(active_only=True)
    alert_list = list(alerts)

    topic = ntfy_topic if ntfy_topic is not None else os.getenv("NTFY_TOPIC", "")
    server = ntfy_server if ntfy_server is not None else os.getenv(
        "NTFY_SERVER", "https://ntfy.sh"
    )

    triggered_results: list[dict[str, Any]] = []
    price_cache: dict[str, Optional[float]] = {
        str(symbol).strip().upper(): normalize_float(value)
        for symbol, value in (price_overrides or {}).items()
        if str(symbol).strip()
    }

    symbols_needed = {
        str(alert.get("symbol", "")).strip().upper()
        for alert in alert_list
        if alert.get("is_active", False) and str(alert.get("symbol", "")).strip()
    }
    missing_symbols = [
        symbol
        for symbol in symbols_needed
        if symbol not in price_cache or price_cache[symbol] is None
    ]
    if missing_symbols:
        price_cache.update(fetch_current_prices(missing_symbols))

    for alert in alert_list:
        if not alert.get("is_active", False):
            continue

        symbol = str(alert.get("symbol", "")).upper()
        target_price = normalize_float(alert.get("target_price"))
        if not symbol or target_price is None:
            continue

        current_price = normalize_float(price_cache.get(symbol))
        if current_price is None:
            continue

        previous_price = normalize_float(alert.get("last_checked_price"))
        condition = alert.get("condition", "above")
        triggered = should_trigger(
            condition=condition,
            previous_price=previous_price,
            current_price=current_price,
            target_price=target_price,
        )

        update_payload: dict[str, Any] = {
            "last_checked_price": current_price,
        }

        if not triggered:
            storage.update_alert(str(alert["id"]), update_payload)
            continue

        triggered_at = utc_now_iso()
        message = build_alert_message(alert, current_price)
        notification_status = "disabled"

        if alert.get("notify_ntfy", True):
            sent, detail = send_ntfy_notification(
                topic=topic or "",
                server=server or "https://ntfy.sh",
                title=f"🚨 {symbol} fiyat alarmı",
                message=message,
            )
            notification_status = "sent" if sent else f"failed: {detail}"

        repeat_mode = alert.get("repeat_mode", "once")
        update_payload["last_triggered_at"] = triggered_at
        if repeat_mode == "once":
            update_payload["is_active"] = False

        storage.update_alert(str(alert["id"]), update_payload)
        history = storage.create_alert_history(
            {
                "alert_id": alert.get("id"),
                "symbol": symbol,
                "label": alert.get("label", "Fiyat alarmı"),
                "target_price": target_price,
                "triggered_price": current_price,
                "condition": condition,
                "triggered_at": triggered_at,
                "notification_status": notification_status,
                "message": message,
            }
        )

        triggered_results.append(
            {
                "alert": alert,
                "current_price": current_price,
                "message": message,
                "notification_status": notification_status,
                "history": history,
            }
        )

    return triggered_results
