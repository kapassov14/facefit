from __future__ import annotations

import json
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.serializers import report_public_dict
from app.core.config import after_photo_feature_enabled, settings as env_settings
from app.core.exceptions import not_found
from app.db.crm import add_lead_event
from app.db.models import ClientStatus, CtaClickEvent, GeneratedReport, ReportViewEvent
from app.db.repositories import get_bot_settings
from app.db.session import get_db
from app.reports.bella_web_report import render_bella_web_report_html
from app.storage.local import local_storage

router = APIRouter(tags=["public"])


def _url(path: str | None) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return local_storage.public_url(path)


def _e(value: Any) -> str:
    return escape(str(value or ""))


def _clean_public(value: Any) -> str:
    text = str(value or "")
    text = text.replace("Нормальная кожа", "Кожа с ровной плотной базой")
    text = text.replace("нормальная кожа", "кожа с ровной плотной базой")
    text = text.replace("Нормальная", "Комбинированная с ровной плотной базой")
    text = text.replace("нормальная", "комбинированная с ровной плотной базой")
    text = text.replace("normal", "комбинированная с ровной плотной базой")
    return " ".join(text.split())


def _skin_type_public_title(value: Any) -> str:
    text = _clean_public(value)
    lowered = text.lower()
    if not lowered or lowered in {"unknown", "none", "не определено"}:
        return "Комбинированная, с ровной плотной базой"
    if "комбинированная с ровной плотной базой" in lowered or "смешан" in lowered:
        return "Комбинированная, с ровной плотной базой"
    return text


def _items_html(items: list[str] | None, fallback: str) -> str:
    values = items or [fallback]
    return "".join(f"<li>{_e(_clean_public(item))}</li>" for item in values)


def _zone_label(zone: dict[str, Any]) -> str:
    if zone.get("status") == "good" or zone.get("color") == "green":
        return "Все хорошо"
    if zone.get("status") == "priority" or zone.get("color") == "red":
        return "Приоритет"
    return "Зона внимания"


def _image(src: str, alt: str, class_name: str = "") -> str:
    if not src:
        return "<div class='image-placeholder'>Изображение формируется</div>"
    return f"<img class='{class_name}' src='{_e(src)}' alt='{_e(alt)}'>"


PUBLIC_REPORT_SHELL = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bella Vladi · Персональный отчет лица</title>
  <style>
    :root{--bg:#ece4d7;--sheet:#faf5ec;--sheet-2:#fffaf1;--card:#fdfbf5;--card-2:#f7f0e3;--line:#e5d8c2;--line-soft:#efe6d3;--ink:#3a2a1e;--ink-2:#5a4636;--muted:#8c7868;--accent:#a8755a;--accent-2:#c89a7a;--good:#8aa183;--good-soft:rgba(138,161,131,.18);--attention:#c9a96a;--attention-soft:rgba(201,169,106,.20);--priority:#c08474;--priority-soft:rgba(192,132,116,.20);--serif:"Cormorant Garamond","Playfair Display",Georgia,"Times New Roman",serif;--sans:"Inter","Helvetica Neue",Arial,sans-serif;--r:20px;--r-sm:12px;--shadow:0 1px 0 rgba(58,42,30,.04),0 10px 30px rgba(58,42,30,.06)}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:var(--sans);color:var(--ink);font-size:17px;line-height:1.6;padding:32px 16px 92px;-webkit-font-smoothing:antialiased}img{display:block;width:100%;height:100%;object-fit:cover}.sheet{max-width:1140px;margin:0 auto;background:radial-gradient(1200px 600px at 50% -10%,#fff8ea 0%,transparent 60%),linear-gradient(180deg,var(--sheet-2) 0%,var(--sheet) 100%);border:1px solid var(--line);border-radius:28px;box-shadow:0 1px 0 rgba(255,255,255,.6) inset,0 30px 80px -30px rgba(58,42,30,.25),0 8px 24px rgba(58,42,30,.08);padding:56px 56px 48px;overflow:hidden}.mono{width:58px;height:58px;border-radius:50%;border:1px solid var(--accent);color:var(--accent);font-family:var(--serif);font-style:italic;font-size:28px;display:flex;align-items:center;justify-content:center;background:var(--sheet-2);margin-bottom:24px}.eyebrow,.label{font-size:12px;letter-spacing:.42em;text-transform:uppercase;color:var(--muted);font-weight:500}.display{font-family:var(--serif);font-weight:500;font-size:64px;line-height:1.04;letter-spacing:.5px;margin:14px 0 18px}.display em{font-style:italic;color:var(--accent);font-weight:400}.hero{display:grid;grid-template-columns:1.2fr .9fr;gap:40px;align-items:center;padding-bottom:48px;border-bottom:1px solid var(--line-soft)}.hero-sub{font-size:18px;line-height:1.55;color:var(--ink-2);max-width:620px}.hero-meta{display:flex;gap:28px;margin-top:28px;flex-wrap:wrap;padding:18px 0;border-top:1px solid var(--line-soft);border-bottom:1px solid var(--line-soft)}.hero-meta div{display:flex;flex-direction:column;gap:4px}.val{font-family:var(--serif);font-size:22px}.photo-card,.card,.mini,.after-card,.summary-lead,.map-panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow)}.photo-card{background:var(--card-2);padding:14px}.photo-frame{aspect-ratio:4/5;border-radius:18px;overflow:hidden;background:radial-gradient(120% 80% at 50% 30%,#f1e3cb 0%,#e0cdaf 60%,#c9b18c 100%)}.photo-frame .image-placeholder{height:100%;min-height:100%}.image-placeholder{min-height:360px;display:grid;place-items:center;padding:28px;color:var(--muted);text-align:center;background:var(--card-2)}.photo-caption{text-align:center;padding:12px 4px 4px;font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--muted)}.section{padding:56px 0;border-top:1px solid var(--line-soft)}.section:first-of-type{border-top:none}.section-head{display:flex;align-items:baseline;gap:18px;margin-bottom:22px}.num{font-family:var(--serif);font-style:italic;color:var(--accent);font-size:20px}.section-title{font-family:var(--serif);font-weight:500;font-size:38px;line-height:1.1;margin:0}.summary-lead{padding:36px 40px;margin-bottom:24px}.summary-lead .lead{font-family:var(--serif);font-size:30px;line-height:1.25;margin:10px 0 0}.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:22px}.mini{border-radius:var(--r-sm);padding:20px}.mini .t,.card-title{font-family:var(--serif);font-size:22px;line-height:1.2;margin:0 0 8px;font-weight:500}.mini .d,.card p,.card li{color:var(--ink-2)}.card{padding:26px}.card.tinted{background:var(--card-2)}.age-grid{display:grid;grid-template-columns:.85fr 1.15fr;gap:32px}.age-big{background:linear-gradient(180deg,#fffaf1 0%,#f5ead5 100%);border:1px solid var(--line);border-radius:var(--r);padding:36px;box-shadow:var(--shadow)}.range{font-family:var(--serif);font-size:88px;line-height:1;margin:18px 0 6px}.range small{font-size:34px;color:var(--accent);font-style:italic;margin-left:6px}.scale{margin-top:24px;height:8px;border-radius:99px;background:rgba(168,117,90,.15);position:relative;overflow:hidden}.fill{position:absolute;inset:0 auto 0 0;background:linear-gradient(90deg,var(--accent-2),var(--accent));border-radius:99px}.tag,.status{display:inline-flex;align-items:center;padding:6px 12px;border-radius:99px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:600}.tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.tag{background:var(--card-2);border:1px solid var(--line);color:var(--ink-2)}.good{background:var(--good-soft);color:#4d6147}.attention{background:var(--attention-soft);color:#7d6324}.priority{background:var(--priority-soft);color:#7a3f31}.bullet{margin:8px 0 0;padding:0;list-style:none}.bullet li{position:relative;padding:8px 0 8px 22px;border-bottom:1px solid var(--line-soft)}.bullet li:last-child{border-bottom:none}.bullet li:before{content:"";position:absolute;left:0;top:18px;width:7px;height:7px;border-radius:50%;background:var(--accent-2)}.map-wrap{display:grid;grid-template-columns:360px 1fr;gap:22px;align-items:start}.map-panel{background:var(--card-2);padding:14px;align-self:start}.face-map{position:relative;aspect-ratio:4/5;border-radius:16px;overflow:hidden;background:var(--card-2)}.face-map img,.face-map .image-placeholder{border-radius:16px;min-height:100%;height:100%}.map-pin{position:absolute;transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;display:grid;place-items:center;border:1px solid rgba(255,255,255,.72);box-shadow:0 6px 18px rgba(58,42,30,.22);font-size:13px;font-weight:700}.legend{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-2)}.legend.compact{justify-content:center;margin:14px 0 0}.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:8px}.dot.good{background:var(--good)}.dot.attention{background:var(--attention)}.dot.priority{background:var(--priority)}.zone-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.zone{display:grid;grid-template-columns:30px 1fr;gap:10px;align-items:start;padding:14px;background:var(--card);border:1px solid var(--line);border-radius:var(--r-sm)}.zn{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:14px;background:var(--card-2);border:1px solid var(--line)}.zone b{font-family:var(--serif);font-size:17px;line-height:1.15;font-weight:500;display:block;margin-bottom:4px}.zone .body{font-size:13px;color:var(--ink-2);line-height:1.42}.zone .extra{margin-top:7px;font-size:12px;color:var(--muted)}.zone .status{grid-column:2;justify-self:start;margin-top:4px}.benefits{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.benefit,.cause,.strength{background:var(--card);border:1px solid var(--line);border-radius:var(--r-sm);padding:22px}.benefit h4,.cause h4,.strength h4{font-family:var(--serif);font-size:20px;margin:0 0 8px;font-weight:500}.timeline{position:relative;padding-left:36px}.timeline:before{content:"";position:absolute;left:14px;top:8px;bottom:8px;width:1px;background:linear-gradient(180deg,var(--accent-2),var(--line))}.tl-item{position:relative;padding-bottom:28px}.tl-item:before{content:"";position:absolute;left:-29px;top:6px;width:14px;height:14px;border-radius:50%;background:var(--sheet);border:2px solid var(--accent)}.tl-period{font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:var(--accent);font-weight:600;margin-bottom:6px}.tl-card{background:var(--card);border:1px solid var(--line);border-radius:var(--r-sm);padding:20px 22px}.after-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}.after-card{padding:16px;margin:0}.note{margin-top:18px;padding:16px 20px;background:var(--card-2);border:1px solid var(--line);border-radius:var(--r-sm);font-size:13px;color:var(--ink-2);font-style:italic}.cta-block{background:radial-gradient(800px 400px at 80% 0%,rgba(200,154,122,.25),transparent 60%),linear-gradient(180deg,#fffaf1 0%,#efe1c6 100%);border:1px solid var(--line);border-radius:24px;padding:48px;display:grid;grid-template-columns:1.1fr .9fr;gap:36px;align-items:center}.cta-block h3{font-family:var(--serif);font-size:38px;line-height:1.15;margin:0 0 14px;font-weight:500}.btn{display:inline-flex;align-items:center;justify-content:center;gap:10px;padding:16px 28px;border-radius:999px;background:var(--ink);color:#faf5ec;border:1px solid var(--ink);font-size:13px;letter-spacing:.22em;text-transform:uppercase;font-weight:600;cursor:pointer;text-decoration:none}.footer{margin-top:48px;padding-top:32px;border-top:1px solid var(--line-soft);display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap;font-size:13px;color:var(--muted)}.brand{font-family:var(--serif);font-size:20px;color:var(--ink);font-style:italic}.loading{min-height:100vh;display:grid;place-items:center}.loading-card{width:min(520px,calc(100vw - 32px));border:1px solid var(--line);border-radius:24px;background:var(--sheet-2);padding:36px;text-align:center;box-shadow:var(--shadow)}
    @media(max-width:900px){body{padding:16px 8px 80px;font-size:16px}.sheet{padding:28px 22px 36px;border-radius:22px}.display{font-size:38px}.section-title{font-size:28px}.hero,.grid-4,.grid-3,.grid-2,.age-grid,.map-wrap,.zone-list,.benefits,.after-grid,.cta-block{grid-template-columns:1fr}.section{padding:40px 0}.range{font-size:64px}.zone{grid-template-columns:36px 1fr}.zone .status{grid-column:1/-1;justify-self:start}.summary-lead{padding:24px}.summary-lead .lead{font-size:22px}.cta-block{padding:32px}.cta-block h3{font-size:28px}}
  </style>
</head>
<body>
<div id="app" class="loading"><div class="loading-card"><div class="eyebrow">Bella Vladi · Face Protocol</div><p>Загружаю персональный отчет...</p></div></div>
<script>
const token="__TOKEN__";
const app=document.getElementById("app");
const e=(v)=>String(v ?? "").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const src=(asset)=>asset?.url || (asset?.path ? `/api/media/${asset.path}` : "");
const img=(asset,label,pending="Изображение формируется")=>src(asset)?`<img src="${e(src(asset))}" alt="${e(label)}">`:`<div class="image-placeholder">${e(pending)}</div>`;
const list=(items)=>Array.isArray(items)&&items.length?items:["Мягкая зона внимания."];
const cls=(s)=>s==="good"?"good":s==="priority"?"priority":"attention";
const textItems=(source,fallback="Мягкая зона внимания.")=>Array.isArray(source)?(source.length?source:[fallback]):((source?.items&&source.items.length)?source.items:[fallback]);
const textIntro=(source)=>Array.isArray(source)?"":(source?.intro || "");
const textOutro=(source)=>Array.isArray(source)?"":(source?.outro || "");
const MAP_POINTS=[{left:"50%",top:"18%"},{left:"50%",top:"33%"},{left:"35%",top:"37%"},{left:"61%",top:"52%"},{left:"50%",top:"65%"},{left:"68%",top:"75%"}];
async function ctaClick(){
  const res=await fetch(`/api/reports/${token}/cta-click`,{method:"POST",headers:{"ngrok-skip-browser-warning":"true"}});
  const data=await res.json();
  window.location.href=data.target_url || "#";
}
function render(r){
  app.className="";
  app.innerHTML=`<main class="sheet">
    <section class="hero"><div><div class="mono">BV</div><div class="eyebrow">Bella Vladi · Face Protocol</div><h1 class="display">Персональный <em>протокол лица</em></h1><p class="hero-sub">${e(r.summary.main_conclusion)}</p><div class="hero-meta"><div><span class="label">Для</span><span class="val">${e(r.user.name)}</span></div><div><span class="label">Дата анализа</span><span class="val">${e(r.meta.analysis_date)}</span></div><div><span class="label">Источник</span><span class="val">${e(r.user.source)}</span></div></div></div><div class="photo-card"><div class="photo-frame">${img(r.images.original_photo,"Фото пользователя")}</div><div class="photo-caption">Фото · ${e(r.meta.analysis_date)}</div></div></section>
    <section class="section"><div class="section-head"><span class="num">01</span><h2 class="section-title">Главный вывод</h2></div><div class="summary-lead"><span class="label">Резюме разбора</span><p class="lead">${e(r.summary.main_conclusion)}</p></div><div class="grid-4">${[["01","Главный фокус",r.summary.main_focus],["02","Потенциал",r.summary.potential],["03","Приоритетные зоны",(r.summary.priority_zones||[]).join(", ")],["04","Прогноз",r.summary.forecast_short]].map(x=>`<div class="mini"><span class="num">${x[0]}</span><div class="t">${e(x[1])}</div><div class="d">${e(x[2])}</div></div>`).join("")}</div></section>
    <section class="section"><div class="section-head"><span class="num">02</span><h2 class="section-title">Биологический возраст кожи</h2></div><div class="age-grid"><div class="age-big"><span class="label">Визуальный возраст</span><div class="range">${e(r.skin_age.value)}<small>${e(r.skin_age.unit)}</small></div><div class="label" style="color:var(--accent)">Score · ${e(r.skin_age.score)}</div><div class="scale"><div class="fill" style="width:${Number(r.skin_age.score_percent||78)}%"></div></div><p class="note">Это визуальная эстетическая оценка, а не медицинское заключение.</p></div><div class="card"><h3 class="card-title">Почему такой вывод</h3><p>${e(r.skin_age.explanation)}</p><div class="tags">${(r.zones||[]).slice(0,5).map(z=>`<span class="tag ${cls(z.status)}">${e(z.label)}</span>`).join("")}</div><h3 class="card-title" style="margin-top:22px">Потенциал улучшения</h3><p>${e(r.skin_age.improvement_potential)}</p></div></div></section>
    <section class="section"><div class="section-head"><span class="num">03</span><h2 class="section-title">Тип кожи</h2></div><div class="grid-2"><div class="card"><span class="label">Тип кожи</span><h3 class="card-title" style="margin-top:8px">${e(r.skin_type.title)}</h3><ul class="bullet">${list(r.skin_type.features).map(i=>`<li>${e(i)}</li>`).join("")}</ul></div><div class="card tinted"><span class="label">Сильные стороны кожи</span><ul class="bullet">${list(r.skin_type.strengths).map(i=>`<li>${e(i)}</li>`).join("")}</ul><span class="label" style="display:block;margin-top:20px">Зоны внимания</span><ul class="bullet">${list(r.skin_type.attention_points).map(i=>`<li>${e(i)}</li>`).join("")}</ul></div></div></section>
    <section class="section"><div class="section-head"><span class="num">04</span><h2 class="section-title">Карта зон лица</h2></div><div class="map-wrap"><div class="map-panel"><div class="face-map">${img(r.images.original_photo,"Карта зон лица","Фото загружается")}${(r.zones||[]).slice(0,6).map((z,n)=>`<span class="map-pin ${cls(z.status)}" style="left:${MAP_POINTS[n]?.left||"50%"};top:${MAP_POINTS[n]?.top||"50%"}">${e(z.number)}</span>`).join("")}</div><div class="legend compact"><span><i class="dot good"></i>Всё хорошо</span><span><i class="dot attention"></i>Зона внимания</span><span><i class="dot priority"></i>Приоритет</span></div></div><div class="zone-list">${(r.zones||[]).map(z=>`<article class="zone"><span class="zn">${e(z.number)}</span><div class="body"><b>${e(z.label)}</b><div>${e(z.short_comment)}</div><div class="extra">${e(z.recommended_focus)}</div></div><span class="status ${cls(z.status)}">${e(z.status_label)}</span></article>`).join("")}</div></div></section>
    <section class="section"><div class="section-head"><span class="num">05</span><h2 class="section-title">Почему это происходит</h2></div>${textIntro(r.causes)?`<div class="summary-lead"><span class="label">Логика вашего типа</span><p class="lead">${e(textIntro(r.causes))}</p></div>`:""}<div class="grid-3">${textItems(r.causes,"На состояние лица влияют лимфоток, тонус мышц, шея и привычная мимика.").map((i,n)=>`<article class="cause"><span class="num">${String(n+1).padStart(2,"0")}</span><h4>Фактор</h4><p>${e(i)}</p></article>`).join("")}</div>${textOutro(r.causes)?`<p class="note">${e(textOutro(r.causes))}</p>`:""}</section>
    <section class="section"><div class="summary-lead"><p class="lead">«Сильные стороны лица не надо исправлять. Их нужно раскрыть: через лимфу, шею, тонус и мягкую регулярность.»</p><div class="grid-3">${list(r.strengths).map(i=>`<article class="strength"><h4>${e(i)}</h4><p>Эта сторона лица уже работает как ресурс: на нее можно опереться, чтобы результат выглядел естественно.</p></article>`).join("")}</div></div></section>
    <section class="section"><div class="section-head"><span class="num">07</span><h2 class="section-title">Что даст фейсфитнес</h2></div><div class="benefits">${textItems(r.benefits,"Более свежий вид и мягкая поддержка овала лица.").map((i,n)=>`<article class="benefit"><span class="num">${n+1}</span><h4>Визуальный эффект</h4><p>${e(i)}</p></article>`).join("")}</div>${textOutro(r.benefits)?`<div class="summary-lead" style="margin-top:18px"><p class="lead">${e(textOutro(r.benefits))}</p></div>`:""}</section>
    <section class="section"><div class="section-head"><span class="num">08</span><h2 class="section-title">Прогноз по времени</h2></div><div class="timeline">${(r.forecast||[]).map(i=>`<div class="tl-item"><div class="tl-period">${e(i.period)}</div><div class="tl-card">${e(i.text)}</div></div>`).join("")}</div></section>
    ${r.after_photo?.state==="disabled"?"":`<section class="section"><div class="section-head"><span class="num">09</span><h2 class="section-title">After-photo</h2></div><div class="after-grid"><figure class="after-card"><div class="photo-frame">${img(r.images.original_photo,"Исходное фото")}</div><figcaption class="photo-caption">Исходное фото</figcaption></figure><figure class="after-card"><div class="photo-frame">${r.after_photo.state==="ready"?img(r.images.after_photo,"AI-визуализация"):img(null,"AI-визуализация",r.after_photo.message)}</div><figcaption class="photo-caption">AI-визуализация</figcaption></figure></div><p class="note">${e(r.after_photo.message)} Визуализация не является гарантией результата.</p></section>`}
    <section class="section"><div class="cta-block"><div><h3>Следующий шаг: персональная программа Bella Vladi</h3><p>Получите программу, которая опирается на ваши зоны внимания и сильные стороны лица.</p></div><button class="btn" onclick="ctaClick()">${e(r.cta.text)} →</button></div></section>
    <footer class="footer"><div class="brand">Bella Vladi</div><div>${e(r.disclaimer)}</div></footer>
  </main>`;
}
const initialReport=__REPORT_JSON__;
const loadReport=initialReport
  ? Promise.resolve(initialReport)
  : fetch(`/api/reports/${token}`,{headers:{"ngrok-skip-browser-warning":"true"}}).then(r=>r.json());
loadReport.then(d=>render(d.view_model)).catch(()=>{app.innerHTML='<div class="loading-card"><div class="eyebrow">Отчет недоступен</div><p>Не удалось загрузить публичный отчет.</p></div>'});
</script>
</body>
</html>
"""


@router.get("/report/{token}", response_class=HTMLResponse)
def public_report_page(token: str, request: Request, db: Session = Depends(get_db)) -> str:
    report = db.query(GeneratedReport).filter(GeneratedReport.public_token == token, GeneratedReport.is_published.is_(True)).first()
    if not report:
        raise not_found("Отчет не найден")
    bot_settings = get_bot_settings(db)
    report.opened_count += 1
    if report.analysis and report.analysis.lead:
        report.analysis.lead.report_opened = True
        if report.analysis.lead.crm_status not in {ClientStatus.CTA_CLICKED, ClientStatus.PAID, ClientStatus.BOUGHT}:
            report.analysis.lead.crm_status = ClientStatus.REPORT_OPENED
        add_lead_event(db, report.analysis.lead, "report_opened", "Пользователь открыл отчет", {"report_id": report.id})
    db.add(
        ReportViewEvent(
            report_id=report.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    db.commit()
    public_app_url = (env_settings.public_app_url or env_settings.frontend_url or "").rstrip("/")
    backend_url = (env_settings.backend_url or "").rstrip("/")
    if public_app_url and public_app_url != backend_url:
        return RedirectResponse(f"{public_app_url}/report/{_e(token)}")
    return render_bella_web_report_html(report, bot_settings)

    analysis = report.analysis
    report_json = report.report_json or {}
    analysis_json = analysis.analysis_json if analysis else {}
    user_name = report_json.get("user_name") or (analysis.lead.name if analysis and analysis.lead else "Ваш протокол")
    original = _url(analysis.original_photo_path if analysis else None)
    protocol_slide_paths = []
    if analysis:
        if analysis.protocol_version == "v4":
            protocol_slide_paths = analysis.protocol_slide_paths or []
        else:
            protocol_slide_paths = analysis.protocol_slide_paths or [
                image.path
                for image in sorted(analysis.images, key=lambda item: (item.metadata_json or {}).get("slide", item.id))
                if image.kind == "protocol_slide" and image.path
            ]
    protocol_source = protocol_slide_paths[0] if protocol_slide_paths else (
        analysis.legacy_protocol_image_path if analysis and analysis.protocol_version not in {"v2", "v3", "v4"} else None
    )
    protocol = _url(protocol_source)
    after = _url((analysis.after_photo_final_path or analysis.after_photo_path) if analysis and after_photo_feature_enabled() else None)
    cta_target = bot_settings.whatsapp_url or bot_settings.telegram_url or bot_settings.instagram_url or env_settings.public_app_url
    cta_url = f"{env_settings.backend_url.rstrip('/')}/report/{token}/cta" if env_settings.backend_url else f"/report/{token}/cta"

    skin_age = analysis_json.get("skin_visual_age", {})
    skin_type = analysis_json.get("skin_type", {})
    face_strengths = analysis_json.get("face_type_and_aging_type", {})
    zones = analysis_json.get("zones", [])
    forecast = analysis_json.get("time_forecast", {})

    priority_zones = [zone.get("name") for zone in zones if zone.get("status") == "priority" or zone.get("color") == "red"]
    if not priority_zones:
        priority_zones = [zone.get("name") for zone in zones[:2]]

    zones_html = "".join(
        f"""
        <article class="zone-row {zone.get('color', 'yellow')}">
          <span class="zone-number">{_e(zone.get('number'))}</span>
          <div>
            <h3>{_e(zone.get('name'))}</h3>
            <p>{_e(zone.get('short_comment'))}</p>
            <small>{_e(zone.get('recommended_focus'))}</small>
          </div>
          <b>{_zone_label(zone)}</b>
        </article>
        """
        for zone in zones
    )

    causes_html = _items_html(analysis_json.get("causes"), "Тонус мышц, лимфоток, осанка и ежедневные мимические привычки.")
    strengths_html = _items_html(analysis_json.get("strengths"), "Естественная выразительность лица и хороший потенциал отклика на регулярную практику.")
    benefits_html = _items_html(analysis_json.get("facefitness_benefits"), "Более свежий вид, мягкое снижение отечности и поддержка овала лица.")
    features_html = _items_html(skin_type.get("features"), "Особенности кожи лучше оценивать мягко, без медицинских выводов.")
    attention_html = _items_html(skin_type.get("attention_points"), "Отечность, тонус и микроциркуляция.")

    return f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bella Vladi Face Protocol</title>
  <style>
    :root {{
      --bg: #fbf6ef;
      --paper: #fffdf9;
      --pearl: #eaded5;
      --ink: #302a27;
      --clay: #745f57;
      --muted: #9a8177;
      --rose: #b76f7c;
      --sage: #719a7e;
      --amber: #d6ab4d;
      --red: #c45e5b;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }}
    main {{ max-width:1120px; margin:0 auto; padding:28px 18px 96px; }}
    img {{ display:block; width:100%; object-fit:cover; }}
    .cover {{ display:grid; grid-template-columns:minmax(0,1.05fr) minmax(300px,.75fr); gap:20px; align-items:stretch; min-height:520px; }}
    .cover-copy {{ display:flex; flex-direction:column; justify-content:space-between; padding:34px; border:1px solid var(--pearl); border-radius:8px; background:linear-gradient(135deg,#fffdf9 0%,#f5e9e0 100%); box-shadow:0 18px 55px rgba(48,42,39,.09); }}
    .cover-image {{ overflow:hidden; border:1px solid var(--pearl); border-radius:8px; background:var(--paper); box-shadow:0 18px 55px rgba(48,42,39,.09); }}
    .cover-image img {{ height:100%; min-height:460px; }}
    .eyebrow {{ margin:0 0 14px; color:var(--rose); font-size:15px; font-weight:800; }}
    h1 {{ max-width:720px; margin:0; font-size:58px; line-height:1.02; }}
    h2 {{ margin:0 0 16px; font-size:25px; line-height:1.16; }}
    h3 {{ margin:0; font-size:17px; }}
    p, li {{ font-size:16px; line-height:1.68; }}
    ul {{ margin:14px 0 0; padding-left:20px; }}
    .lead {{ max-width:720px; margin:20px 0 0; color:var(--clay); font-size:20px; }}
    .disclaimer {{ margin:28px 0 0; padding:14px 16px; border:1px solid rgba(183,111,124,.24); border-radius:8px; background:rgba(255,255,255,.6); color:var(--clay); font-size:14px; }}
    .summary-strip {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin:18px 0; }}
    .metric, .card {{ border:1px solid var(--pearl); border-radius:8px; background:rgba(255,253,249,.94); box-shadow:0 16px 45px rgba(48,42,39,.07); }}
    .metric {{ padding:18px; }}
    .metric span {{ display:block; margin-bottom:8px; color:var(--muted); font-size:13px; font-weight:800; }}
    .metric b {{ display:block; font-size:19px; line-height:1.35; }}
    .section-grid {{ display:grid; gap:18px; margin-top:18px; }}
    .three {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
    .two {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    .card {{ padding:24px; }}
    .section-head {{ display:flex; gap:12px; align-items:center; margin-bottom:14px; }}
    .number {{ display:inline-grid; width:34px; height:34px; place-items:center; flex:0 0 auto; border-radius:50%; background:var(--rose); color:#fff; font-weight:900; }}
    .number.green {{ background:var(--sage); }}
    .number.amber {{ background:var(--amber); }}
    .number.dark {{ background:var(--ink); }}
    .card strong {{ display:block; margin-bottom:10px; font-size:19px; line-height:1.42; }}
    .map-layout {{ display:grid; grid-template-columns:minmax(320px,.8fr) minmax(0,1fr); gap:18px; align-items:start; }}
    .protocol-frame {{ overflow:hidden; border:1px solid var(--pearl); border-radius:8px; background:#fff; }}
    .legend {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; color:var(--clay); font-size:14px; font-weight:700; }}
    .legend span {{ display:inline-flex; align-items:center; gap:7px; }}
    .dot {{ display:inline-block; width:12px; height:12px; border-radius:50%; }}
    .dot.green, .zone-row.green .zone-number {{ background:var(--sage); }}
    .dot.yellow, .zone-row.yellow .zone-number {{ background:var(--amber); }}
    .dot.red, .zone-row.red .zone-number {{ background:var(--red); }}
    .zone-list {{ display:grid; gap:10px; }}
    .zone-row {{ display:grid; grid-template-columns:38px minmax(0,1fr) auto; gap:12px; align-items:start; padding:14px; border:1px solid var(--pearl); border-left-width:5px; border-radius:8px; background:#fff; }}
    .zone-row.green {{ border-left-color:var(--sage); }}
    .zone-row.yellow {{ border-left-color:var(--amber); }}
    .zone-row.red {{ border-left-color:var(--red); }}
    .zone-number {{ display:grid; width:30px; height:30px; place-items:center; border-radius:50%; color:#fff; font-weight:900; }}
    .zone-row p {{ margin:4px 0; color:var(--clay); }}
    .zone-row small {{ display:block; color:var(--muted); line-height:1.55; }}
    .zone-row b {{ color:var(--clay); font-size:13px; white-space:nowrap; }}
    .timeline {{ display:grid; gap:12px; }}
    .timeline p {{ margin:0; padding:14px; border-radius:8px; background:#f5e9e0; }}
    .timeline b {{ display:block; margin-bottom:5px; color:var(--rose); }}
    .compare {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
    .compare figure {{ margin:0; }}
    .compare img, .image-placeholder {{ min-height:360px; border-radius:8px; background:#f2e6dc; }}
    .compare figcaption {{ margin-top:8px; color:var(--muted); font-size:13px; }}
    .image-placeholder {{ display:grid; place-items:center; padding:28px; color:var(--muted); text-align:center; }}
    .sticky-cta {{ position:fixed; left:50%; bottom:18px; transform:translateX(-50%); display:flex; width:min(720px,calc(100vw - 28px)); gap:14px; align-items:center; justify-content:space-between; padding:12px 12px 12px 18px; border:1px solid var(--pearl); border-radius:8px; background:rgba(255,253,249,.96); box-shadow:0 16px 45px rgba(48,42,39,.18); backdrop-filter:blur(12px); }}
    .button {{ display:inline-flex; min-height:44px; align-items:center; justify-content:center; padding:0 18px; border-radius:8px; background:var(--rose); color:#fff; text-decoration:none; font-weight:900; }}
    @media (max-width: 860px) {{
      main {{ padding-top:16px; }}
      .cover, .summary-strip, .three, .two, .map-layout, .compare {{ grid-template-columns:1fr; }}
      .cover {{ min-height:0; }}
      h1 {{ font-size:40px; }}
      .cover-copy {{ padding:24px; }}
      .zone-row {{ grid-template-columns:34px minmax(0,1fr); }}
      .zone-row b {{ grid-column:2; }}
      .sticky-cta {{ align-items:stretch; flex-direction:column; }}
      .button {{ width:100%; }}
    }}
  </style>
</head>
<body>
<main>
  <section class="cover">
    <div class="cover-copy">
      <div>
        <p class="eyebrow">Bella Vladi Face Protocol · {_e(report_json.get("date", ""))}</p>
        <h1>{_e(user_name)}</h1>
        <p class="lead">{_e(analysis_json.get("summary", "Ваш персональный face-протокол готов."))}</p>
      </div>
      <p class="disclaimer">{_e(bot_settings.disclaimer)}</p>
    </div>
    <div class="cover-image">{_image(original, "Фото пользователя")}</div>
  </section>

  <section class="summary-strip">
    <div class="metric"><span>Главный фокус</span><b>{_e(report_json.get("main_problem") or ", ".join(priority_zones) or "Тонус и свежесть лица")}</b></div>
    <div class="metric"><span>Главный потенциал</span><b>{_e(report_json.get("main_potential") or "Хороший отклик на регулярную практику")}</b></div>
    <div class="metric"><span>Приоритетные зоны</span><b>{_e(", ".join(priority_zones) or "мягкая поддержка овала и свежести")}</b></div>
  </section>

  <section class="section-grid three">
    <article class="card">
      <div class="section-head"><span class="number">1</span><h2>Биологический возраст кожи</h2></div>
      <strong>{_e(skin_age.get("estimated_range"))}</strong>
      <p>{_e(skin_age.get("explanation"))}</p>
    </article>
    <article class="card">
      <div class="section-head"><span class="number green">2</span><h2>Тип кожи</h2></div>
      <strong>{_e(_skin_type_public_title(skin_type.get("type")))}</strong>
      <ul>{features_html}</ul>
    </article>
    <article class="card">
      <div class="section-head"><span class="number amber">3</span><h2>Сильные стороны и тип старения</h2></div>
      <strong>{_e(face_strengths.get("face_type"))} · {_e(face_strengths.get("aging_type"))}</strong>
      <p>{_e(face_strengths.get("explanation"))}</p>
    </article>
  </section>

  <section class="card section-grid">
    <div class="section-head"><span class="number dark">4</span><h2>Карта зон лица</h2></div>
    <div class="map-layout">
      <div class="protocol-frame">{_image(protocol, "Фото-протокол Bella Vladi")}</div>
      <div>
        <div class="legend">
          <span><i class="dot green"></i>Все хорошо</span>
          <span><i class="dot yellow"></i>Зона внимания</span>
          <span><i class="dot red"></i>Приоритет</span>
        </div>
        <div class="zone-list">{zones_html}</div>
      </div>
    </div>
  </section>

  <section class="section-grid two">
    <article class="card">
      <div class="section-head"><span class="number">5</span><h2>Почему это происходит</h2></div>
      <ul>{causes_html}</ul>
    </article>
    <article class="card">
      <div class="section-head"><span class="number green">6</span><h2>Ваши сильные стороны</h2></div>
      <ul>{strengths_html}</ul>
    </article>
  </section>

  <section class="section-grid two">
    <article class="card">
      <div class="section-head"><span class="number amber">7</span><h2>Что даст фейсфитнес</h2></div>
      <ul>{benefits_html}</ul>
    </article>
    <article class="card">
      <div class="section-head"><span class="number dark">8</span><h2>Прогноз по времени</h2></div>
      <div class="timeline">
        <p><b>Первые изменения</b>{_e(forecast.get("first_changes", "7-14 дней: больше свежести и меньше утренней отечности."))}</p>
        <p><b>Заметный визуальный эффект</b>{_e(forecast.get("visible_changes", "4-6 недель: заметнее тонус, взгляд и линия овала."))}</p>
        <p><b>Устойчивый результат</b>{_e(forecast.get("stable_result", "8-12 недель: более устойчивый эффект при регулярной практике."))}</p>
      </div>
    </article>
  </section>

  <section class="card">
    <h2>Зоны внимания по типу кожи</h2>
    <ul>{attention_html}</ul>
  </section>
</main>
<aside class="sticky-cta">
  <strong>Следующий шаг: персональная программа Bella Vladi</strong>
  <a class="button" href="{_e(cta_url)}">{_e(bot_settings.cta_text)}</a>
</aside>
</body>
</html>
"""


@router.get("/report/{token}/cta")
def public_report_cta(token: str, request: Request, db: Session = Depends(get_db)):
    report = db.query(GeneratedReport).filter(GeneratedReport.public_token == token, GeneratedReport.is_published.is_(True)).first()
    if not report:
        raise not_found("Отчет не найден")
    bot_settings = get_bot_settings(db)
    target = bot_settings.whatsapp_url or bot_settings.telegram_url or bot_settings.instagram_url or env_settings.public_app_url
    report.cta_click_count += 1
    if report.analysis and report.analysis.lead:
        report.analysis.lead.cta_clicked = True
        report.analysis.lead.crm_status = ClientStatus.CTA_CLICKED
        add_lead_event(db, report.analysis.lead, "cta_clicked", "Пользователь нажал CTA", {"report_id": report.id, "target_url": target})
    db.add(
        CtaClickEvent(
            report_id=report.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            target_url=target,
        )
    )
    db.commit()
    from fastapi.responses import RedirectResponse

    return RedirectResponse(target)
