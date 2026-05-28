import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";

import { apiRequest, storageUrl } from "../api/client";

type Asset = { path?: string | null; url?: string | null };
type TextBlock = string[] | { intro?: string; items?: string[]; outro?: string } | null | undefined;

const MAP_POINTS = [
  { left: "50%", top: "18%" },
  { left: "50%", top: "33%" },
  { left: "35%", top: "37%" },
  { left: "61%", top: "52%" },
  { left: "50%", top: "65%" },
  { left: "68%", top: "75%" },
];

function assetUrl(asset?: Asset | string | null) {
  if (!asset) return "";
  if (typeof asset === "string") return storageUrl(asset);
  return asset.url || storageUrl(asset.path) || "";
}

function statusClass(status?: string) {
  if (status === "good") return "good";
  if (status === "priority") return "priority";
  return "attention";
}

function textItems(source?: TextBlock, fallback = "Мягкая зона внимания.") {
  const items = Array.isArray(source) ? source : source?.items;
  return items?.length ? items : [fallback];
}

function textIntro(source?: TextBlock) {
  return !Array.isArray(source) ? source?.intro || "" : "";
}

function textOutro(source?: TextBlock) {
  return !Array.isArray(source) ? source?.outro || "" : "";
}

function PhotoFrame({ asset, label, pendingText }: { asset?: Asset | null; label: string; pendingText?: string }) {
  const src = assetUrl(asset);
  return (
    <figure className="photo-card soft-card">
      <div className="photo-frame">
        {src ? <img src={src} alt={label} /> : <div className="image-placeholder">{pendingText || "Изображение формируется"}</div>}
      </div>
      <figcaption className="photo-caption">{label}</figcaption>
    </figure>
  );
}

function CompactZoneMap({ report }: { report: any }) {
  const photo = assetUrl(report.images?.original_photo);
  const zones = (report.zones || []).slice(0, 6);
  return (
    <div className="map-panel">
      <div className="face-map">
        {photo ? <img src={photo} alt="Карта зон лица" /> : <div className="image-placeholder">Фото загружается</div>}
        {zones.map((zone: any, index: number) => (
          <span
            key={`${zone.number}-${zone.label}`}
            className={`map-pin ${statusClass(zone.status)}`}
            style={MAP_POINTS[index] || MAP_POINTS[MAP_POINTS.length - 1]}
          >
            {zone.number}
          </span>
        ))}
      </div>
      <div className="legend compact">
        <span><i className="dot good" />Всё хорошо</span>
        <span><i className="dot attention" />Внимание</span>
        <span><i className="dot priority" />Приоритет</span>
      </div>
    </div>
  );
}

const reportStyles = `
:root {
  --bg:#ece4d7; --sheet:#faf5ec; --sheet-2:#fffaf1;
  --card:#fdfbf5; --card-2:#f7f0e3;
  --line:#e5d8c2; --line-soft:#efe6d3;
  --ink:#3a2a1e; --ink-2:#5a4636; --muted:#8c7868;
  --accent:#a8755a; --accent-2:#c89a7a;
  --good:#8aa183; --good-soft:rgba(138,161,131,.18);
  --attention:#c9a96a; --attention-soft:rgba(201,169,106,.20);
  --priority:#c08474; --priority-soft:rgba(192,132,116,.20);
  --serif:"Cormorant Garamond","Playfair Display",Georgia,"Times New Roman",serif;
  --sans:"Inter","Helvetica Neue",Arial,sans-serif;
  --r:20px; --r-sm:12px;
  --shadow:0 1px 0 rgba(58,42,30,.04), 0 10px 30px rgba(58,42,30,.06);
}
.public-report, .public-report * { box-sizing:border-box; }
.public-report {
  min-height:100vh; background:var(--bg); color:var(--ink);
  font-family:var(--sans); font-size:17px; line-height:1.58;
  padding:32px 16px 92px; -webkit-font-smoothing:antialiased;
}
.public-report img { display:block; width:100%; height:100%; object-fit:cover; }
.report-sheet {
  max-width:1140px; margin:0 auto;
  background:radial-gradient(1200px 600px at 50% -10%, #fff8ea 0%, transparent 60%), linear-gradient(180deg,var(--sheet-2) 0%, var(--sheet) 100%);
  border:1px solid var(--line); border-radius:28px;
  box-shadow:0 1px 0 rgba(255,255,255,.6) inset, 0 30px 80px -30px rgba(58,42,30,.25), 0 8px 24px rgba(58,42,30,.08);
  padding:56px 56px 48px; overflow:hidden;
}
.mono {
  width:58px; height:58px; border-radius:50%; border:1px solid var(--accent); color:var(--accent);
  font-family:var(--serif); font-style:italic; font-size:28px;
  display:flex; align-items:center; justify-content:center; background:var(--sheet-2); margin-bottom:24px;
}
.eyebrow, .label {
  font-size:12px; letter-spacing:.42em; text-transform:uppercase; color:var(--muted); font-weight:500;
}
.display {
  font-family:var(--serif); font-weight:500; font-size:64px; line-height:1.04; letter-spacing:.5px;
  margin:14px 0 18px; color:var(--ink);
}
.display em { font-style:italic; color:var(--accent); font-weight:400; }
.hero { display:grid; grid-template-columns:1.18fr .82fr; gap:40px; align-items:center; padding-bottom:42px; border-bottom:1px solid var(--line-soft); }
.hero-sub { font-size:18px; line-height:1.55; color:var(--ink-2); max-width:620px; margin:6px 0 0; }
.hero-meta { display:flex; gap:28px; margin-top:28px; flex-wrap:wrap; padding:18px 0; border-top:1px solid var(--line-soft); border-bottom:1px solid var(--line-soft); }
.hero-meta div { display:flex; flex-direction:column; gap:4px; }
.hero-meta .val { font-family:var(--serif); font-size:22px; color:var(--ink); }
.photo-frame { aspect-ratio:4/5; border-radius:18px; overflow:hidden; background:radial-gradient(120% 80% at 50% 30%, #f1e3cb 0%, #e0cdaf 60%, #c9b18c 100%); }
.image-placeholder { min-height:100%; display:grid; place-items:center; padding:28px; color:var(--muted); text-align:center; background:var(--card-2); }
.photo-caption { text-align:center; padding:12px 4px 4px; font-size:11px; letter-spacing:.3em; text-transform:uppercase; color:var(--muted); }
.section { padding:44px 0; border-top:1px solid var(--line-soft); }
.section:first-of-type { border-top:none; }
.section-head { display:flex; align-items:baseline; gap:18px; margin-bottom:20px; }
.num { font-family:var(--serif); font-style:italic; color:var(--accent); font-size:20px; letter-spacing:.04em; }
.section-title { font-family:var(--serif); font-weight:500; font-size:38px; line-height:1.1; letter-spacing:.3px; margin:0; }
.section-sub { color:var(--muted); font-size:15px; letter-spacing:.04em; max-width:780px; margin:-8px 0 24px; }
.soft-card, .card, .mini-card, .story-lead, .map-panel, .zone, .timeline-card {
  background:var(--card); border:1px solid var(--line); border-radius:var(--r); box-shadow:var(--shadow);
}
.photo-card { background:var(--card-2); padding:14px; margin:0; }
.story-lead { padding:32px 36px; margin-bottom:20px; }
.story-lead .lead { font-family:var(--serif); font-size:28px; line-height:1.28; color:var(--ink); margin:10px 0 0; }
.grid-4 { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; }
.grid-3 { display:grid; grid-template-columns:repeat(3,1fr); gap:18px; }
.grid-2 { display:grid; grid-template-columns:repeat(2,1fr); gap:22px; align-items:start; }
.mini-card { border-radius:var(--r-sm); padding:18px; }
.mini-card .t, .card-title { font-family:var(--serif); font-size:22px; line-height:1.2; margin:0 0 8px; font-weight:500; }
.mini-card .d, .card p, .card li { color:var(--ink-2); }
.card { padding:26px; }
.card.tinted { background:var(--card-2); }
.card.warm { background:linear-gradient(180deg,#fffaf1 0%, #f5ead5 100%); }
.age-grid { display:grid; grid-template-columns:.82fr 1.18fr; gap:28px; align-items:stretch; }
.age-big { background:linear-gradient(180deg,#fffaf1 0%, #f5ead5 100%); border:1px solid var(--line); border-radius:var(--r); padding:32px; display:flex; flex-direction:column; justify-content:space-between; box-shadow:var(--shadow); }
.range { font-family:var(--serif); font-size:82px; line-height:1; color:var(--ink); margin:16px 0 6px; }
.range small { font-size:32px; color:var(--accent); font-style:italic; margin-left:6px; }
.scale { margin-top:22px; height:8px; border-radius:99px; background:rgba(168,117,90,.15); position:relative; overflow:hidden; }
.scale .fill { position:absolute; inset:0 auto 0 0; background:linear-gradient(90deg,var(--accent-2),var(--accent)); border-radius:99px; }
.after-note, .editor-note {
  margin-top:16px; padding:15px 18px; background:var(--card-2); border:1px solid var(--line); border-radius:var(--r-sm);
  font-size:14px; color:var(--ink-2); line-height:1.55; font-style:italic;
}
.tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:18px; }
.tag, .status {
  display:inline-flex; align-items:center; padding:6px 12px; border-radius:99px;
  font-size:11px; letter-spacing:.16em; text-transform:uppercase; font-weight:600;
}
.tag { background:var(--card-2); border:1px solid var(--line); color:var(--ink-2); }
.tag.good, .status.good, .map-pin.good { background:var(--good-soft); color:#4d6147; }
.tag.attention, .status.attention, .map-pin.attention { background:var(--attention-soft); color:#7d6324; }
.tag.priority, .status.priority, .map-pin.priority { background:var(--priority-soft); color:#7a3f31; }
.bullet { margin:8px 0 0; padding:0; list-style:none; }
.bullet li { position:relative; padding:8px 0 8px 22px; border-bottom:1px solid var(--line-soft); }
.bullet li:last-child { border-bottom:none; }
.bullet li::before { content:""; position:absolute; left:0; top:18px; width:7px; height:7px; border-radius:50%; background:var(--accent-2); }
.map-wrap { display:grid; grid-template-columns:360px 1fr; gap:22px; align-items:start; }
.map-panel { padding:14px; align-self:start; position:sticky; top:18px; }
.face-map { position:relative; aspect-ratio:4/5; border-radius:16px; overflow:hidden; background:var(--card-2); }
.map-pin {
  position:absolute; transform:translate(-50%,-50%); width:30px; height:30px; border-radius:50%;
  display:grid; place-items:center; border:1px solid rgba(255,255,255,.7); box-shadow:0 6px 18px rgba(58,42,30,.22);
  font-size:13px; font-weight:700;
}
.legend { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px; font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-2); }
.legend.compact { justify-content:center; margin:14px 0 0; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:8px; vertical-align:middle; }
.dot.good { background:var(--good); } .dot.attention { background:var(--attention); } .dot.priority { background:var(--priority); }
.zone-list { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; align-items:start; }
.zone { display:grid; grid-template-columns:30px 1fr; gap:10px; align-items:start; padding:14px; border-radius:var(--r-sm); }
.zn { width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-family:var(--serif); color:var(--ink); background:var(--card-2); border:1px solid var(--line); font-size:14px; }
.zone b { color:var(--ink); font-family:var(--serif); font-size:17px; line-height:1.15; font-weight:500; display:block; margin-bottom:4px; }
.zone .body { font-size:13px; color:var(--ink-2); line-height:1.42; }
.zone .extra { margin-top:7px; font-size:12px; color:var(--muted); }
.zone .status { grid-column:2; justify-self:start; margin-top:4px; }
.cause-grid, .strengths-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.cause, .strength { background:var(--card); border:1px solid var(--line); border-radius:var(--r-sm); padding:20px; }
.cause h4, .strength h4, .benefit h4 { font-family:var(--serif); font-size:20px; margin:0 0 8px; font-weight:500; }
.editorial { background:linear-gradient(180deg,#fffaf1 0%, #f1e3c8 100%); border:1px solid var(--line); border-radius:var(--r); padding:34px; }
.editorial .quote { font-family:var(--serif); font-style:italic; font-size:28px; line-height:1.35; color:var(--ink); margin:0 0 24px; }
.benefits { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.benefit { display:grid; grid-template-columns:42px 1fr; gap:14px; background:var(--card); border:1px solid var(--line); border-radius:var(--r-sm); padding:20px; }
.bi { width:38px; height:38px; border-radius:50%; background:var(--card-2); border:1px solid var(--line); display:flex; align-items:center; justify-content:center; font-family:var(--serif); color:var(--accent); font-style:italic; }
.benefit-outro { margin-top:18px; padding:22px 26px; border:1px solid var(--line); border-radius:var(--r); background:linear-gradient(180deg,#f6ecd9 0%,#efe1c8 100%); font-family:var(--serif); font-size:26px; line-height:1.25; color:var(--ink); }
.timeline { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.timeline-card { padding:22px; border-radius:var(--r-sm); }
.tl-period { font-size:11px; letter-spacing:.25em; text-transform:uppercase; color:var(--accent); font-weight:600; margin-bottom:10px; }
.after-grid { display:grid; grid-template-columns:1fr 1fr; gap:22px; }
.cta-block { background:linear-gradient(180deg,#fffaf1 0%, #efe1c6 100%); border:1px solid var(--line); border-radius:24px; padding:44px; display:grid; grid-template-columns:1.1fr .9fr; gap:36px; align-items:center; }
.cta-block h3 { font-family:var(--serif); font-size:36px; line-height:1.15; margin:0 0 14px; font-weight:500; }
.btn { display:inline-flex; align-items:center; justify-content:center; gap:10px; padding:16px 28px; border-radius:999px; background:var(--ink); color:#faf5ec; border:1px solid var(--ink); font-size:13px; letter-spacing:.22em; text-transform:uppercase; font-weight:600; cursor:pointer; text-decoration:none; }
.footer { margin-top:44px; padding-top:28px; border-top:1px solid var(--line-soft); display:flex; justify-content:space-between; gap:24px; flex-wrap:wrap; font-size:13px; color:var(--muted); }
.footer .brand { font-family:var(--serif); font-size:20px; color:var(--ink); font-style:italic; }
.loader { min-height:100vh; display:grid; place-items:center; background:var(--bg); color:var(--ink); font-family:var(--sans); }
.loader-card { width:min(520px, calc(100vw - 32px)); border:1px solid var(--line); border-radius:24px; background:var(--sheet-2); padding:36px; text-align:center; box-shadow:var(--shadow); }
.loader-card svg { margin:0 auto 14px; color:var(--accent); }
@media (max-width: 900px) {
  .public-report { padding:16px 8px 80px; font-size:16px; }
  .report-sheet { padding:28px 22px 36px; border-radius:22px; }
  .display { font-size:38px; }
  .section-title { font-size:28px; }
  .hero, .grid-4, .grid-3, .grid-2, .age-grid, .map-wrap, .zone-list, .cause-grid, .strengths-grid, .benefits, .timeline, .after-grid, .cta-block { grid-template-columns:1fr; }
  .section { padding:36px 0; }
  .range { font-size:64px; }
  .map-panel { position:relative; top:auto; }
  .story-lead, .editorial, .cta-block { padding:26px; }
  .story-lead .lead, .editorial .quote, .benefit-outro { font-size:22px; }
  .cta-block h3 { font-size:28px; }
}
`;

export function PublicReport() {
  const { publicToken, token } = useParams();
  const reportToken = publicToken || token;
  const openedTracked = useRef(false);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["public-report", reportToken],
    queryFn: () => apiRequest<any>(`/api/reports/${reportToken}`),
    enabled: Boolean(reportToken),
  });
  const view = useMutation({ mutationFn: () => apiRequest(`/api/reports/${reportToken}/view`, { method: "POST" }) });
  const cta = useMutation({ mutationFn: () => apiRequest<{ target_url: string }>(`/api/reports/${reportToken}/cta-click`, { method: "POST" }) });

  useEffect(() => {
    if (!reportToken || openedTracked.current) return;
    openedTracked.current = true;
    view.mutate();
  }, [reportToken]);

  if (isLoading) {
    return (
      <>
        <style>{reportStyles}</style>
        <div className="loader">
          <div className="loader-card">
            <Loader2 className="animate-spin" size={30} />
            <div className="eyebrow">Bella Vladi · Face Protocol</div>
            <p>Загружаю персональный отчет...</p>
          </div>
        </div>
      </>
    );
  }

  if (isError || !data?.view_model) {
    return (
      <>
        <style>{reportStyles}</style>
        <div className="loader">
          <div className="loader-card">
            <div className="eyebrow">Отчет недоступен</div>
            <p>{error instanceof Error ? error.message : "Не удалось загрузить публичный отчет."}</p>
          </div>
        </div>
      </>
    );
  }

  const report = data.view_model;
  const causes = textItems(report.causes, "На состояние лица влияют лимфоток, тонус мышц, шея и привычная мимика.");
  const benefits = textItems(report.benefits, "Более свежий вид и мягкая поддержка овала лица.");
  const onCta = async () => {
    const result = await cta.mutateAsync();
    const target = result.target_url || report.cta?.url || "#";
    window.location.href = target;
  };

  return (
    <>
      <style>{reportStyles}</style>
      <main className="public-report">
        <div className="report-sheet">
          <section className="hero">
            <div>
              <div className="mono">BV</div>
              <div className="eyebrow">Bella Vladi · Face Protocol</div>
              <h1 className="display">Персональный <em>протокол лица</em></h1>
              <p className="hero-sub">{report.summary.main_conclusion}</p>
              <div className="hero-meta">
                <div><span className="label">Для</span><span className="val">{report.user.name}</span></div>
                <div><span className="label">Дата анализа</span><span className="val">{report.meta.analysis_date}</span></div>
                <div><span className="label">Источник</span><span className="val">{report.user.source}</span></div>
              </div>
            </div>
            <PhotoFrame asset={report.images.original_photo} label={`Фото · ${report.meta.analysis_date}`} />
          </section>

          <section className="section">
            <div className="section-head"><span className="num">01</span><h2 className="section-title">Главный вывод</h2></div>
            <div className="story-lead">
              <span className="label">Резюме разбора</span>
              <p className="lead">{report.summary.main_conclusion}</p>
            </div>
            <div className="grid-4">
              <div className="mini-card"><span className="num">01</span><div className="t">Главный фокус</div><div className="d">{report.summary.main_focus}</div></div>
              <div className="mini-card"><span className="num">02</span><div className="t">Потенциал</div><div className="d">{report.summary.potential}</div></div>
              <div className="mini-card"><span className="num">03</span><div className="t">Зоны роста</div><div className="d">{(report.summary.priority_zones || []).join(", ")}</div></div>
              <div className="mini-card"><span className="num">04</span><div className="t">Прогноз</div><div className="d">{report.summary.forecast_short}</div></div>
            </div>
          </section>

          <section className="section">
            <div className="section-head"><span className="num">02</span><h2 className="section-title">Портрет кожи и морфотипа</h2></div>
            <div className="age-grid">
              <div className="age-big">
                <span className="label">Визуальный возраст кожи</span>
                <div className="range">{report.skin_age.value}<small>{report.skin_age.unit}</small></div>
                <div className="label" style={{ color: "var(--accent)" }}>Состояние · {report.skin_age.score}</div>
                <div className="scale"><div className="fill" style={{ width: `${report.skin_age.score_percent}%` }} /></div>
                <p className="after-note">Оценка визуальная: смотрим тонус, плотность, свежесть, отёчность и собранность лица.</p>
              </div>
              <div className="grid-2">
                <div className="card">
                  <span className="label">Тип кожи</span>
                  <h3 className="card-title" style={{ marginTop: 8 }}>{report.skin_type.title}</h3>
                  <ul className="bullet">{textItems(report.skin_type.features).map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
                <div className="card warm">
                  <span className="label">Сильные стороны / старение</span>
                  <h3 className="card-title" style={{ marginTop: 8 }}>{report.face_aging.face_strengths}</h3>
                  <p><b>{report.face_aging.aging_type}</b></p>
                  <p>{report.face_aging.strong_base}</p>
                </div>
              </div>
            </div>
          </section>

          <section className="section">
            <div className="section-head"><span className="num">03</span><h2 className="section-title">Как это проявляется</h2></div>
            <div className="grid-2">
              <div className="card">
                <h3 className="card-title">Механика вашего типа</h3>
                <p>{report.face_aging.explanation}</p>
                <ul className="bullet">{textItems(report.face_aging.bullets, "Мягкая поддержка зон внимания.").map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
              <div className="card tinted">
                <h3 className="card-title">Что важно поддерживать</h3>
                <ul className="bullet">{textItems(report.skin_type.attention_points, "Лимфоток, шею и тонус нижней трети.").map((item) => <li key={item}>{item}</li>)}</ul>
                <p className="editor-note">{report.skin_type.recommendations}</p>
              </div>
            </div>
          </section>

          <section className="section">
            <div className="section-head"><span className="num">04</span><h2 className="section-title">Карта зон лица</h2></div>
            <div className="map-wrap">
              <CompactZoneMap report={report} />
              <div className="zone-list">
                {(report.zones || []).map((zone: any) => (
                  <article className="zone" key={`${zone.number}-${zone.label}`}>
                    <span className="zn">{zone.number}</span>
                    <div className="body">
                      <b>{zone.label}</b>
                      <div>{zone.short_comment}</div>
                      <div className="extra">{zone.recommended_focus}</div>
                    </div>
                    <span className={`status ${statusClass(zone.status)}`}>{zone.status_label}</span>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="section">
            <div className="section-head"><span className="num">05</span><h2 className="section-title">Почему это происходит</h2></div>
            {textIntro(report.causes) && <div className="story-lead"><span className="label">Логика вашего типа</span><p className="lead">{textIntro(report.causes)}</p></div>}
            <div className="cause-grid">
              {causes.map((item, index) => (
                <article className="cause" key={item}>
                  <span className="num">{String(index + 1).padStart(2, "0")}</span>
                  <h4>Фактор</h4>
                  <p>{item}</p>
                </article>
              ))}
            </div>
            {textOutro(report.causes) && <p className="editor-note">{textOutro(report.causes)}</p>}
          </section>

          <section className="section">
            <div className="editorial">
              <p className="quote">«Сильные стороны лица не надо исправлять. Их нужно раскрыть: через лимфу, шею, тонус и мягкую регулярность.»</p>
              <div className="strengths-grid">
                {textItems(report.strengths).map((item) => (
                  <article className="strength" key={item}>
                    <h4>{item}</h4>
                    <p>Это уже ресурс лица: на него можно опереться, чтобы результат выглядел естественно.</p>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="section">
            <div className="section-head"><span className="num">07</span><h2 className="section-title">Что даст фейсфитнес</h2></div>
            <div className="benefits">
              {benefits.map((item, index) => (
                <article className="benefit" key={item}>
                  <span className="bi">{index + 1}</span>
                  <div><h4>Визуальный эффект</h4><p>{item}</p></div>
                </article>
              ))}
            </div>
            {textOutro(report.benefits) && <div className="benefit-outro">{textOutro(report.benefits)}</div>}
          </section>

          <section className="section">
            <div className="section-head"><span className="num">08</span><h2 className="section-title">Прогноз по времени</h2></div>
            <div className="timeline">
              {(report.forecast || []).map((item: any) => (
                <div className="timeline-card" key={item.period}>
                  <div className="tl-period">{item.period}</div>
                  <div>{item.text}</div>
                </div>
              ))}
            </div>
          </section>

          {report.after_photo?.state !== "disabled" ? (
            <section className="section">
              <div className="section-head"><span className="num">09</span><h2 className="section-title">After-photo</h2></div>
              <div className="after-grid">
                <PhotoFrame asset={report.images.original_photo} label="Исходное фото" />
                <PhotoFrame asset={report.after_photo.state === "ready" ? report.images.after_photo : null} label="AI-визуализация" pendingText={report.after_photo.message} />
              </div>
              <p className="after-note">{report.after_photo.message} Визуализация не является гарантией результата.</p>
            </section>
          ) : null}

          <section className="section">
            <div className="cta-block">
              <div>
                <h3>Следующий шаг: персональная программа Bella Vladi</h3>
                <p>Получите программу, которая опирается на ваши зоны внимания и сильные стороны лица.</p>
              </div>
              <button className="btn" type="button" onClick={onCta} disabled={cta.isPending}>
                {cta.isPending ? "Открываю..." : report.cta.text}
                <ArrowRight size={16} />
              </button>
            </div>
          </section>

          <footer className="footer">
            <div className="brand">Bella Vladi</div>
            <div>{report.disclaimer}</div>
          </footer>
        </div>
      </main>
    </>
  );
}
