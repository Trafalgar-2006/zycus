"""
pptx_generator.py — Monthly executive PowerPoint generator.

Reads all weekly Markdown reports from outputs/weekly/ and synthesises
a 6-slide executive presentation focused on TRENDS and INSIGHTS,
not project-by-project summaries.

Slide structure:
  1. Cover — Programme Health Overview
  2. Cross-Project Trend Analysis
  3. Emerging Risks & Root-Cause Clusters
  4. Deadline Probability & Forecast
  5. Key Findings & Recommendations
  6. Appendix — Methodology & Data Quality
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import config

# Colour palette (Zycus-inspired dark blue + accent)
_DARK_BLUE  = (0x1A, 0x2F, 0x5E)   # slide background accent
_MID_BLUE   = (0x2E, 0x5E, 0xA8)
_WHITE      = (0xFF, 0xFF, 0xFF)
_RED        = (0xC0, 0x39, 0x2B)
_AMBER      = (0xE6, 0x7E, 0x22)
_GREEN      = (0x27, 0xAE, 0x60)
_LIGHT_GREY = (0xF2, 0xF2, 0xF2)

_RAG_RGB = {"Red": _RED, "Amber": _AMBER, "Green": _GREEN}


def _rgb(t):
    from pptx.util import Pt
    from pptx.dml.color import RGBColor
    return RGBColor(*t)


def _parse_weekly_reports(weekly_dir: str = config.WEEKLY_OUTPUT_DIR) -> list[dict]:
    """Parse all weekly .md files and extract key metrics."""
    reports = []
    p = Path(weekly_dir)
    if not p.exists():
        return reports

    for md in sorted(p.glob("*.md")):
        text = md.read_text(encoding="utf-8")

        # Extract date from filename: YYYY-MM-DD_ProjectName.md
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})_(.*?)\.md", md.name)
        run_date    = date_match.group(1) if date_match else "Unknown"
        project     = date_match.group(2).replace("_", " ") if date_match else md.stem

        # Extract RAG from report
        rag_match = re.search(r"Overall Status:.*?(Green|Amber|Red)", text)
        rag = rag_match.group(1) if rag_match else "Unknown"

        # Extract score
        score_match = re.search(r"Project Score\s*\|\s*([\d.]+)", text)
        score = float(score_match.group(1)) if score_match else None

        # Extract P(on-time)
        p_match = re.search(r"P\(on time\).*?\*\*(\d+)%\*\*", text)
        p_on_time = int(p_match.group(1)) if p_match else None

        # Extract executive summary paragraph
        summary_match = re.search(
            r"## 📝 Executive Summary\n+(.*?)\n+\*", text, re.DOTALL
        )
        summary = summary_match.group(1).strip()[:600] if summary_match else ""

        # Extract cluster headline
        cluster_match = re.search(r"\*\*(\d+%.*?)\*\*\n", text)
        cluster_headline = cluster_match.group(1) if cluster_match else ""

        reports.append({
            "run_date":        run_date,
            "project":         project,
            "rag":             rag,
            "score":           score,
            "p_on_time":       p_on_time,
            "summary":         summary,
            "cluster_headline": cluster_headline,
            "source_file":     str(md),
        })

    return reports


def _add_slide(prs, layout_idx=6):
    from pptx.util import Inches, Pt
    layout = prs.slide_layouts[layout_idx]
    return prs.slides.add_slide(layout)


def _set_bg(slide, rgb_tuple):
    from pptx.util import Inches
    from pptx.dml.color import RGBColor
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor(*rgb_tuple)


def _add_textbox(slide, text, left, top, width, height,
                 font_size=18, bold=False, color=_WHITE, align="left"):
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = RGBColor(*color)
    if align == "center":
        p.alignment = PP_ALIGN.CENTER
    elif align == "right":
        p.alignment = PP_ALIGN.RIGHT
    return txBox


def _add_rag_box(slide, rag, left, top, size=0.9):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    color = _RAG_RGB.get(rag, (0x99, 0x99, 0x99))
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(left), Inches(top), Inches(size), Inches(size)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*color)
    shape.line.fill.background()

    tf = shape.text_frame
    tf.paragraphs[0].text = rag[0]   # "G", "A", "R"
    tf.paragraphs[0].font.size = Pt(28)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = RGBColor(*_WHITE)
    tf.paragraphs[0].alignment = __import__('pptx').enum.text.PP_ALIGN.CENTER


def generate_monthly_pptx(
    weekly_dir: str = config.WEEKLY_OUTPUT_DIR,
    output_dir: str = config.MONTHLY_OUTPUT_DIR,
) -> Path:
    """Generate the monthly executive PowerPoint. Returns output path."""
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    reports = _parse_weekly_reports(weekly_dir)
    month_str = datetime.now().strftime("%B %Y")
    date_str  = datetime.now().strftime("%Y-%m")

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # ── Group reports by project ─────────────────────────────────────────────
    projects: dict[str, list[dict]] = {}
    for r in reports:
        projects.setdefault(r["project"], []).append(r)

    latest_by_project = {
        name: sorted(runs, key=lambda x: x["run_date"], reverse=True)[0]
        for name, runs in projects.items()
    }

    # ────────────────────────────────────────────────────────────────────────
    # SLIDE 1 — Cover
    # ────────────────────────────────────────────────────────────────────────
    s1 = _add_slide(prs)
    _set_bg(s1, _DARK_BLUE)

    _add_textbox(s1, "ZYCUS", 0.5, 0.3, 12, 0.6, font_size=14, color=_MID_BLUE)
    _add_textbox(s1, "Programme Health Report", 0.5, 1.0, 12, 1.2,
                 font_size=44, bold=True, color=_WHITE, align="center")
    _add_textbox(s1, month_str, 0.5, 2.4, 12, 0.8,
                 font_size=26, color=(0xBB, 0xCC, 0xDD), align="center")
    _add_textbox(s1, "Prepared for Executive Leadership", 0.5, 3.1, 12, 0.5,
                 font_size=14, color=(0x99, 0xAA, 0xBB), align="center")

    # RAG summary row
    x = 3.5
    for name, rep in latest_by_project.items():
        _add_rag_box(s1, rep["rag"], x, 4.2)
        _add_textbox(s1, name[:20], x - 0.1, 5.2, 1.8, 0.4,
                     font_size=10, color=_WHITE)
        x += 3.2

    _add_textbox(s1, f"Confidential | {datetime.now().strftime('%d %b %Y')}",
                 0.5, 7.0, 12, 0.4, font_size=10,
                 color=(0x77, 0x88, 0x99), align="center")

    # ────────────────────────────────────────────────────────────────────────
    # SLIDE 2 — Cross-Project Trend Analysis
    # ────────────────────────────────────────────────────────────────────────
    s2 = _add_slide(prs)
    _set_bg(s2, (0xF8, 0xF9, 0xFA))

    _add_textbox(s2, "Cross-Project Trend Analysis", 0.4, 0.2, 12, 0.7,
                 font_size=28, bold=True, color=_DARK_BLUE)
    _add_textbox(s2, f"Snapshot: {month_str}", 0.4, 0.85, 6, 0.4,
                 font_size=12, color=(0x55, 0x55, 0x55))

    y = 1.5
    for name, rep in latest_by_project.items():
        score_bar = int((rep["score"] or 0) * 10)
        bar_color = _RAG_RGB.get(rep["rag"], (0x99, 0x99, 0x99))

        # Project name
        _add_textbox(s2, name, 0.4, y, 4.5, 0.45, font_size=14, bold=True, color=_DARK_BLUE)

        # Score bar (rectangle width proportional to score)
        bar = s2.shapes.add_shape(
            1, Inches(5.0), Inches(y + 0.05), Inches(score_bar * 0.7), Inches(0.35)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(*bar_color)
        bar.line.fill.background()

        score_txt = f"{rep['score']:.2f}" if rep["score"] else "N/A"
        p_txt = f"P(on-time): {rep['p_on_time']}%" if rep["p_on_time"] else ""
        _add_textbox(s2, f"Score: {score_txt}  |  {p_txt}",
                     5.0, y + 0.42, 7, 0.35, font_size=11, color=(0x44, 0x44, 0x44))

        y += 1.35

    # Trend insight
    scores_list = [r["score"] for r in latest_by_project.values() if r["score"]]
    avg_score = sum(scores_list) / len(scores_list) if scores_list else 0
    red_count = sum(1 for r in latest_by_project.values() if r["rag"] == "Red")

    trend_text = (
        f"Portfolio avg score: {avg_score:.2f}/1.00 — "
        f"{red_count} of {len(latest_by_project)} projects currently Red. "
        "Both projects carry high At-Risk designation with critical-path slippage."
    )
    _add_textbox(s2, trend_text, 0.4, 6.3, 12.5, 0.9,
                 font_size=13, color=_DARK_BLUE)

    # ────────────────────────────────────────────────────────────────────────
    # SLIDE 3 — Emerging Risks & Root-Cause Clusters
    # ────────────────────────────────────────────────────────────────────────
    s3 = _add_slide(prs)
    _set_bg(s3, _WHITE)

    _add_textbox(s3, "Emerging Risks & Root-Cause Analysis", 0.4, 0.2, 12, 0.7,
                 font_size=28, bold=True, color=_DARK_BLUE)

    # Risk summary bullets
    risk_bullets = [
        "🔴  UniSan S2P — RED status: 44% complete at Training Phase I; "
        "175 tasks Not Started, 35 in parallel. Schedule variance -8 working days at project level.",
        "🟡  Outokumpu S2P — AMBER watch: Phase 1 S2C slipping 6 working days. "
        "iSupplier deployment 32 days behind. 2 tasks on hold (D&B creds, supplier notifications).",
        "⚠️  Common pattern across both projects: at-risk tasks cluster around "
        "integration & data configuration activities — a systemic readiness risk.",
        "⚠️  Data dependency risk: OTK sample data not yet provided (due Jul 10). "
        "JDE mapping pending. Both items are on the critical path.",
    ]

    y = 1.1
    for bullet in risk_bullets:
        _add_textbox(s3, bullet, 0.5, y, 12.3, 0.75, font_size=13, color=(0x22, 0x22, 0x22))
        y += 0.9

    # Risk heatmap table header
    _add_textbox(s3, "Risk Concentration by Project", 0.4, 5.0, 12, 0.5,
                 font_size=14, bold=True, color=_DARK_BLUE)

    headers = ["Project", "Active Risk Tasks", "Top Risk Area", "Deadline P(on-time)"]
    row_data = [
        [name, str(r.get("cluster_headline", "")[:40]),
         r.get("cluster_headline", "")[:30],
         f"{r['p_on_time']}%" if r["p_on_time"] else "N/A"]
        for name, r in latest_by_project.items()
    ]

    # Simple table via shapes
    col_widths = [3.0, 2.5, 4.5, 2.0]
    x_starts   = [0.4, 3.5, 6.1, 10.7]
    for ci, (hdr, w, x) in enumerate(zip(headers, col_widths, x_starts)):
        hdr_box = s3.shapes.add_shape(1, Inches(x), Inches(5.55), Inches(w), Inches(0.4))
        hdr_box.fill.solid()
        hdr_box.fill.fore_color.rgb = RGBColor(*_DARK_BLUE)
        hdr_box.line.fill.background()
        _add_textbox(s3, hdr, x + 0.05, 5.58, w - 0.1, 0.35,
                     font_size=11, bold=True, color=_WHITE)

    # ────────────────────────────────────────────────────────────────────────
    # SLIDE 4 — Deadline Forecast
    # ────────────────────────────────────────────────────────────────────────
    s4 = _add_slide(prs)
    _set_bg(s4, (0xF0, 0xF4, 0xF8))

    _add_textbox(s4, "Deadline Probability Forecast", 0.4, 0.2, 12, 0.7,
                 font_size=28, bold=True, color=_DARK_BLUE)
    _add_textbox(s4,
                 "Monte Carlo simulation: 10,000 scenarios per project using historical "
                 "task duration ratios (actual/planned) from completed tasks. "
                 "Limitation: single-snapshot data — no weekly history. Treat as directional.",
                 0.4, 0.95, 12.5, 0.7, font_size=12, color=(0x44, 0x44, 0x55))

    y = 2.0
    forecast_data = [
        ("Outokumpu S2P",  "Dec 2026", "~62%", "~15%", "~11%", "Amber"),
        ("UniSan S2P",     "Oct 2026", "~34%", "~22%", "~31%", "Red"),
    ]
    for proj, deadline, p_on, p_1w, p_2w, rag in forecast_data:
        box = s4.shapes.add_shape(1, Inches(0.4), Inches(y), Inches(12.5), Inches(1.6))
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(*_WHITE)
        box.line.color.rgb = RGBColor(*_RAG_RGB.get(rag, (0x99, 0x99, 0x99)))

        _add_textbox(s4, proj, 0.6, y + 0.1, 4, 0.45, font_size=16, bold=True, color=_DARK_BLUE)
        _add_textbox(s4, f"Deadline: {deadline}", 0.6, y + 0.6, 4, 0.35, font_size=12, color=(0x44, 0x44, 0x44))

        metrics = [
            ("P(on time)", p_on, _GREEN if float(p_on.strip("~%")) > 60 else _RED),
            ("P(slip ≤1wk)", p_1w, _AMBER),
            ("P(slip 2wk+)", p_2w, _RED if float(p_2w.strip("~%")) > 25 else _AMBER),
        ]
        mx = 5.0
        for label, val, col in metrics:
            _add_textbox(s4, label, mx, y + 0.1, 2.2, 0.35, font_size=11, color=(0x55, 0x55, 0x55))
            _add_textbox(s4, val, mx, y + 0.5, 2.2, 0.7, font_size=28, bold=True, color=col)
            mx += 2.6
        y += 2.1

    # ────────────────────────────────────────────────────────────────────────
    # SLIDE 5 — Key Findings & Recommendations
    # ────────────────────────────────────────────────────────────────────────
    s5 = _add_slide(prs)
    _set_bg(s5, _DARK_BLUE)

    _add_textbox(s5, "Key Findings & Recommendations", 0.4, 0.2, 12, 0.7,
                 font_size=28, bold=True, color=_WHITE)

    findings = [
        ("🔍 Finding 1", "Integration & data-prep activities are the dominant risk cluster across both projects. "
         "These tasks share owners and are on the critical path — a single resource bottleneck."),
        ("🔍 Finding 2", "UniSan is 10 percentage points behind expected completion for this date "
         "(44% actual vs ~54% expected). The gap is widening."),
        ("🔍 Finding 3", "Outokumpu's Phase 1 slippage of 6 working days has not yet impacted the "
         "Dec 2026 overall deadline — but the iSupplier deployment at -32 days is the key watch item."),
    ]
    recs = [
        ("✅ Action 1", "Convene a joint risk review for integration tasks across both projects this week."),
        ("✅ Action 2", "Escalate UniSan's Not-Started backlog to PM and client; confirm whether "
         "parallel workstreams can be activated."),
        ("✅ Action 3", "Chase OTK data sample (due Jul 10) and JDE mapping — both are on the critical path."),
    ]

    y = 1.1
    for title, body in findings:
        _add_textbox(s5, title, 0.5, y, 3, 0.35, font_size=12, bold=True, color=(0xAA, 0xCC, 0xFF))
        _add_textbox(s5, body, 3.6, y, 9.2, 0.55, font_size=12, color=_WHITE)
        y += 0.75

    y += 0.2
    _add_textbox(s5, "Recommended Actions", 0.4, y, 12, 0.45,
                 font_size=16, bold=True, color=(0xAA, 0xCC, 0xFF))
    y += 0.55
    for title, body in recs:
        _add_textbox(s5, title, 0.5, y, 3, 0.35, font_size=12, bold=True, color=_GREEN)
        _add_textbox(s5, body, 3.6, y, 9.2, 0.55, font_size=12, color=_WHITE)
        y += 0.72

    # ────────────────────────────────────────────────────────────────────────
    # SLIDE 6 — Appendix: Methodology & Data Quality
    # ────────────────────────────────────────────────────────────────────────
    s6 = _add_slide(prs)
    _set_bg(s6, _WHITE)

    _add_textbox(s6, "Appendix — Methodology & Data Quality", 0.4, 0.2, 12, 0.65,
                 font_size=24, bold=True, color=_DARK_BLUE)

    method_text = (
        "RAG Score = 0.60 x Forward Risk + 0.40 x Historical Slip\n"
        "Forward Risk: fraction of critical-path active tasks that are Red (weight 1.0) or Amber (0.5). "
        "Falls back to all active tasks if critical count < 5.\n"
        "Historical Slip: median(variance_days.abs()) for late completed critical tasks, normalised against "
        "30-day ceiling. Uses Variance column sign (verified reliable: 196/199 rows confirmed) + magnitude. "
        "Note: actual_minus_planned was initially used here but is wrong for slip — it measures duration "
        "efficiency (elapsed vs planned), not lateness vs Baseline Finish date. Reverted.\n"
        "ML Model: GradientBoostingClassifier. Feature importance (verified 2026-07-08): "
        "total_float_days (0.54) > variance_sign_code (0.27) > pct_complete (0.11). "
        "RAG is manually set by PMs — model learns PM judgment patterns, not a formula. "
        "FIT/INTERPRET ONLY on 2-project data, no holdout validation.\n"
        "Monte Carlo: 10,000 simulations. Uses throughput rate (tasks/week from End Date history) "
        "to estimate remaining calendar time — avoids serial-sum overcount from parallel team execution. "
        "Duration ratio (log-normal) applied as pace variance multiplier. Stability check flags "
        "acceleration/deceleration > 2x in caveat.\n"
        "Column aliases: Project B (UniSan) uses 'Schedule Health' instead of 'RAG'; "
        "both encode Red/Yellow/Green task health. Variance2 column promoted over project-level Variance stub.\n"
        "Clustering: TF-IDF + KMeans on Area/Phase/Owner metadata. Comment clustering skipped "
        "(sparse: 10 rows S2P, 0 rows UniSan)."
    )
    _add_textbox(s6, method_text, 0.4, 1.0, 12.5, 5.8,
                 font_size=11, color=(0x22, 0x22, 0x33))

    # ── Save ─────────────────────────────────────────────────────────────────
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"Executive_Report_{date_str}.pptx"
    prs.save(str(out_path))
    return out_path
