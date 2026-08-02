"""Kalıcı veri katmanı: Supabase varsa onu, yoksa yerel JSON dosyalarını kullanır."""

from __future__ import annotations

import json
import os

# macOS'ta tarayıcının güvendiği sistem sertifikalarını Python/HTTPX'e açar.
# Özellikle kurumsal ağ, güvenlik yazılımı veya yerel sertifika otoritesi
# bulunan bilgisayarlardaki CERTIFICATE_VERIFY_FAILED hatasını çözer.
# SSL doğrulaması kapatılmaz.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    # Sistem trust store kullanılamazsa standart certifi paketine geri dön.
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

try:
    from supabase import Client, create_client
except Exception:  # pragma: no cover - paket kurulmadan yerel mod çalışabilsin
    Client = Any  # type: ignore
    create_client = None  # type: ignore


LOCAL_DATA_DIR = Path(os.getenv("AYLOOPER_DATA_DIR", ".aylooper_data"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class FinanceStorage:
    """Uygulamanın takip listesi, günlük ve alarm verilerini yönetir."""

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        local_data_dir: Path | str = LOCAL_DATA_DIR,
    ) -> None:
        self.client: Optional[Client] = None
        self.mode = "local"
        self.last_error = ""
        self.local_dir = Path(local_data_dir)

        if supabase_url and supabase_key and create_client is not None:
            try:
                self.client = create_client(supabase_url, supabase_key)
                # Secret ve tablo kurulumunu baştan doğrula.
                self.client.table("watchlist").select("symbol").limit(1).execute()
                self.mode = "supabase"
            except Exception as exc:
                self.last_error = str(exc)
                self.client = None
                self.mode = "local"

    @property
    def is_supabase(self) -> bool:
        return self.client is not None and self.mode == "supabase"

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------
    def _local_path(self, name: str) -> Path:
        return self.local_dir / name

    def _execute(self, query: Any) -> list[dict[str, Any]]:
        try:
            response = query.execute()
            self.last_error = ""
            return list(response.data or [])
        except Exception as exc:
            self.last_error = str(exc)
            raise

    # ------------------------------------------------------------------
    # Takip listesi
    # ------------------------------------------------------------------
    def get_watchlist(self, defaults: list[str]) -> list[str]:
        if self.is_supabase:
            try:
                rows = self._execute(
                    self.client.table("watchlist")
                    .select("symbol,sort_order,added_at")
                    .order("sort_order")
                    .order("added_at")
                )
                symbols = [str(row["symbol"]).upper() for row in rows if row.get("symbol")]
                if symbols:
                    return symbols
                for index, symbol in enumerate(defaults):
                    self.add_watchlist_symbol(symbol, sort_order=index)
                return list(defaults)
            except Exception:
                # Supabase tablo kurulumu tamamlanmadıysa uygulama açılmaya devam etsin.
                pass

        path = self._local_path("watchlist.json")
        values = _read_json(path, None)
        if not values:
            # Eski takip_listesi.json dosyasını otomatik devral.
            legacy = Path("takip_listesi.json")
            values = _read_json(legacy, defaults)
            _write_json(path, values)
        return [str(item).upper() for item in values]

    def add_watchlist_symbol(self, symbol: str, sort_order: Optional[int] = None) -> bool:
        symbol = symbol.strip().upper()
        if not symbol:
            return False

        if self.is_supabase:
            try:
                payload = {
                    "symbol": symbol,
                    "sort_order": sort_order if sort_order is not None else 9999,
                }
                self.client.table("watchlist").upsert(
                    payload,
                    on_conflict="symbol",
                ).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("watchlist.json")
        items = _read_json(path, [])
        if symbol not in items:
            items.append(symbol)
            _write_json(path, items)
        return True

    def remove_watchlist_symbol(self, symbol: str) -> bool:
        symbol = symbol.strip().upper()
        if self.is_supabase:
            try:
                self.client.table("watchlist").delete().eq("symbol", symbol).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("watchlist.json")
        items = [item for item in _read_json(path, []) if item != symbol]
        _write_json(path, items)
        return True

    # ------------------------------------------------------------------
    # Varlık günlüğü
    # ------------------------------------------------------------------
    def list_journal_entries(self, symbol: str) -> list[dict[str, Any]]:
        symbol = symbol.strip().upper()
        if self.is_supabase:
            try:
                return self._execute(
                    self.client.table("journal_entries")
                    .select("*")
                    .eq("symbol", symbol)
                    .order("created_at", desc=True)
                )
            except Exception:
                return []

        rows = _read_json(self._local_path("journal_entries.json"), [])
        return sorted(
            [row for row in rows if row.get("symbol") == symbol],
            key=lambda row: row.get("created_at", ""),
            reverse=True,
        )

    def list_all_journal_entries(self) -> list[dict[str, Any]]:
        """Bütün varlıklara ait günlük kayıtlarını en yeniden eskiye getirir."""
        if self.is_supabase:
            try:
                return self._execute(
                    self.client.table("journal_entries")
                    .select("*")
                    .order("created_at", desc=True)
                )
            except Exception:
                return []

        rows = _read_json(self._local_path("journal_entries.json"), [])
        return sorted(
            rows,
            key=lambda row: row.get("created_at", ""),
            reverse=True,
        )

    def create_journal_entry(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        now = utc_now_iso()
        row = {
            "id": str(uuid4()),
            "symbol": str(payload.get("symbol", "")).upper(),
            "title": str(payload.get("title", "")).strip(),
            "content": str(payload.get("content", "")).strip(),
            "entry_type": payload.get("entry_type", "Analiz"),
            "market_price_at_note": payload.get("market_price_at_note"),
            "price_at_entry": payload.get("price_at_entry"),
            "target_price": payload.get("target_price"),
            "stop_price": payload.get("stop_price"),
            "status": payload.get("status", "Açık"),
            "tags": payload.get("tags", []),
            "created_at": now,
            "updated_at": now,
        }

        if self.is_supabase:
            try:
                row.pop("id", None)
                data = self._execute(
                    self.client.table("journal_entries").insert(row).select("*")
                )
                return data[0] if data else None
            except Exception as exc:
                self.last_error = str(exc)
                return None

        path = self._local_path("journal_entries.json")
        rows = _read_json(path, [])
        rows.append(row)
        _write_json(path, rows)
        return row

    def update_journal_entry(
        self,
        entry_id: str,
        payload: dict[str, Any],
    ) -> bool:
        allowed = {
            "title",
            "content",
            "entry_type",
            "market_price_at_note",
            "price_at_entry",
            "target_price",
            "stop_price",
            "status",
            "tags",
        }
        update = {key: value for key, value in payload.items() if key in allowed}
        update["updated_at"] = utc_now_iso()

        if self.is_supabase:
            try:
                self.client.table("journal_entries").update(update).eq("id", entry_id).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("journal_entries.json")
        rows = _read_json(path, [])
        changed = False
        for row in rows:
            if row.get("id") == entry_id:
                row.update(update)
                changed = True
                break
        if changed:
            _write_json(path, rows)
        return changed

    def delete_journal_entry(self, entry_id: str) -> bool:
        if self.is_supabase:
            try:
                self.client.table("journal_entries").delete().eq("id", entry_id).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("journal_entries.json")
        rows = _read_json(path, [])
        new_rows = [row for row in rows if row.get("id") != entry_id]
        _write_json(path, new_rows)
        return len(new_rows) != len(rows)

    # ------------------------------------------------------------------
    # Portföy işlemleri
    # ------------------------------------------------------------------
    def portfolio_table_available(self) -> bool:
        """Supabase portföy tablosunun kurulmuş olup olmadığını doğrular."""
        if not self.is_supabase:
            return True
        try:
            self.client.table("portfolio_transactions").select("id").limit(1).execute()
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def list_portfolio_transactions(
        self,
        symbol: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Portföy alış/satış işlemlerini tarih sırasıyla getirir."""
        if self.is_supabase:
            try:
                query = self.client.table("portfolio_transactions").select("*")
                if symbol:
                    query = query.eq("symbol", symbol.strip().upper())
                return self._execute(
                    query.order("trade_date", desc=True).order("created_at", desc=True)
                )
            except Exception as exc:
                self.last_error = str(exc)
                return []

        rows = _read_json(self._local_path("portfolio_transactions.json"), [])
        if symbol:
            rows = [
                row for row in rows
                if str(row.get("symbol", "")).upper() == symbol.strip().upper()
            ]
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("trade_date", "")),
                str(row.get("created_at", "")),
            ),
            reverse=True,
        )

    def create_portfolio_transaction(
        self,
        payload: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        now = utc_now_iso()
        trade_date = payload.get("trade_date")
        if hasattr(trade_date, "isoformat"):
            trade_date = trade_date.isoformat()
        row = {
            "id": str(uuid4()),
            "symbol": str(payload.get("symbol", "")).strip().upper(),
            "transaction_type": str(payload.get("transaction_type", "buy")).lower(),
            "quantity": payload.get("quantity"),
            "unit_price": payload.get("unit_price"),
            "currency": str(payload.get("currency", "TRY")).upper(),
            "trade_date": str(trade_date or datetime.now().date().isoformat()),
            "commission": payload.get("commission", 0),
            "actual_try_amount": payload.get("actual_try_amount"),
            "fx_rate_to_try": payload.get("fx_rate_to_try"),
            "journal_entry_id": payload.get("journal_entry_id"),
            "note": str(payload.get("note", "")).strip() or None,
            "created_at": now,
            "updated_at": now,
        }

        if self.is_supabase:
            try:
                row.pop("id", None)
                data = self._execute(
                    self.client.table("portfolio_transactions").insert(row).select("*")
                )
                return data[0] if data else None
            except Exception as exc:
                self.last_error = str(exc)
                return None

        path = self._local_path("portfolio_transactions.json")
        rows = _read_json(path, [])
        rows.append(row)
        _write_json(path, rows)
        self.last_error = ""
        return row

    def update_portfolio_transaction(
        self,
        transaction_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Mevcut alış/satış kaydını güvenli biçimde günceller."""
        allowed = {
            "symbol",
            "transaction_type",
            "quantity",
            "unit_price",
            "currency",
            "trade_date",
            "commission",
            "actual_try_amount",
            "fx_rate_to_try",
            "journal_entry_id",
            "note",
        }
        update = {key: value for key, value in payload.items() if key in allowed}
        if "symbol" in update:
            update["symbol"] = str(update["symbol"]).strip().upper()
        if "transaction_type" in update:
            update["transaction_type"] = str(update["transaction_type"]).lower()
        if "currency" in update:
            update["currency"] = str(update["currency"]).upper()
        if "trade_date" in update and hasattr(update["trade_date"], "isoformat"):
            update["trade_date"] = update["trade_date"].isoformat()
        if "note" in update:
            update["note"] = str(update.get("note") or "").strip() or None
        update["updated_at"] = utc_now_iso()

        if self.is_supabase:
            try:
                self.client.table("portfolio_transactions").update(update).eq(
                    "id", transaction_id
                ).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("portfolio_transactions.json")
        rows = _read_json(path, [])
        changed = False
        for row in rows:
            if str(row.get("id")) == str(transaction_id):
                row.update(update)
                changed = True
                break
        if changed:
            _write_json(path, rows)
            self.last_error = ""
        return changed

    def delete_portfolio_transaction(self, transaction_id: str) -> bool:
        if self.is_supabase:
            try:
                self.client.table("portfolio_transactions").delete().eq(
                    "id", transaction_id
                ).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("portfolio_transactions.json")
        rows = _read_json(path, [])
        new_rows = [row for row in rows if str(row.get("id")) != str(transaction_id)]
        _write_json(path, new_rows)
        return len(new_rows) != len(rows)

    # ------------------------------------------------------------------
    # Alarmlar
    # ------------------------------------------------------------------
    def list_alerts(
        self,
        symbol: Optional[str] = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        if self.is_supabase:
            try:
                query = self.client.table("price_alerts").select("*")
                if symbol:
                    query = query.eq("symbol", symbol.strip().upper())
                if active_only:
                    query = query.eq("is_active", True)
                return self._execute(query.order("created_at", desc=True))
            except Exception:
                return []

        rows = _read_json(self._local_path("price_alerts.json"), [])
        if symbol:
            rows = [row for row in rows if row.get("symbol") == symbol.strip().upper()]
        if active_only:
            rows = [row for row in rows if bool(row.get("is_active", False))]
        return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)

    def create_alert(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        now = utc_now_iso()
        row = {
            "id": str(uuid4()),
            "symbol": str(payload.get("symbol", "")).upper(),
            "label": str(payload.get("label", "Fiyat alarmı")).strip(),
            "target_price": payload.get("target_price"),
            "condition": payload.get("condition", "above"),
            "is_active": bool(payload.get("is_active", True)),
            "repeat_mode": payload.get("repeat_mode", "once"),
            "last_checked_price": payload.get("last_checked_price"),
            "last_triggered_at": payload.get("last_triggered_at"),
            "journal_entry_id": payload.get("journal_entry_id"),
            "notify_ntfy": bool(payload.get("notify_ntfy", True)),
            "created_at": now,
            "updated_at": now,
        }

        if self.is_supabase:
            try:
                row.pop("id", None)
                data = self._execute(
                    self.client.table("price_alerts").insert(row).select("*")
                )
                return data[0] if data else None
            except Exception:
                return None

        path = self._local_path("price_alerts.json")
        rows = _read_json(path, [])
        rows.append(row)
        _write_json(path, rows)
        return row

    def update_alert(self, alert_id: str, payload: dict[str, Any]) -> bool:
        allowed = {
            "label",
            "target_price",
            "condition",
            "is_active",
            "repeat_mode",
            "last_checked_price",
            "last_triggered_at",
            "notify_ntfy",
        }
        update = {key: value for key, value in payload.items() if key in allowed}
        update["updated_at"] = utc_now_iso()

        if self.is_supabase:
            try:
                self.client.table("price_alerts").update(update).eq("id", alert_id).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("price_alerts.json")
        rows = _read_json(path, [])
        changed = False
        for row in rows:
            if row.get("id") == alert_id:
                row.update(update)
                changed = True
                break
        if changed:
            _write_json(path, rows)
        return changed

    def delete_alert(self, alert_id: str) -> bool:
        if self.is_supabase:
            try:
                self.client.table("price_alerts").delete().eq("id", alert_id).execute()
                self.last_error = ""
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        path = self._local_path("price_alerts.json")
        rows = _read_json(path, [])
        new_rows = [row for row in rows if row.get("id") != alert_id]
        _write_json(path, new_rows)
        return len(new_rows) != len(rows)

    # ------------------------------------------------------------------
    # Alarm geçmişi
    # ------------------------------------------------------------------
    def list_alert_history(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self.is_supabase:
            try:
                query = self.client.table("alert_history").select("*")
                if symbol:
                    query = query.eq("symbol", symbol.strip().upper())
                return self._execute(
                    query.order("triggered_at", desc=True).limit(max(1, limit))
                )
            except Exception:
                return []

        rows = _read_json(self._local_path("alert_history.json"), [])
        if symbol:
            rows = [row for row in rows if row.get("symbol") == symbol.strip().upper()]
        rows = sorted(rows, key=lambda row: row.get("triggered_at", ""), reverse=True)
        return rows[:limit]

    def create_alert_history(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        row = {
            "id": str(uuid4()),
            "alert_id": payload.get("alert_id"),
            "symbol": str(payload.get("symbol", "")).upper(),
            "label": payload.get("label", "Fiyat alarmı"),
            "target_price": payload.get("target_price"),
            "triggered_price": payload.get("triggered_price"),
            "condition": payload.get("condition"),
            "triggered_at": payload.get("triggered_at", utc_now_iso()),
            "notification_status": payload.get("notification_status", "not_sent"),
            "message": payload.get("message", ""),
        }

        if self.is_supabase:
            try:
                row.pop("id", None)
                data = self._execute(
                    self.client.table("alert_history").insert(row).select("*")
                )
                return data[0] if data else None
            except Exception:
                return None

        path = self._local_path("alert_history.json")
        rows = _read_json(path, [])
        rows.append(row)
        _write_json(path, rows)
        return row
