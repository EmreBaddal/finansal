"""Aylooper portföy hesaplama motoru.

İşlem kayıtlarından ağırlıklı ortalama maliyet, açık pozisyon, gerçekleşmiş ve
 gerçekleşmemiş kâr/zarar ile TL bazlı portföy toplamlarını üretir.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Iterable, Mapping, Optional

import pandas as pd
import yfinance as yf


def normalize_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def currency_for_symbol(symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    if symbol.endswith(".IS"):
        return "TRY"
    if symbol.endswith(".L"):
        return "GBP"
    if symbol.endswith((".DE", ".F", ".PA", ".AS", ".BR", ".MI")):
        return "EUR"
    return "USD"


def fx_ticker_for_currency(currency: str) -> Optional[str]:
    currency = str(currency or "TRY").strip().upper()
    if currency == "TRY":
        return None
    return {
        "USD": "USDTRY=X",
        "EUR": "EURTRY=X",
        "GBP": "GBPTRY=X",
        "CHF": "CHFTRY=X",
        "JPY": "JPYTRY=X",
    }.get(currency)


@lru_cache(maxsize=256)
def fetch_fx_rate_on_date(currency: str, date_text: str) -> Optional[float]:
    """İşlem tarihine yakın erişilebilir kapanış kurunu getirir."""
    currency = str(currency or "TRY").strip().upper()
    if currency == "TRY":
        return 1.0
    ticker = fx_ticker_for_currency(currency)
    if not ticker:
        return None
    try:
        trade_day = datetime.fromisoformat(str(date_text)).date()
    except Exception:
        try:
            trade_day = date.fromisoformat(str(date_text))
        except Exception:
            return None

    start = trade_day - timedelta(days=7)
    end = trade_day + timedelta(days=5)
    try:
        history = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
        )
        if history is None or history.empty:
            return None
        closes = history["Close"].dropna()
        if closes.empty:
            return None
        try:
            index_dates = pd.to_datetime(closes.index).date
            eligible = [i for i, item in enumerate(index_dates) if item <= trade_day]
            value = closes.iloc[eligible[-1]] if eligible else closes.iloc[0]
        except Exception:
            value = closes.iloc[-1]
        return normalize_float(value)
    except Exception:
        return None


def current_fx_rates(
    currencies: Iterable[str],
    fetched_prices: Optional[Mapping[str, Optional[float]]] = None,
) -> dict[str, Optional[float]]:
    """Para birimlerini TL'ye çeviren güncel kurları döndürür."""
    unique = list(dict.fromkeys(str(item or "TRY").upper() for item in currencies))
    result: dict[str, Optional[float]] = {"TRY": 1.0}
    price_map = dict(fetched_prices or {})
    for currency in unique:
        if currency == "TRY":
            result[currency] = 1.0
            continue
        ticker = fx_ticker_for_currency(currency)
        result[currency] = normalize_float(price_map.get(ticker)) if ticker else None
    return result


def transaction_native_amount(transaction: Mapping[str, Any]) -> Optional[float]:
    quantity = normalize_float(transaction.get("quantity"))
    unit_price = normalize_float(transaction.get("unit_price"))
    commission = normalize_float(transaction.get("commission")) or 0.0
    if quantity is None or unit_price is None or quantity <= 0 or unit_price <= 0:
        return None
    if str(transaction.get("transaction_type", "buy")).lower() == "sell":
        return max(0.0, quantity * unit_price - commission)
    return quantity * unit_price + commission


def _sort_key(transaction: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(transaction.get("trade_date") or ""),
        str(transaction.get("created_at") or ""),
        str(transaction.get("id") or ""),
    )


def validate_transaction_sequence(transactions: Iterable[Mapping[str, Any]]) -> tuple[bool, str]:
    """Tarih sırasına göre hiçbir pozisyonun eksi adede düşmediğini doğrular."""
    quantities: dict[str, float] = defaultdict(float)
    for transaction in sorted(list(transactions), key=_sort_key):
        symbol = str(transaction.get("symbol") or "").strip().upper()
        quantity = normalize_float(transaction.get("quantity"))
        tx_type = str(transaction.get("transaction_type") or "buy").lower()
        if not symbol or quantity is None or quantity <= 0:
            return False, "Sembol ve adet geçerli olmalıdır."
        if tx_type == "buy":
            quantities[symbol] += quantity
        elif tx_type == "sell":
            if quantity > quantities[symbol] + 1e-9:
                return (
                    False,
                    f"{symbol} için {transaction.get('trade_date')} tarihindeki satış, "
                    "o tarihe kadar alınmış adedi aşıyor.",
                )
            quantities[symbol] -= quantity
        else:
            return False, "İşlem türü yalnızca alış veya satış olabilir."
    return True, "ok"


def build_portfolio_snapshot(
    transactions: Iterable[Mapping[str, Any]],
    current_prices: Mapping[str, Optional[float]],
    fx_rates: Mapping[str, Optional[float]],
) -> dict[str, Any]:
    """İşlemleri ağırlıklı ortalama maliyet yöntemiyle açık pozisyonlara dönüştürür."""
    states: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for transaction in sorted(list(transactions), key=_sort_key):
        symbol = str(transaction.get("symbol") or "").strip().upper()
        tx_type = str(transaction.get("transaction_type") or "buy").strip().lower()
        quantity = normalize_float(transaction.get("quantity"))
        unit_price = normalize_float(transaction.get("unit_price"))
        commission = normalize_float(transaction.get("commission")) or 0.0
        currency = str(transaction.get("currency") or currency_for_symbol(symbol)).upper()
        actual_try_amount = normalize_float(transaction.get("actual_try_amount"))
        fx_rate = normalize_float(transaction.get("fx_rate_to_try"))
        if fx_rate is None:
            fx_rate = 1.0 if currency == "TRY" else normalize_float(fx_rates.get(currency))

        if not symbol or quantity is None or unit_price is None or quantity <= 0 or unit_price <= 0:
            warnings.append(f"Geçersiz işlem atlandı: {symbol or 'sembol yok'}")
            continue

        state = states.setdefault(
            symbol,
            {
                "symbol": symbol,
                "currency": currency,
                "quantity": 0.0,
                "cost_basis_native": 0.0,
                "cost_basis_try": 0.0,
                "realized_pnl_native": 0.0,
                "realized_pnl_try": 0.0,
                "buy_count": 0,
                "sell_count": 0,
                "first_trade_date": transaction.get("trade_date"),
                "last_trade_date": transaction.get("trade_date"),
                "journal_entry_ids": set(),
            },
        )
        state["currency"] = currency
        state["last_trade_date"] = transaction.get("trade_date")
        journal_id = transaction.get("journal_entry_id")
        if journal_id:
            state["journal_entry_ids"].add(str(journal_id))

        if tx_type == "buy":
            native_cost = quantity * unit_price + commission
            # TRY işlemlerinde maliyet doğrudan adet × fiyat + komisyondur.
            # "Gerçek TL" alanı yalnız yabancı para işlemlerinde kur dönüşümü içindir.
            try_cost = native_cost if currency == "TRY" else actual_try_amount
            if try_cost is None and fx_rate is not None:
                try_cost = native_cost * fx_rate
            if try_cost is None:
                try_cost = 0.0
                warnings.append(f"{symbol} alış işlemi için TL maliyet hesaplanamadı.")

            state["quantity"] += quantity
            state["cost_basis_native"] += native_cost
            state["cost_basis_try"] += try_cost
            state["buy_count"] += 1
            continue

        if tx_type != "sell":
            warnings.append(f"{symbol} için bilinmeyen işlem türü atlandı: {tx_type}")
            continue

        if quantity > state["quantity"] + 1e-9:
            warnings.append(f"{symbol} satış adedi mevcut adedi aştığı için atlandı.")
            continue

        avg_native = (
            state["cost_basis_native"] / state["quantity"]
            if state["quantity"] > 0
            else 0.0
        )
        avg_try = (
            state["cost_basis_try"] / state["quantity"]
            if state["quantity"] > 0
            else 0.0
        )
        removed_native = avg_native * quantity
        removed_try = avg_try * quantity
        proceeds_native = max(0.0, quantity * unit_price - commission)
        # TRY satışlarında alınan tutar doğrudan işlem hesabından gelir.
        proceeds_try = proceeds_native if currency == "TRY" else actual_try_amount
        if proceeds_try is None and fx_rate is not None:
            proceeds_try = proceeds_native * fx_rate
        if proceeds_try is None:
            proceeds_try = 0.0
            warnings.append(f"{symbol} satış işlemi için TL tutar hesaplanamadı.")

        state["realized_pnl_native"] += proceeds_native - removed_native
        state["realized_pnl_try"] += proceeds_try - removed_try
        state["cost_basis_native"] -= removed_native
        state["cost_basis_try"] -= removed_try
        state["quantity"] -= quantity
        state["sell_count"] += 1

        if state["quantity"] <= 1e-9:
            state["quantity"] = 0.0
            state["cost_basis_native"] = 0.0
            state["cost_basis_try"] = 0.0

    positions: list[dict[str, Any]] = []
    total_cost_try = 0.0
    total_value_try = 0.0
    total_unrealized_try = 0.0
    total_realized_try = 0.0

    for symbol, state in states.items():
        total_realized_try += float(state["realized_pnl_try"])
        quantity = float(state["quantity"])
        if quantity <= 0:
            continue

        current_price = normalize_float(current_prices.get(symbol))
        currency = str(state["currency"]).upper()
        current_fx = 1.0 if currency == "TRY" else normalize_float(fx_rates.get(currency))
        avg_cost_native = state["cost_basis_native"] / quantity if quantity else None
        avg_cost_try = state["cost_basis_try"] / quantity if quantity else None
        current_value_native = current_price * quantity if current_price is not None else None
        current_value_try = (
            current_value_native * current_fx
            if current_value_native is not None and current_fx is not None
            else None
        )
        unrealized_native = (
            current_value_native - state["cost_basis_native"]
            if current_value_native is not None
            else None
        )
        unrealized_try = (
            current_value_try - state["cost_basis_try"]
            if current_value_try is not None
            else None
        )
        return_native_pct = (
            unrealized_native / state["cost_basis_native"] * 100
            if unrealized_native is not None and state["cost_basis_native"] > 0
            else None
        )
        return_try_pct = (
            unrealized_try / state["cost_basis_try"] * 100
            if unrealized_try is not None and state["cost_basis_try"] > 0
            else None
        )

        total_cost_try += float(state["cost_basis_try"])
        if current_value_try is not None:
            total_value_try += current_value_try
        if unrealized_try is not None:
            total_unrealized_try += unrealized_try

        positions.append(
            {
                **state,
                "journal_entry_ids": sorted(state["journal_entry_ids"]),
                "average_cost_native": avg_cost_native,
                "average_cost_try": avg_cost_try,
                "current_price": current_price,
                "current_fx_rate": current_fx,
                "current_value_native": current_value_native,
                "current_value_try": current_value_try,
                "unrealized_pnl_native": unrealized_native,
                "unrealized_pnl_try": unrealized_try,
                "return_native_pct": return_native_pct,
                "return_try_pct": return_try_pct,
            }
        )

    positions.sort(key=lambda item: item.get("current_value_try") or 0.0, reverse=True)
    for position in positions:
        position["portfolio_weight_pct"] = (
            (position.get("current_value_try") or 0.0) / total_value_try * 100
            if total_value_try > 0
            else 0.0
        )

    return {
        "positions": positions,
        "totals": {
            "open_cost_try": total_cost_try,
            "current_value_try": total_value_try,
            "unrealized_pnl_try": total_unrealized_try,
            "unrealized_return_pct": (
                total_unrealized_try / total_cost_try * 100 if total_cost_try > 0 else None
            ),
            "realized_pnl_try": total_realized_try,
            "total_pnl_try": total_unrealized_try + total_realized_try,
        },
        "warnings": warnings,
    }
