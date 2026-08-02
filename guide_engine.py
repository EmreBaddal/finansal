"""Aylooper Rehber ve Piyasa Dili.

Sözlük ayrı bir sayfada çalışır. Haber başlıklarında ve ekonomik takvim
çevresinde görülen kavramları yerel JSON içeriğiyle eşleştirir. Yapay zekâ
ve ücretli API kullanmaz.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Iterable

import streamlit as st

GUIDE_FILE = Path(__file__).with_name("guide_content.json")
GUIDE_PAGE_LABEL = "📘 Rehber & Piyasa Dili"

@st.cache_data(show_spinner=False)
def load_guide_content(path_text: str = str(GUIDE_FILE)) -> dict[str, Any]:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"terms": [], "error": f"Rehber içeriği bulunamadı: {path.name}"}
    except Exception as exc:
        return {"terms": [], "error": f"Rehber içeriği okunamadı: {exc}"}
    if not isinstance(payload.get("terms"), list):
        return {"terms": [], "error": "Rehber dosyasındaki terms alanı geçersiz."}
    return payload

def normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()

def _safe_call(obj: Any, method_name: str, default: Any) -> Any:
    method = getattr(obj, method_name, None)
    if not callable(method): return default
    try: return method()
    except Exception: return default

def terms_by_id() -> dict[str, dict[str, Any]]:
    return {str(x.get("id")):x for x in load_guide_content().get("terms",[]) if x.get("id")}

def _aliases(item: dict[str, Any]) -> list[str]:
    values = [item.get("term", "")] + list(item.get("aliases") or [])
    return sorted({normalize_text(x) for x in values if normalize_text(x)}, key=len, reverse=True)

def find_guide_terms(text: str, context: str | None = None, max_results: int = 5) -> list[dict[str, Any]]:
    """Metindeki sözlük kavramlarını uzun ve özgül ifadeleri önceleyerek bulur."""
    haystack = normalize_text(text)
    if not haystack: return []
    allowed_short = {"pmi","cpi","ppi","nfp","gdp","eps","etf","byf","roe","dxy","mom","yoy","qoq","ppk","fomc","ecb","viop"}
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in load_guide_content().get("terms", []):
        contexts = set(item.get("contexts") or [])
        best = 0
        for alias in _aliases(item):
            if len(alias) < 3 and alias not in allowed_short: continue
            pattern = rf"(?<![\w]){re.escape(alias)}(?![\w])"
            if re.search(pattern, haystack):
                score = len(alias) * 10
                if alias == normalize_text(item.get("term")): score += 25
                if context and context in contexts: score += 20
                if item.get("essential"): score += 3
                best = max(best, score)
        if best: matches.append((best,item))
    matches.sort(key=lambda x:(-x[0], str(x[1].get("term",""))))
    result=[]; seen=set()
    for _,item in matches:
        if item.get("id") in seen: continue
        result.append(item); seen.add(item.get("id"))
        if len(result)>=max_results: break
    return result

def search_guide(query: str, context: str | None = None, max_results: int = 8) -> list[dict[str, Any]]:
    needle = normalize_text(query)
    if not needle: return []
    scored=[]
    for item in load_guide_content().get("terms",[]):
        contexts=set(item.get("contexts") or [])
        aliases=_aliases(item)
        searchable=normalize_text(" ".join([str(item.get(k,"")) for k in ("term","short","seen_as","category")] + aliases))
        if len(needle) <= 4:
            if not any(re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", candidate) for candidate in aliases + [normalize_text(item.get("term", ""))]):
                continue
        elif needle not in searchable:
            continue
        score=0
        if any(needle==a for a in aliases): score+=100
        if normalize_text(item.get("term","" )).startswith(needle): score+=60
        if context and context in contexts: score+=20
        score += max(0,30-searchable.find(needle))
        scored.append((score,item))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("term",""))))
    return [x[1] for x in scored[:max_results]]

def _navigate_to_guide(term_id: str, return_context: str = "") -> None:
    st.session_state["guide_selected_term_id"] = term_id
    st.session_state["guide_return_context"] = return_context
    st.session_state["aylooper_app_section"] = GUIDE_PAGE_LABEL

def _render_term(item: dict[str, Any], compact: bool = False, key_prefix: str = "term") -> None:
    st.markdown(f"#### {item.get('term','Kavram')}")
    st.write(item.get("short", ""))
    seen = str(item.get("seen_as","")).strip()
    if seen: st.caption(f"Ekranda/haberde şöyle görünebilir: {seen}")
    if compact:
        with st.expander("Neden önemli ve sık yapılan hata", expanded=False):
            st.markdown("**Neden önemli?**")
            st.write(item.get("why", ""))
            st.markdown("**Basit örnek**")
            st.write(item.get("example", ""))
            st.warning(item.get("common_mistake", ""), icon="⚠️")
    else:
        st.markdown("**Neden önemli?**")
        st.write(item.get("why", ""))
        st.markdown("**Basit örnek**")
        st.write(item.get("example", ""))
        st.markdown("**Sık yapılan yanlış yorum**")
        st.warning(item.get("common_mistake", ""), icon="⚠️")
        st.markdown("**Aylooper'da nerede karşına çıkar?**")
        st.info(item.get("in_app", ""), icon="📍")
        url=str(item.get("source_url","")).strip()
        if url: st.link_button(f"Kaynak: {item.get('source_name','Kaynak')}",url)

def render_contextual_term_shortcuts(text: str, key_prefix: str, context: str = "news", max_terms: int = 3) -> None:
    matches=find_guide_terms(text,context=context,max_results=max_terms)
    if not matches: return
    digest=hashlib.sha1(f"{key_prefix}|{text}".encode("utf-8")).hexdigest()[:10]
    labels=", ".join(str(x.get("term")) for x in matches)
    popover_label = f"📘 {matches[0].get('term')}" if len(matches) == 1 else f"📘 {matches[0].get('term')} +{len(matches)-1}"
    with st.popover(popover_label):
        options={str(x.get("term")):str(x.get("id")) for x in matches}
        selected_label=st.radio("Açıklanacak kavram",list(options),horizontal=False,key=f"ctx_radio_{digest}",label_visibility="collapsed")
        item=terms_by_id().get(options[selected_label])
        if item:
            _render_term(item,compact=True,key_prefix=f"ctx_{digest}")
            st.button("Rehberde ayrıntılı aç",key=f"ctx_full_{digest}_{item['id']}",on_click=_navigate_to_guide,args=(item['id'],context))

def render_calendar_term_helper() -> None:
    """TradingView takviminin üstünde çalışan hızlı, mobil uyumlu sözlük."""
    ids=['aciklanan_deger','beklenti_takvim','onceki_deger','revizyon','mom','yoy','cpi','cekirdek_enflasyon','pmi','tarim_disi_istihdam','faiz_karari','baz_puan']
    mapping=terms_by_id()
    with st.expander("📘 Takvimdeki ifadeleri 30 saniyede açıkla",expanded=False):
        st.caption("Takvimde gördüğün ifadeyi seç veya yaz. Açıklama bu ekranda açılır; takvimden kopmazsın.")
        available=[mapping[x] for x in ids if x in mapping]
        labels=[x['term'] for x in available]
        selected=st.selectbox("Sık görülen ifade",["Seç"]+labels,key="calendar_quick_term")
        query=st.text_input("Başka bir ifade ara",placeholder="Örn: Core CPI, YoY, revizyon, FOMC",key="calendar_guide_search")
        item=None
        if selected!="Seç": item=next((x for x in available if x['term']==selected),None)
        if query.strip():
            found=search_guide(query,context="calendar",max_results=5)
            if found:
                choice=st.selectbox("Eşleşen kavram",[x['term'] for x in found],key="calendar_guide_match")
                item=next((x for x in found if x['term']==choice),item)
            else: st.info("Bu ifadeyle eşleşen kavram bulunamadı.")
        if item:
            with st.container(border=True):
                _render_term(item,compact=True,key_prefix="calendar")
                st.button("Rehberde ayrıntılı aç",key=f"calendar_full_{item['id']}",on_click=_navigate_to_guide,args=(item['id'],"calendar"))

def _portfolio_priorities(storage: Any, watch_list: Iterable[str]) -> list[tuple[str,str]]:
    out: "OrderedDict[str,str]"=OrderedDict()
    def add(i,r):
        if i not in out: out[i]=r
    for i,r in [
        ('hisse_senedi','Yatırım aracının neyi temsil ettiğini anlamak için.'),('maliyet','Portföy hesabının temelini anlamak için.'),
        ('gerceklesmemis_kar_zarar','Açık pozisyon sonucunu kesinleşmiş sonuçtan ayırmak için.'),('limit_emir','İşlem fiyatını kontrol etmek için.'),
        ('pozisyon_buyuklugu','Toplam riski yalnız fiyatın değil ayrılan tutarın da belirlediğini görmek için.'),('cesitlendirme','Şirket sayısıyla gerçek dağılımı ayırmak için.')]: add(i,r)
    tx=_safe_call(storage,'list_portfolio_transactions',[])
    if isinstance(tx,list) and tx:
        currencies={str(x.get('currency','TRY')).upper() for x in tx}
        types={str(x.get('transaction_type','buy')).lower() for x in tx}
        counts=Counter(str(x.get('symbol','')).upper() for x in tx if str(x.get('transaction_type','buy')).lower()=='buy')
        if any(v>1 for v in counts.values()): add('maliyet','Aynı varlıkta birden fazla alışın bulunduğu için.')
        if 'sell' in types: add('gerceklesmis_kar_zarar','Satış işlemin bulunduğu için.')
        if any(c!='TRY' for c in currencies): add('kur_riski','Yabancı para işlemin bulunduğu için.')
    plans=_safe_call(storage,'list_all_journal_entries',[])
    if isinstance(plans,list) and plans:
        add('giris_fiyati','Kayıtlı işlem planların olduğu için.'); add('risk_getiri','Hedef ve stop ilişkisini okumak için.')
    wl=[str(x).upper() for x in (watch_list or [])]
    if any(x.endswith('.IS') for x in wl): add('kap','BIST varlıklarını takip ettiğin için.')
    if any('-USD' in x for x in wl): add('volatilite','Kripto varlık takip ettiğin için.')
    return list(out.items())[:8]

def _show_term_cards(items: list[dict[str,Any]], max_items: int | None = None) -> None:
    if max_items: items=items[:max_items]
    for item in items:
        with st.expander(f"{item.get('term')} · {item.get('level')}",expanded=False):
            _render_term(item,compact=False,key_prefix=f"guide_{item.get('id')}")

def render_guide_page(storage: Any, watch_list: Iterable[str]) -> None:
    payload=load_guide_content(); terms=payload.get('terms',[]); mapping=terms_by_id()
    st.header("📘 Rehber & Piyasa Dili")
    st.caption("Kavramları kısa açıklamayla başlatır; ayrıntı yalnız açtığında görünür. Yatırım tavsiyesi üretmez.")
    if payload.get('error'): st.error(payload['error']); return

    selected_id=st.session_state.get('guide_selected_term_id')
    if selected_id and selected_id in mapping:
        with st.container(border=True):
            st.caption("Açtığın kavram")
            _render_term(mapping[selected_id],compact=False,key_prefix="focused")
        if st.button("← Rehber ana sayfasına dön",key="guide_home_back"):
            st.session_state.pop('guide_selected_term_id',None); st.rerun()
        st.markdown('---')

    section=st.selectbox("Rehber bölümü",["🚀 İlk 10 kavram","🎯 Sana göre önce öğren","💰 Yatırım araçlarını tanı","📅 Ekonomik takvimi oku","📰 Haber ve KAP dilini çöz","🔎 Tüm sözlükte ara"],key="guide_section")

    if section=="🚀 İlk 10 kavram":
        st.subheader("İlk 10 kavram")
        st.caption("Önce bunları öğren; ileri başlıklar daha sonra anlamlı hale gelir.")
        ids=['hisse_senedi','lot_adet','maliyet','guncel_deger','gerceklesmemis_kar_zarar','limit_emir','stop_seviyesi','pozisyon_buyuklugu','cesitlendirme','yatirim_fonu']
        _show_term_cards([mapping[x] for x in ids if x in mapping])
    elif section=="🎯 Sana göre önce öğren":
        st.subheader("Sana göre önce öğren")
        for term_id,reason in _portfolio_priorities(storage,watch_list):
            if term_id not in mapping: continue
            with st.container(border=True):
                st.markdown(f"**{mapping[term_id]['term']}**")
                st.write(mapping[term_id]['short']); st.caption(reason)
                st.button("Ayrıntıyı aç",key=f"prio_{term_id}",on_click=_navigate_to_guide,args=(term_id,'guide'))
    elif section=="💰 Yatırım araçlarını tanı":
        tool=st.selectbox("Araç grubu",["Fonlar ve ETF","VİOP ve Türevler"],key="guide_tool_group")
        if tool=="VİOP ve Türevler": st.warning("Bu bölüm kaldıraçlı ve türev ürünleri anlatır. İlk adımlar ve risk kavramlarını tamamladıktan sonra ilerlemek daha anlaşılır olur.")
        _show_term_cards([x for x in terms if x.get('category')==tool])
    elif section=="📅 Ekonomik takvimi oku":
        st.info("Takvimde önce Açıklanan–Beklenti–Önceki üçlüsünü; sonra MoM, YoY ve veri türünü birlikte oku.")
        _show_term_cards([x for x in terms if x.get('category') in {'Ekonomik Takvim Dili','Ekonomik Gelişmeler'}])
    elif section=="📰 Haber ve KAP dilini çöz":
        st.info("Bir ifadenin olumlu veya olumsuz anlamı bağlama göre değişebilir. Kartlarda sık yapılan yanlış yorum ayrıca gösterilir.")
        _show_term_cards([x for x in terms if x.get('category') in {'Haber ve KAP Dili','Şirket Gelişmeleri','Şirket Finansalları'}])
    else:
        q=st.text_input("Kavram veya haber ifadesi ara",placeholder="Örn: ETF, bedelli, hawkish, Core CPI, guidance",key="guide_all_search")
        categories=sorted({str(x.get('category')) for x in terms})
        c1,c2=st.columns(2)
        category=c1.selectbox("Kategori",["Tümü"]+categories,key="guide_all_category")
        level=c2.selectbox("Seviye",["Tümü","Başlangıç","Biraz Teknik","İleri"],key="guide_all_level")
        if q.strip(): filtered=search_guide(q,max_results=30)
        else: filtered=list(terms)
        if category!="Tümü": filtered=[x for x in filtered if x.get('category')==category]
        if level!="Tümü": filtered=[x for x in filtered if x.get('level')==level]
        st.caption(f"Gösterilen: {len(filtered)} · Toplam içerik: {len(terms)}")
        _show_term_cards(filtered,max_items=50)

    st.markdown('---')
    st.caption("Açıklamalar eğitim amaçlıdır. Tek bir kavram veya veri yatırımın uygunluğunu ya da gelecekteki performansını tek başına göstermez.")
