"""Fiyat alarmı kontrol motoru ve ntfy bildirimi."""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

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


def should_trigger(
    condition: str,
    previous_price: Optional[float],
    current_price: float,
    target_price: float,
) -> bool:
    """Alarmın yalnızca hedef seviyesi geçildiğinde tetiklenmesini sağlar."""
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
    """ntfy konu adresine ücretsiz push bildirimi yollar."""
    topic = (topic or "").strip()
    if not topic:
        return False, "NTFY_TOPIC tanımlı değil"

    url = f"{server.rstrip('/')}/{topic}"
    try:
        response = requests.post(
            url,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "chart_with_upwards_trend,warning",
                "Content-Type": "text/plain; charset=utf-8",
            },
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
) -> list[dict[str, Any]]:
    """Aktif alarmları kontrol eder, tetiklenenleri kaydeder ve bildirir."""
    if alerts is None:
        alerts = storage.list_alerts(active_only=True)

    topic = ntfy_topic if ntfy_topic is not None else os.getenv("NTFY_TOPIC", "")
    server = ntfy_server if ntfy_server is not None else os.getenv(
        "NTFY_SERVER", "https://ntfy.sh"
    )

    triggered_results: list[dict[str, Any]] = []
    price_cache: dict[str, Optional[float]] = {}

    for alert in alerts:
        if not alert.get("is_active", False):
            continue

        symbol = str(alert.get("symbol", "")).upper()
        target_price = normalize_float(alert.get("target_price"))
        if not symbol or target_price is None:
            continue

        if symbol not in price_cache:
            price_cache[symbol] = fetch_current_price(symbol)
        current_price = price_cache[symbol]
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
