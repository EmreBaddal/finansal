"""GitHub Actions tarafından çağrılan ücretsiz arka plan alarm kontrolü."""

from __future__ import annotations

import os
import sys

from alert_engine import process_alerts
from finance_storage import FinanceStorage


def main() -> int:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip()
    ntfy_server = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip()

    if not supabase_url or not supabase_key:
        print("SUPABASE_URL ve SUPABASE_SERVICE_ROLE_KEY zorunludur.")
        return 2

    storage = FinanceStorage(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )
    if not storage.is_supabase:
        print(f"Supabase bağlantısı kurulamadı: {storage.last_error}")
        return 3

    alerts = storage.list_alerts(active_only=True)
    print(f"Kontrol edilecek aktif alarm sayısı: {len(alerts)}")

    triggered = process_alerts(
        storage=storage,
        alerts=alerts,
        ntfy_topic=ntfy_topic,
        ntfy_server=ntfy_server,
    )

    for item in triggered:
        alert = item["alert"]
        print(
            f"TETİKLENDİ: {alert.get('symbol')} | "
            f"{alert.get('label')} | {item.get('current_price')}"
        )
    print(f"Tetiklenen alarm sayısı: {len(triggered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
