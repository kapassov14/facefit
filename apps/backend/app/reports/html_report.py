from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from jinja2 import Template

from app.ai.prompts import DISCLAIMER


STATUS_LABELS = {
    "good": "Все хорошо",
    "attention": "Зона внимания",
    "priority": "Приоритет",
    "green": "Все хорошо",
    "yellow": "Зона внимания",
    "red": "Приоритет",
}


REPORT_TEMPLATE = Template(
    """
<article class="bella-report-v2">
  <section class="report-cover">
    <p class="eyebrow">Bella Vladi Face Protocol</p>
    <h1>{{ user_name }}</h1>
    <p class="lead">{{ summary }}</p>
    <p class="disclaimer">{{ disclaimer }}</p>
  </section>

  <section class="report-grid three">
    <div class="report-card">
      <span class="section-number">1</span>
      <h2>Биологический возраст кожи</h2>
      <strong>{{ skin_age.visual_age or skin_age.estimated_range }}</strong>
      <p>{{ skin_age.explanation }}</p>
    </div>
    <div class="report-card">
      <span class="section-number green">2</span>
      <h2>Тип кожи</h2>
      <strong>{{ skin_type.type }}</strong>
      <ul>{% for item in skin_type.features %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
    <div class="report-card">
      <span class="section-number amber">3</span>
      <h2>Сильные стороны и тип старения</h2>
      <strong>{{ face_type.face_type }} · {{ face_type.aging_type }}</strong>
      <p>{{ face_type.explanation }}</p>
    </div>
  </section>

  <section class="report-card">
    <span class="section-number dark">4</span>
    <h2>Карта зон лица</h2>
    <div class="legend">
      <span><i class="dot green"></i>Все хорошо</span>
      <span><i class="dot yellow"></i>Зона внимания</span>
      <span><i class="dot red"></i>Приоритет</span>
    </div>
    <div class="zones-table">
      {% for zone in zones %}
      <div class="zone-row {{ zone.color }}">
        <div class="zone-number">{{ zone.number }}</div>
        <div>
          <h3>{{ zone.name }}</h3>
          <p>{{ zone.short_comment }}</p>
          <small>{{ zone.reason }}</small>
        </div>
        <b>{{ zone.status_label }}</b>
      </div>
      {% endfor %}
    </div>
  </section>

  <section class="report-grid two">
    <div class="report-card">
      <span class="section-number">5</span>
      <h2>Почему это происходит</h2>
      <ul>{% for item in causes %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
    <div class="report-card">
      <span class="section-number green">6</span>
      <h2>Ваши сильные стороны</h2>
      <ul>{% for item in strengths %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
  </section>

  <section class="report-grid two">
    <div class="report-card">
      <span class="section-number amber">7</span>
      <h2>Что даст фейсфитнес</h2>
      <ul>{% for item in benefits %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
    <div class="report-card">
      <span class="section-number dark">8</span>
      <h2>Прогноз по времени</h2>
      <div class="timeline">
        <p><b>7-14 дней</b>{{ forecast.first_changes }}</p>
        <p><b>4-6 недель</b>{{ forecast.visible_changes }}</p>
        <p><b>8-12 недель</b>{{ forecast.stable_result }}</p>
      </div>
    </div>
  </section>
</article>
"""
)


def _zone_status_label(zone: dict[str, Any]) -> str:
    return STATUS_LABELS.get(zone.get("status")) or STATUS_LABELS.get(zone.get("color")) or "Зона внимания"


def build_report_json(user_name: str, analysis_json: dict[str, Any], selected_problems: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    zones = analysis_json.get("zones", [])
    priority_zones = [
        zone.get("name")
        for zone in zones
        if zone.get("status") == "priority" or zone.get("color") == "red"
    ] or [zone.get("name") for zone in zones[:3]]
    return {
        "user_name": user_name,
        "date": datetime.now().strftime("%d.%m.%Y"),
        "summary": analysis_json.get("summary", ""),
        "main_problem": selected_problems[0] if selected_problems else (priority_zones[0] if priority_zones else "Тонус и свежесть лица"),
        "main_potential": ", ".join(analysis_json.get("strengths", [])[:2]) or "шея и лимфоток как первый рычаг результата",
        "priority_zones": priority_zones,
        "analysis": analysis_json,
        "extra": extra or {},
        "disclaimer": DISCLAIMER,
    }


def render_report_html(report_json: dict[str, Any]) -> str:
    analysis = report_json.get("analysis", {})
    zones = []
    for zone in analysis.get("zones", []):
        item = dict(zone)
        item["status_label"] = _zone_status_label(zone)
        zones.append(item)

    return REPORT_TEMPLATE.render(
        user_name=escape(report_json.get("user_name", "Гость")),
        date=report_json.get("date", ""),
        disclaimer=report_json.get("disclaimer", DISCLAIMER),
        summary=analysis.get("summary", ""),
        priority_zones=report_json.get("priority_zones", []),
        skin_age=analysis.get("skin_visual_age", {}),
        skin_type=analysis.get("skin_type", {}),
        face_type=analysis.get("face_type_and_aging_type", {}),
        zones=zones,
        causes=analysis.get("causes", []),
        strengths=analysis.get("strengths", []),
        benefits=analysis.get("facefitness_benefits", []),
        forecast=analysis.get("time_forecast", {}),
    )


def build_face_protocol_html(
    analysis_json: dict[str, Any],
    user_name: str = "Гость",
    selected_problems: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    return render_report_html(build_report_json(user_name, analysis_json, selected_problems or [], extra or {"source": "backend_template"}))


buildFaceProtocolHtml = build_face_protocol_html
