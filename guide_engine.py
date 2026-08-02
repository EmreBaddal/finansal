"""Aylooper Rehber Sözlük ekranı.

İçerik guide_content.json dosyasından okunur. Bu modül yatırım tavsiyesi
üretmez; yalnızca kavramları sade dille açıklar ve kullanıcının uygulamadaki
kayıtlarına göre hangi kavramları önce öğrenmesinin faydalı olacağını seçer.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Iterable

import streamlit as st


GUIDE_FILE = Path(__file__).with_name("guide_content.json")


@st.cache_data(show_spinner=False)
def load_guide_content(path_text: str = str(GUIDE_FILE)) -> dict[str, Any]:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"terms": [], "error": f"Rehber içeriği bulunamadı: {path.name}"}
    except Exception as exc:
        return {"terms": [], "error": f"Rehber içeriği okunamadı: {exc}"}

    terms = payload.get("terms")
    if not isinstance(terms, list):
        return {"terms": [], "error": "Rehber dosyasındaki terms alanı geçersiz."}
    return payload


def _search_text(value: Any) -> str:
    text = str(value or "").casefold()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _safe_call(obj: Any, method_name: str, default: Any) -> Any:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return default
    try:
        return method()
    except Exception:
        return default


def _portfolio_learning_priorities(storage: Any, watch_list: Iterable[str]) -> list[tuple[str, str]]:
    """Kullanıcının mevcut kayıtlarına göre öğrenme öncelikleri üretir.

    Burada yatırım profili veya uygunluk çıkarımı yapılmaz. Yalnızca uygulamada
    karşılaşılmış olabilecek kavramlar öne alınır.
    """
    priorities: "OrderedDict[str, str]" = OrderedDict()

    def add(term_id: str, reason: str) -> None:
        if term_id not in priorities:
            priorities[term_id] = reason

    # Her yeni yatırımcı için temel rota.
    add("hisse_senedi", "Uygulamadaki temel varlık türünü doğru anlamak için.")
    add("lot_adet", "İşlem miktarı ve toplam tutar hesabının başlangıcı olduğu için.")
    add("maliyet", "Alışların ortalama maliyete nasıl dönüştüğünü anlamak için.")
    add("gerceklesmemis_kar_zarar", "Açık pozisyon sonucunu kesinleşmiş sonuçtan ayırmak için.")
    add("limit_emir", "İşlem fiyatını kontrol eden temel emir türü olduğu için.")
    add("stop_emri", "Stop seviyesinin kesin gerçekleşme fiyatı olmadığını bilmek için.")
    add("pozisyon_buyuklugu", "Toplam sonucu yalnız hissenin değil ayrılan tutarın da belirlediğini görmek için.")
    add("cesitlendirme", "Farklı şirket sayısı ile gerçek çeşitlendirme arasındaki farkı anlamak için.")

    transactions = _safe_call(storage, "list_portfolio_transactions", [])
    if isinstance(transactions, list) and transactions:
        symbols = [str(row.get("symbol", "")).upper() for row in transactions if row.get("symbol")]
        currencies = {str(row.get("currency", "TRY")).upper() for row in transactions}
        transaction_types = {str(row.get("transaction_type", "buy")).lower() for row in transactions}
        buy_counts = Counter(
            str(row.get("symbol", "")).upper()
            for row in transactions
            if str(row.get("transaction_type", "buy")).lower() == "buy" and row.get("symbol")
        )

        if len(set(symbols)) >= 2:
            add("yogunlasma", "Birden fazla pozisyonun portföy ağırlıklarını doğru okumak için.")
        if any(count > 1 for count in buy_counts.values()):
            add("maliyet", "Aynı varlıkta birden fazla alış kaydı bulunduğu için.")
        if "sell" in transaction_types:
            add("gerceklesmis_kar_zarar", "Portföyde satış işlemi bulunduğu için.")
        if any(currency != "TRY" for currency in currencies):
            add("kur_riski", "Yabancı para cinsinden işlem bulunduğu için.")

    plans = _safe_call(storage, "list_all_journal_entries", [])
    if isinstance(plans, list) and plans:
        add("giris_fiyati", "Uygulamada kayıtlı analiz veya işlem planların bulunduğu için.")
        add("hedef_fiyat", "Planın başarı koşulunu ölçmek için.")
        add("stop_seviyesi", "Planın geçersiz sayılacağı noktayı önceden tanımlamak için.")
        add("risk_getiri", "Hedef ile stop arasındaki matematiksel ilişkiyi anlamak için.")

    normalized_watch = [str(symbol).upper() for symbol in watch_list or []]
    if any(symbol.endswith(".IS") for symbol in normalized_watch):
        add("kap", "Takip listende Borsa İstanbul varlıkları bulunduğu için.")
        add("bilanco_aciklamasi", "BIST şirketlerinde resmî finansal açıklamaları okumak için.")
        add("bedelli_sermaye", "BIST yatırımcılarının sık karşılaştığı sermaye işlemlerinden biri olduğu için.")
        add("bedelsiz_sermaye", "Pay sayısı artışı ile servet artışını birbirinden ayırmak için.")
    if any("-USD" in symbol for symbol in normalized_watch):
        add("volatilite", "Takip listende kripto varlık bulunduğu için fiyat hareketi kavramı önceliklidir.")
        add("likidite", "Hızlı hareket eden piyasalarda gerçekleşme koşullarını anlamak için.")
        add("piyasa_emri", "Hızlı piyasada görülen fiyat ile gerçekleşen fiyatın farklılaşabileceğini bilmek için.")

    return list(priorities.items())[:10]


def _render_learning_path() -> None:
    st.markdown("### 🗺️ Başlangıç öğrenme yolu")
    st.caption("Hepsini bir günde öğrenmek gerekmez. Bu sıra, kavramların birbirinin üzerine kurulmasını sağlar.")
    steps = [
        ("1", "İşlemi anla", "Hisse · lot · maliyet · güncel değer · kâr/zarar"),
        ("2", "Emri anla", "Piyasa emri · limit emir · stop emri · likidite"),
        ("3", "Planı anla", "Giriş · hedef · stop · pozisyon büyüklüğü · risk/getiri"),
        ("4", "Şirketi anla", "Ciro · kâr · nakit akışı · borç · değerleme"),
        ("5", "Gelişmeyi anla", "KAP · bilanço · sermaye işlemleri · faiz · enflasyon"),
    ]
    cols = st.columns(5)
    for col, (number, title, text) in zip(cols, steps):
        with col:
            with st.container(border=True):
                st.markdown(f"#### {number}. {title}")
                st.caption(text)


def _render_recommended_terms(
    terms_by_id: dict[str, dict[str, Any]],
    priorities: list[tuple[str, str]],
) -> None:
    valid = [(terms_by_id[term_id], reason) for term_id, reason in priorities if term_id in terms_by_id]
    if not valid:
        return

    st.markdown("### 🎯 Önce bunları öğren")
    st.caption(
        "Bu sıra bir yatırım önerisi değildir. Takip listen ve uygulamadaki kayıtların nedeniyle "
        "karşına çıkma ihtimali yüksek kavramları öne alır."
    )
    for item, reason in valid:
        with st.container(border=True):
            c1, c2 = st.columns([1, 4])
            with c1:
                st.markdown("**Öncelikli**")
                st.caption(item.get("category", ""))
            with c2:
                st.markdown(f"#### {item.get('term', 'Kavram')}")
                st.write(item.get("short", ""))
                st.caption(reason)


def render_guide_page(storage: Any, watch_list: Iterable[str]) -> None:
    payload = load_guide_content()
    terms = payload.get("terms", [])

    st.header("📘 Rehber Sözlük")
    st.caption(
        "Yatırıma yeni başlayanlar için kavramları sade dille açıklar. "
        "Bu bölüm al/sat kararı üretmez ve geleceğe ilişkin getiri tahmini yapmaz."
    )

    if payload.get("error"):
        st.error(payload["error"])
        return
    if not terms:
        st.warning("Rehber içeriği boş.")
        return

    categories = sorted({str(item.get("category", "Diğer")) for item in terms})
    essential_count = sum(bool(item.get("essential")) for item in terms)
    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Toplam kavram", len(terms))
    metric2.metric("Öncelikli kavram", essential_count)
    metric3.metric("Konu başlığı", len(categories))

    _render_learning_path()

    terms_by_id = {str(item.get("id")): item for item in terms}
    priorities = _portfolio_learning_priorities(storage, watch_list)
    _render_recommended_terms(terms_by_id, priorities)

    st.markdown("---")
    st.markdown("### 🔎 Rehberde ara")
    filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
    with filter_col1:
        search = st.text_input(
            "Kavram veya açıklama ara",
            placeholder="Örn: stop, bilanço, enflasyon, nakit akışı",
            key="guide_search",
        )
    with filter_col2:
        category = st.selectbox("Kategori", ["Tümü"] + categories, key="guide_category")
    with filter_col3:
        level = st.selectbox("Seviye", ["Tümü", "Başlangıç", "Biraz Teknik"], key="guide_level")

    essential_only = st.checkbox(
        "Yalnız bilinmesi öncelikli kavramları göster",
        value=False,
        key="guide_essential_only",
    )

    needle = _search_text(search)
    filtered: list[dict[str, Any]] = []
    for item in terms:
        if category != "Tümü" and item.get("category") != category:
            continue
        if level != "Tümü" and item.get("level") != level:
            continue
        if essential_only and not item.get("essential"):
            continue
        haystack = _search_text(
            " ".join(
                str(item.get(field, ""))
                for field in ("term", "category", "short", "why", "example", "common_mistake", "in_app")
            )
        )
        if needle and needle not in haystack:
            continue
        filtered.append(item)

    filtered.sort(key=lambda item: (not bool(item.get("essential")), str(item.get("term", ""))))
    st.caption(f"Gösterilen kavram: {len(filtered)} / {len(terms)}")

    if not filtered:
        st.info("Bu filtrelerle eşleşen kavram bulunamadı.")
        return

    for item in filtered:
        badge = "⭐ Öncelikli" if item.get("essential") else item.get("level", "")
        heading = f"{item.get('term', 'Kavram')} · {badge} · {item.get('category', '')}"
        with st.expander(heading, expanded=False):
            st.markdown("**Kısaca ne demek?**")
            st.write(item.get("short", ""))

            st.markdown("**Neden önemli?**")
            st.write(item.get("why", ""))

            st.markdown("**Basit örnek**")
            st.write(item.get("example", ""))

            st.markdown("**Sık yapılan hata**")
            st.warning(item.get("common_mistake", ""), icon="⚠️")

            st.markdown("**Aylooper'da nerede karşına çıkar?**")
            st.info(item.get("in_app", ""), icon="📍")

            source_url = str(item.get("source_url", "")).strip()
            source_name = str(item.get("source_name", "Resmî kaynak")).strip()
            if source_url:
                st.link_button(f"Kaynak: {source_name}", source_url)

    st.markdown("---")
    st.caption(
        "Rehber açıklamaları eğitim amaçlıdır. Bir kavramın tek başına olumlu veya olumsuz olması, "
        "bir yatırımın uygunluğunu ya da gelecekteki performansını göstermez."
    )
