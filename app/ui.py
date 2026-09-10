from __future__ import annotations

import html
from typing import Callable, Any

import gradio as gr

from app.database import get_all_meetings, search_meetings, get_tasks
from app.visual_analytics_service import validate_visual_insights


# =========================================================
# BASIC PRESENTATION HELPERS
# =========================================================


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def display_value(value: Any) -> str:
    if value in (None, "", "null"):
        return "Not specified"
    return str(value)


# =========================================================
# SPEAKER PRESENTATION
# =========================================================


def build_speaker_setup_html(speakers: dict) -> str:
    count = len(speakers)

    if count == 0:
        return """
        <div class="empty-state">
            No speakers could be detected.
        </div>
        """

    cards = []

    for index, (_, lines) in enumerate(speakers.items(), 1):
        snippets = "".join(
            f"""
            <div class="speaker-snippet">
                “{esc(line)}”
            </div>
            """
            for line in lines
        )

        cards.append(
            f"""
            <div class="topic-card">
                <div class="topic-number">SPEAKER {index}</div>
                <h3>Speaker {index}</h3>
                <div class="section-label">SAMPLE UTTERANCES</div>
                {snippets}
            </div>
            """
        )

    return f"""
    <div class="summary-card">
        <div class="section-label">SPEAKER DETECTION</div>
        <p>
            MeetingOS detected <strong>{count}</strong>
            speaker{"s" if count != 1 else ""}.
            Is this correct?
        </p>
    </div>
    <div class="topic-grid">{"".join(cards)}</div>
    """


# =========================================================
# REPORT PRESENTATION
# =========================================================


def render_evidence(evidence) -> str:
    if not evidence:
        return ""

    blocks = []
    for item in evidence:
        if not isinstance(item, dict):
            continue

        timestamp = esc(item.get("timestamp", ""))
        text = esc(item.get("text", ""))

        if timestamp or text:
            blocks.append(
                f"""
                <div class="evidence">
                    <span class="evidence-label">Evidence</span>
                    <span class="evidence-time">{timestamp}</span>
                    <span class="evidence-text">{text}</span>
                </div>
                """
            )

    return "".join(blocks)


def render_topics(topics) -> str:
    if not topics:
        return ""

    cards = []

    for index, topic in enumerate(topics, 1):
        if not isinstance(topic, dict):
            continue

        name = esc(topic.get("name", f"Topic {index}"))
        summary = esc(topic.get("summary", ""))
        outcome = esc(topic.get("outcome", ""))
        key_points = topic.get("key_points", []) or []
        evidence = topic.get("evidence", []) or []

        points_html = ""
        if key_points:
            points_html = "<ul>" + "".join(
                f"<li>{esc(point)}</li>" for point in key_points
            ) + "</ul>"

        outcome_html = (
            f"<div class='outcome'><strong>Outcome:</strong> {outcome}</div>"
            if outcome else ""
        )

        cards.append(
            f"""
            <div class="topic-card">
                <div class="topic-number">TOPIC {index}</div>
                <h3>{name}</h3>
                <p class="topic-summary">{summary}</p>
                {points_html}
                {outcome_html}
                {render_evidence(evidence)}
            </div>
            """
        )

    return "".join(cards)


def _simple_cards(items, body_key: str, css_class: str, icon: str) -> str:
    cards = []

    for item in items or []:
        if isinstance(item, dict):
            text = esc(item.get(body_key, ""))
            evidence = render_evidence(item.get("evidence", []))
        else:
            text = esc(item)
            evidence = ""

        cards.append(
            f"""
            <div class="{css_class}">
                <div class="icon">{icon}</div>
                <div>
                    <div class="card-main">{text}</div>
                    {evidence}
                </div>
            </div>
            """
        )

    return "".join(cards)


def render_decisions(decisions) -> str:
    if not decisions:
        return ""
    cards = []
    for decision in decisions:
        if isinstance(decision, dict):
            text = esc(decision.get("decision", ""))
            evidence = render_evidence(decision.get("evidence", []))
        else:
            text = esc(decision)
            evidence = ""
        cards.append(
            f"""
            <div class="decision-card">
                <div class="icon decision-icon">✓</div>
                <div>
                    <div class="card-main">{text}</div>
                    {evidence}
                </div>
            </div>
            """
        )
    return "".join(cards)


def render_actions(actions) -> str:
    if not actions:
        return ""

    cards = []
    for action in actions:
        if isinstance(action, dict):
            task = esc(action.get("task", ""))
            owner = display_value(action.get("owner"))
            deadline = display_value(action.get("deadline"))
            evidence = render_evidence(action.get("evidence", []))
        else:
            task = esc(action)
            owner = "Not specified"
            deadline = "Not specified"
            evidence = ""

        cards.append(
            f"""
            <div class="action-card">
                <div class="icon action-icon">→</div>
                <div class="action-body">
                    <div class="action-task">{task}</div>
                    <div class="action-meta">
                        <span><strong>Owner</strong>{esc(owner)}</span>
                        <span><strong>Deadline</strong>{esc(deadline)}</span>
                    </div>
                    {evidence}
                </div>
            </div>
            """
        )

    return "".join(cards)


def render_risks(risks) -> str:
    if not risks:
        return ""

    cards = []
    for risk in risks:
        if isinstance(risk, dict):
            text = esc(risk.get("risk", ""))
            evidence = render_evidence(risk.get("evidence", []))
        else:
            text = esc(risk)
            evidence = ""
        cards.append(
            f"""
            <div class="risk-card">
                <div class="icon risk-icon">!</div>
                <div>
                    <div class="card-main">{text}</div>
                    {evidence}
                </div>
            </div>
            """
        )
    return "".join(cards)


def render_questions(questions) -> str:
    if not questions:
        return ""

    cards = []
    for question in questions:
        if isinstance(question, dict):
            text = esc(question.get("question", ""))
            evidence = render_evidence(question.get("evidence", []))
        else:
            text = esc(question)
            evidence = ""
        cards.append(
            f"""
            <div class="question-card">
                <div class="icon question-icon">?</div>
                <div>
                    <div class="card-main">{text}</div>
                    {evidence}
                </div>
            </div>
            """
        )
    return "".join(cards)


def render_contradictions(contradictions) -> str:
    if not contradictions:
        return ""

    cards = []
    for contradiction in contradictions:
        if isinstance(contradiction, dict):
            text = esc(contradiction.get("issue", ""))
            evidence = render_evidence(contradiction.get("evidence", []))
        else:
            text = esc(contradiction)
            evidence = ""
        cards.append(
            f"""
            <div class="contradiction-card">
                <div class="icon contradiction-icon">↔</div>
                <div>
                    <div class="card-main">{text}</div>
                    {evidence}
                </div>
            </div>
            """
        )
    return "".join(cards)


def optional_section(title: str, content: str, content_class: str = "stack") -> str:
    if not content:
        return ""
    return f"""
    <section>
        <div class="section-heading">{esc(title)}</div>
        <div class="{content_class}">{content}</div>
    </section>
    """


def build_optional_report_sections(
    topics_html: str,
    decisions_html: str,
    actions_html: str,
    risks_html: str,
    questions_html: str,
    contradictions_html: str,
) -> str:
    sections = []

    # Put the most decision-useful information first, then supporting context.
    if decisions_html:
        sections.append(optional_section("Decisions Made", decisions_html))
    if actions_html:
        sections.append(optional_section("Action Items", actions_html))
    if topics_html:
        sections.append(optional_section("Discussion Topics", topics_html, "topic-grid"))

    # Keep risk/question sections in the main report flow. A two-column layout
    # creates awkward empty space when one category has fewer items than the other.
    if risks_html:
        sections.append(optional_section("Risks & Concerns", risks_html))
    if questions_html:
        sections.append(optional_section("Unresolved Questions", questions_html))

    if contradictions_html:
        sections.append(
            optional_section(
                "Contradictions & Inconsistencies",
                contradictions_html,
            )
        )

    return "".join(sections)


def render_meeting_report(topic: str, intelligence: dict, saved: bool = False) -> str:
    summary = esc(
        intelligence.get(
            "executive_summary",
            "No executive summary identified.",
        )
    )

    topics_html = render_topics(intelligence.get("topics", []))
    decisions_html = render_decisions(intelligence.get("decisions", []))
    actions_html = render_actions(intelligence.get("action_items", []))
    risks_html = render_risks(intelligence.get("risks_and_concerns", []))
    questions_html = render_questions(intelligence.get("unresolved_questions", []))
    contradictions_html = render_contradictions(intelligence.get("contradictions", []))

    report_sections = build_optional_report_sections(
        topics_html,
        decisions_html,
        actions_html,
        risks_html,
        questions_html,
        contradictions_html,
    )

    eyebrow = "SAVED MEETING" if saved else "MEETING INTELLIGENCE"
    description = "Loaded from MeetingOS history." if saved else "Structured intelligence extracted from the meeting."

    return f"""
    <div class="report">
        <div class="hero-section">
            <div class="eyebrow">{eyebrow}</div>
            <h1>{esc(topic)}</h1>
            <p class="hero-description">{description}</p>
        </div>

        <div class="summary-card">
            <div class="section-label">EXECUTIVE SUMMARY</div>
            <p>{summary}</p>
        </div>

        {report_sections}
    </div>
    """


def render_meeting_metrics(analytics: dict) -> str:
    return f"""
    <div class="analytics-panel">
        <div class="metric">
            <div class="metric-value">{analytics.get("duration_minutes", 0):.2f}</div>
            <div class="metric-label">MINUTES</div>
        </div>
        <div class="metric">
            <div class="metric-value">{analytics.get("word_count", 0):,}</div>
            <div class="metric-label">WORDS</div>
        </div>
        <div class="metric">
            <div class="metric-value">{analytics.get("segment_count", 0)}</div>
            <div class="metric-label">SEGMENTS</div>
        </div>
    </div>
    """


# =========================================================
# VISUAL ANALYTICS PRESENTATION
# =========================================================


def _format_visual_number(value) -> str:
    value = float(value)
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{int(value):,}" if value.is_integer() else f"{value:,.2f}"


def _render_visual_evidence(evidence) -> str:
    blocks = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        text = esc(item.get("text") or "")
        timestamp = esc(item.get("timestamp") or "")
        if text:
            prefix = f"<strong>{timestamp}</strong> " if timestamp else ""
            blocks.append(f'<div class="visual-evidence">{prefix}{text}</div>')
    return "".join(blocks)


def render_visual_insight(insight: dict) -> str:
    title = esc(insight.get("title") or insight.get("metric") or "Quantitative Insight")
    metric = esc(insight.get("metric") or "Metric")
    unit = esc(insight.get("unit") or "")
    trend = esc(insight.get("trend") or "")
    chart_type = insight.get("chart_type", "kpi")
    data = insight.get("data", [])

    if not data:
        return ""

    if chart_type == "kpi":
        point = data[-1]
        suffix = f" {unit}" if unit else ""
        trend_html = f'<div class="visual-trend">{trend}</div>' if trend else ""
        return f"""
        <div class="visual-card kpi-card">
            <div class="section-label">QUANTITATIVE INSIGHT</div>
            <h3>{title}</h3>
            <div class="visual-kpi-value">{esc(_format_visual_number(point["value"]))}<span>{esc(suffix)}</span></div>
            <div class="visual-kpi-label">{esc(point["label"])} • {metric}</div>
            {trend_html}
            {_render_visual_evidence(insight.get("evidence", []))}
        </div>
        """

    width, height = 640, 280
    left, right, top, bottom = 48, 24, 26, 48
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [float(item["value"]) for item in data]
    min_v, max_v = min(values), max(values)

    if chart_type == "donut":
        total = sum(max(v, 0) for v in values) or 1
        cx, cy, radius, thickness = 150, 140, 62, 28
        circumference = 2 * 3.1415926535 * radius
        colors = ["#77a6f7", "#7fcaa8", "#e6b567", "#b28be3", "#df8f8f", "#73b9c7"]
        offset = 0
        segments = []
        for i, value in enumerate(values):
            dash = max(value, 0) / total * circumference
            segments.append(
                f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{colors[i % len(colors)]}" stroke-width="{thickness}" stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
            )
            offset += dash
        legend = []
        for i, point in enumerate(data):
            pct = max(point["value"], 0) / total * 100
            legend.append(
                f'<div class="legend-row"><span class="legend-dot" style="background:{colors[i % len(colors)]}"></span><span>{esc(point["label"])}</span><strong>{pct:.1f}%</strong></div>'
            )
        chart = (
            f'<svg viewBox="0 0 {width} {height}">'
            f'{"".join(segments)}'
            f'<text x="{cx}" y="{cy-2}" text-anchor="middle" class="donut-total">{esc(_format_visual_number(total))}</text>'
            f'<text x="{cx}" y="{cy+18}" text-anchor="middle" class="donut-unit">{unit}</text>'
            f'</svg>'
        )
        chart += '<div class="legend">' + "".join(legend) + "</div>"

    elif chart_type == "line":
        span = max(max_v - min_v, 1.0)
        points = []
        for i, point in enumerate(data):
            x = left + plot_w * i / max(len(data) - 1, 1)
            y = top + (max_v - point["value"]) / span * plot_h
            points.append((x, y, point))
        path = " L ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
        circles = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="line-point"/>'
            for x, y, _ in points
        )
        values_html = "".join(
            f'<text x="{x:.1f}" y="{y-10:.1f}" text-anchor="middle" class="point-label">{esc(_format_visual_number(point["value"]))}</text>'
            for x, y, point in points
        )
        labels = "".join(
            f'<text x="{x:.1f}" y="{height-15}" text-anchor="middle" class="axis-label">{esc(point["label"])}</text>'
            for x, y, point in points
        )
        chart = (
            f'<svg viewBox="0 0 {width} {height}">'
            f'<path d="M {path}" class="line-path"/>'
            f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" class="axis"/>'
            f'{circles}{values_html}{labels}</svg>'
        )

    else:
        baseline = min(0, min_v)
        scale = max(max_v - baseline, 1.0)
        gap = 12
        bar_w = (plot_w - gap * (len(data) - 1)) / max(len(data), 1)
        bars, labels = [], []
        for i, point in enumerate(data):
            x = left + i * (bar_w + gap)
            h = max(4, (point["value"] - baseline) / scale * plot_h)
            y = top + plot_h - h
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="6" class="bar-shape"/>'
            )
            bars.append(
                f'<text x="{x+bar_w/2:.1f}" y="{y-8:.1f}" text-anchor="middle" class="point-label">{esc(_format_visual_number(point["value"]))}</text>'
            )
            labels.append(
                f'<text x="{x+bar_w/2:.1f}" y="{height-15}" text-anchor="middle" class="axis-label">{esc(point["label"])}</text>'
            )
        chart = (
            f'<svg viewBox="0 0 {width} {height}">'
            f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" class="axis"/>'
            f'{"".join(bars)}{"".join(labels)}</svg>'
        )

    trend_html = f'<div class="visual-trend">{trend}</div>' if trend else ""

    return f"""
    <div class="visual-card">
        <div class="section-label">QUANTITATIVE INSIGHT</div>
        <h3>{title}</h3>
        <div class="visual-subtitle">{metric}{" • " + unit if unit else ""}</div>
        <div class="visual-chart">{chart}</div>
        {trend_html}
        {_render_visual_evidence(insight.get("evidence", []))}
    </div>
    """


def build_visual_analytics_html(insights) -> str:
    rendered = "".join(render_visual_insight(item) for item in insights or [])
    if not rendered:
        return ""
    return f"""
    <section class="visual-insights-section">
        <div class="section-heading">Visual Insights</div>
        <div class="visual-analytics-grid">{rendered}</div>
    </section>
    """


# =========================================================
# WORKSPACE PRESENTATION
# =========================================================


def _meeting_choices(meetings):
    choices = []
    for meeting in meetings:
        duration = meeting["duration_seconds"] or 0
        label = (
            f'{meeting["topic"]} • {meeting["created_at"]} '
            f'• {duration / 60:.1f} min'
        )
        choices.append((label, meeting["id"]))
    return choices


def build_history_choices():
    return _meeting_choices(get_all_meetings())


def build_search_choices(query):
    return _meeting_choices(search_meetings(query))


def build_task_choices(status_filter="All"):
    if status_filter == "All":
        tasks = get_tasks()
    else:
        tasks = get_tasks(status=status_filter)

    choices = []
    for task in tasks:
        owner = task.get("owner") or "Unassigned"
        deadline = task.get("deadline") or "No deadline"
        meeting = task.get("meeting_topic") or "Unknown meeting"
        label = (
            f'{task["task"]} • {owner} • {deadline} '
            f'• {meeting} • {task["status"]}'
        )
        choices.append((label, task["id"]))

    return choices


def build_workspace_analytics_html(data: dict) -> str:
    recent = data.get("recent_meetings", [])
    max_duration = max(
        [(meeting["duration_seconds"] or 0) for meeting in recent] or [1]
    )

    duration_rows = []
    for meeting in recent:
        duration = meeting["duration_seconds"] or 0
        width = duration / max_duration * 100 if max_duration else 0
        label = esc(meeting["topic"])
        duration_rows.append(
            f'<div class="bar-row"><span title="{label}">{label[:26]}</span><div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div><strong>{duration / 60:.1f}m</strong></div>'
        )

    max_tasks = max(data.get("total_tasks", 0), 1)

    return f"""
    <div class="workspace-analytics">
        <div class="workspace-metric"><div class="metric-value">{data.get("meeting_count", 0)}</div><div class="metric-label">MEETINGS</div></div>
        <div class="workspace-metric"><div class="metric-value">{data.get("total_minutes", 0):.1f}</div><div class="metric-label">TOTAL MINUTES</div></div>
        <div class="workspace-metric"><div class="metric-value">{data.get("average_duration_minutes", 0):.1f}</div><div class="metric-label">AVG DURATION</div></div>
        <div class="workspace-metric"><div class="metric-value">{data.get("total_tasks", 0)}</div><div class="metric-label">TASKS</div></div>
        <div class="workspace-metric"><div class="metric-value">{data.get("completed_tasks", 0)}</div><div class="metric-label">COMPLETED</div></div>
        <div class="workspace-metric"><div class="metric-value">{data.get("completion_rate", 0):.0f}%</div><div class="metric-label">TASK COMPLETION</div></div>
    </div>
    <div class="analytics-subheading">Task status</div>
    <div class="task-bars">
        <div class="bar-row"><span>Pending</span><div class="bar-track"><div class="bar-fill" style="width:{data.get("pending_tasks", 0) / max_tasks * 100:.1f}%"></div></div><strong>{data.get("pending_tasks", 0)}</strong></div>
        <div class="bar-row"><span>In Progress</span><div class="bar-track"><div class="bar-fill" style="width:{data.get("in_progress_tasks", 0) / max_tasks * 100:.1f}%"></div></div><strong>{data.get("in_progress_tasks", 0)}</strong></div>
        <div class="bar-row"><span>Completed</span><div class="bar-track"><div class="bar-fill" style="width:{data.get("completed_tasks_count", 0) / max_tasks * 100:.1f}%"></div></div><strong>{data.get("completed_tasks_count", 0)}</strong></div>
    </div>
    <div class="analytics-subheading">Recent meeting duration</div>
    <div class="task-bars">
        {''.join(duration_rows) if duration_rows else '<div class="empty-state">No meetings have been saved yet. Analyze and generate a meeting to add it to History & Search.</div>'}
    </div>
    """


def task_selection_changed(get_selected_task: Callable, task_id):
    if task_id is None:
        return (
            gr.update(value="Pending", interactive=False),
            gr.update(interactive=False),
            '<div class="empty-state">Select a task to view its current status and update it.</div>',
        )

    task = get_selected_task(task_id)
    if task is None:
        return (
            gr.update(value="Pending", interactive=False),
            gr.update(interactive=False),
            '<div class="empty-state">That task is no longer available. Refresh the task list and select a current task.</div>',
        )

    owner = task.get("owner") or "Unassigned"
    deadline = task.get("deadline") or "No deadline"
    message = (
        f'<div class="task-meta"><strong>{esc(task["task"])}</strong><br>'
        f'Owner: {esc(owner)} &nbsp;•&nbsp; Deadline: {esc(deadline)}</div>'
    )
    return (
        gr.update(value=task["status"], interactive=True),
        gr.update(interactive=True),
        message,
    )


# =========================================================
# ALL UI EVENT ADAPTERS
# =========================================================


def build_app(
    *,
    prepare_meeting,
    finalize_speakers,
    generate_brief,
    load_saved_meeting,
    remove_saved_meeting,
    list_tasks,
    get_selected_task,
    set_task_status,
    workspace_analytics_data,
):

    def ui_prepare_meeting(audio_path):
        result = prepare_meeting(audio_path)
        if not result["ok"]:
            return (
                "",
                {},
                gr.update(visible=False),
                gr.update(visible=False, value=result["error"]),
                gr.update(visible=False),
                gr.update(visible=False),
                *[gr.update(visible=False, value="") for _ in range(6)],
                gr.update(visible=False),
                gr.update(visible=False),
            )

        speakers = result["speakers"]
        speaker_items = list(speakers.keys())
        name_updates = []

        for index in range(6):
            if index < len(speaker_items):
                name_updates.append(
                    gr.update(
                        visible=True,
                        label=f"Name for Speaker {index + 1}",
                        placeholder="e.g. Shaurya",
                    )
                )
            else:
                name_updates.append(gr.update(visible=False, value=""))

        return (
            result["transcript"],
            speakers,
            gr.update(visible=True),
            gr.update(
                value=build_speaker_setup_html(speakers),
                visible=True,
            ),
            gr.update(
                value=None,
                visible=True,
                label=f'MeetingOS detected {len(speakers)} speaker{"s" if len(speakers) != 1 else ""}. Is this correct?',
            ),
            gr.update(visible=False),
            *name_updates,
            gr.update(visible=True, value="Continue"),
            gr.update(visible=False),
        )

    def ui_update_mapping_visibility(choice):
        if choice == "Yes":
            return (
                gr.update(visible=True),
                gr.update(visible=True, value="Confirm Names & Continue"),
            )
        if choice == "No":
            return (
                gr.update(visible=False),
                gr.update(visible=True, value="Continue Without Names"),
            )
        return gr.update(visible=False), gr.update(visible=False)

    def ui_finalize_speakers(confirmed, transcript, speakers, confirmation, *names):
        if not confirmed:
            return (
                transcript,
                *[gr.update() for _ in range(12)],
            )

        result = finalize_speakers(
            transcript,
            speakers,
            confirmation,
            list(names),
        )

        if not result.get("ok"):
            return (
                result.get("transcript", transcript),
                *[gr.update(visible=False) for _ in range(11)],
                gr.update(visible=False),
            )

        # Speaker review is complete. Hide the review controls, but keep
        # the Generate action visible so the user can continue the workflow.
        return (
            result.get("transcript", transcript),
            gr.update(visible=False),  # speaker_review_heading
            gr.update(visible=False),  # speaker_setup
            gr.update(visible=False),  # speaker_confirmation
            gr.update(visible=False),  # speaker_mapping_group
            gr.update(visible=False, value=""),  # name1
            gr.update(visible=False, value=""),  # name2
            gr.update(visible=False, value=""),  # name3
            gr.update(visible=False, value=""),  # name4
            gr.update(visible=False, value=""),  # name5
            gr.update(visible=False, value=""),  # name6
            gr.update(visible=False),  # continue_speakers_button
            gr.update(visible=True, value="Generate Meeting Intelligence"),  # generate_button
        )

    def ui_generate_brief(transcript, speakers, topic):
        result = generate_brief(transcript, speakers, topic)
        if not result["ok"]:
            return (
                '<div class="empty-page"><strong>No meeting is ready to generate.</strong><br>Analyze a recording and complete speaker review first.</div>',
                '<div class="empty-page"><strong>No meeting is open.</strong><br>Select a saved meeting from History & Search, or analyze a new recording.</div>',
                "",
                gr.update(choices=build_history_choices(), value=None),
                gr.update(choices=[], value=None),
                gr.update(value="Pending"),
                "",
            )

        intelligence_html = render_meeting_report(
            result["topic"],
            result["intelligence"],
            saved=False,
        )
        analytics_html = render_meeting_metrics(result["analytics"])
        visual_html = build_visual_analytics_html(result["visual_insights"])

        task_choices = build_task_choices("All")
        first_task = task_choices[0][1] if task_choices else None
        first_status = (
            (get_selected_task(first_task) or {}).get("status", "Pending")
            if first_task is not None
            else "Pending"
        )

        return (
            intelligence_html,
            analytics_html,
            visual_html,
            gr.update(choices=build_history_choices(), value=result["meeting_id"]),
            gr.update(choices=task_choices, value=first_task),
            gr.update(value=first_status),
            "",
        )

    def ui_refresh_workspace_analytics():
        return build_workspace_analytics_html(workspace_analytics_data())

    def ui_search(query):
        # Current R2 search behavior. Selection-reset refinement is intentionally
        # isolated here so it can be changed later without touching main.py.
        return gr.update(choices=build_search_choices(query), value=None)

    def ui_history_selection(meeting_id):
        enabled = meeting_id is not None
        return (
            gr.update(interactive=enabled),
            gr.update(interactive=enabled),
            gr.update(interactive=enabled),
            gr.update(),
            gr.update(),
            gr.update(),
            "",
        )

    def ui_refresh_task_tracker(status_filter):
        choices = build_task_choices(status_filter)
        first_task = choices[0][1] if choices else None
        current_status = (
            (get_selected_task(first_task) or {}).get("status", "Pending")
            if first_task is not None
            else "Pending"
        )
        return (
            gr.update(
                choices=choices,
                value=first_task,
            ),
            gr.update(value=current_status, interactive=first_task is not None),
            gr.update(interactive=first_task is not None),
            (
                '<div class="empty-state">No tasks match this filter. Try another status.</div>'
                if not choices
                else ""
            ),
        )

    def ui_save_task_status(task_id, status, status_filter):
        if task_id is None:
            return (
                gr.update(choices=build_task_choices(status_filter), value=None),
                gr.update(value="Pending"),
                "Select a task first. Choose one from Workspace Tasks before updating its status.",
            )

        updated = set_task_status(task_id, status)
        if not updated:
            return (
                gr.update(choices=build_task_choices(status_filter), value=task_id),
                gr.update(value=status),
                "The task status could not be updated. Check the selected task and try again.",
            )

        choices = build_task_choices(status_filter)
        remaining_values = {value for _, value in choices}
        selected_value = (
            task_id if task_id in remaining_values else choices[0][1] if choices else None
        )
        selected_status = (
            (get_selected_task(selected_value) or {}).get("status", status)
            if selected_value is not None
            else "Pending"
        )
        return (
            gr.update(choices=choices, value=selected_value),
            gr.update(value=selected_status),
            f'<div class="success-message">Task marked <strong>{esc(status)}</strong>.</div>',
        )

    def _hide_speaker_workflow_updates():
        return (
            gr.update(visible=False),  # speaker_review_heading
            gr.update(visible=False),  # speaker_setup
            gr.update(visible=False),  # speaker_confirmation
            gr.update(visible=False),  # speaker_mapping_group
            gr.update(visible=False, value=""),
            gr.update(visible=False, value=""),
            gr.update(visible=False, value=""),
            gr.update(visible=False, value=""),
            gr.update(visible=False, value=""),
            gr.update(visible=False, value=""),
            gr.update(visible=False),  # continue_speakers_button
            gr.update(visible=False),  # generate_button
        )

    def ui_open_saved_meeting(meeting_id):
        result = load_saved_meeting(meeting_id)
        hidden = _hide_speaker_workflow_updates()
        if not result["ok"]:
            return (
                f'<div class="empty-page">{esc(result["error"])}</div>',
                '<div class="empty-page"><strong>No meeting is open.</strong><br>Select a saved meeting from History & Search, or analyze a new recording.</div>',
                "",
                *hidden,
            )

        # Older meetings can contain visual insights generated before the
        # stricter validator was introduced. Re-validate them on load so
        # stale date/deadline/risk "metrics" do not resurface.
        analytics = dict(result.get("analytics") or {})
        validated_visual_insights = validate_visual_insights({
            "insights": analytics.get("visual_insights", [])
        })
        analytics["visual_insights"] = validated_visual_insights

        return (
            render_meeting_report(result["topic"], result["intelligence"], saved=True),
            render_meeting_metrics(analytics),
            build_visual_analytics_html(validated_visual_insights),
            *hidden,
        )

    def ui_close_saved_meeting():
        return (
            gr.update(value=None),
            '<div class="empty-page"><strong>No meeting is open.</strong><br>Select a saved meeting from History & Search, or analyze a new recording.</div>',
            '<div class="empty-page"><strong>No meeting is open.</strong><br>Select a saved meeting from History & Search, or analyze a new recording.</div>',
            "",
            *_hide_speaker_workflow_updates(),
        )

    def ui_delete_saved_meeting(confirmed, meeting_id):
        if not confirmed:
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                *[gr.update() for _ in range(12)],
            )

        result = remove_saved_meeting(meeting_id)
        hidden = _hide_speaker_workflow_updates()
        if not result["ok"]:
            return (
                gr.update(choices=build_history_choices(), value=None),
                f'<div class="empty-page">{esc(result["error"])}</div>',
                '<div class="empty-page"><strong>No meeting is open.</strong><br>Select a saved meeting from History & Search, or analyze a new recording.</div>',
                "",
                *hidden,
            )

        return (
            gr.update(choices=build_history_choices(), value=None),
            '<div class="empty-page"><strong>Meeting deleted.</strong><br>Select another saved meeting from History & Search or start a new meeting.</div>',
            '<div class="empty-page"><strong>No meeting is open.</strong><br>Select a saved meeting from History & Search, or analyze a new recording.</div>',
            "",
            *hidden,
        )

    def ui_open_confirm_modal():
        return gr.update(visible=True)

    def ui_cancel_confirm_modal():
        return gr.update(visible=False)

    def ui_confirm_speakers(transcript, speakers, confirmation, *names):
        result = ui_finalize_speakers(True, transcript, speakers, confirmation, *names)
        return (*result, gr.update(visible=False))

    def ui_confirm_delete(meeting_id):
        result = ui_delete_saved_meeting(True, meeting_id)
        return (*result, gr.update(visible=False))

    css = """
    .gradio-container { max-width: 1250px !important; margin: 0 auto !important; }
    #header { text-align: center; margin-bottom: 30px; }
    #header h1 { font-size: 44px; margin-bottom: 6px; }
    #header p { opacity: 0.7; font-size: 17px; }
    #generate { height: 52px; font-size: 17px; font-weight: 700; }
    #analyze { height: 48px; font-size: 16px; font-weight: 700; }
    #confirm-speakers { height: 48px; font-size: 16px; font-weight: 700; }
    .report { padding: 10px 0 40px 0; }
    .hero-section { padding: 10px 0 25px 0; }
    .eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 1.8px; opacity: 0.6; margin-bottom: 8px; }
    .hero-section h1 { margin: 0; font-size: 30px; }
    .hero-description { opacity: 0.65; margin-top: 6px; }
    .summary-card { border-radius: 16px; padding: 22px; margin-bottom: 32px; border: 1px solid rgba(255,255,255,0.10); }
    .summary-card p { font-size: 18px; line-height: 1.6; margin-bottom: 0; }
    .section-label { font-size: 12px; font-weight: 700; letter-spacing: 1.4px; opacity: 0.6; margin-bottom: 10px; }
    .section-heading { font-size: 24px; font-weight: 700; margin: 30px 0 14px 0; }
    .topic-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .topic-card, .decision-card, .action-card, .risk-card, .question-card, .contradiction-card { border: 1px solid rgba(255,255,255,0.10); border-radius: 14px; padding: 18px; margin-bottom: 12px; }
    .topic-number { font-size: 11px; font-weight: 700; letter-spacing: 1.2px; opacity: 0.5; }
    .topic-card h3 { margin: 5px 0 10px 0; font-size: 19px; }
    .topic-summary { line-height: 1.55; }
    .topic-card ul { margin-top: 8px; }
    .outcome { margin-top: 12px; font-size: 14px; opacity: 0.85; }
    .stack { display: flex; flex-direction: column; gap: 2px; }
    .decision-card, .action-card, .risk-card, .question-card, .contradiction-card { display: flex; gap: 14px; align-items: flex-start; }
    .icon { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; flex-shrink: 0; }
    .decision-icon { background: rgba(70, 200, 120, 0.16); }
    .action-icon { background: rgba(100, 130, 255, 0.16); }
    .risk-icon { background: rgba(255, 170, 70, 0.16); }
    .question-icon { background: rgba(170, 120, 255, 0.16); }
    .contradiction-icon { background: rgba(255, 100, 120, 0.16); }
    .card-main { font-size: 16px; line-height: 1.5; }
    .action-task { font-size: 16px; font-weight: 650; margin-bottom: 10px; }
    .action-meta { display: flex; gap: 24px; flex-wrap: wrap; font-size: 13px; opacity: 0.75; }
    .action-meta span { display: flex; flex-direction: column; gap: 2px; }
    .evidence { margin-top: 12px; padding: 10px 12px; border-left: 2px solid rgba(255,255,255,0.20); font-size: 12px; opacity: 0.62; line-height: 1.45; }
    .evidence-label { font-weight: 700; margin-right: 8px; }
    .evidence-time { font-weight: 700; margin-right: 8px; }
    .evidence-text { font-style: italic; }
    .two-column { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .empty-state { border: 1px dashed rgba(255,255,255,0.18); border-radius: 12px; padding: 18px; opacity: 0.65; }
    .empty-state.success { border-color: rgba(70, 200, 120, 0.25); }
    .analytics-panel { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .metric { border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; padding: 14px; text-align: center; }
    .metric-value { font-size: 24px; font-weight: 750; }
    .metric-label { font-size: 10px; letter-spacing: 1px; opacity: 0.55; margin-top: 3px; }
    .empty-page { padding: 30px; opacity: 0.6; }
    .speaker-snippet { padding: 9px 12px; margin-top: 8px; border-left: 2px solid rgba(255,255,255,0.20); font-size: 13px; opacity: 0.75; line-height: 1.45; }
    .speaker-help { font-size: 13px; opacity: 0.65; margin-bottom: 10px; }
    .workspace-analytics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 12px 0 18px 0; }
    .workspace-metric { border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; padding: 16px; }
    .task-bars { display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; }
    .bar-row { display: grid; grid-template-columns: 110px 1fr 30px; gap: 10px; align-items: center; font-size: 13px; }
    .bar-track { height: 9px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 999px; background: currentColor; }
    .task-meta { margin: 6px 0 10px 0; padding: 10px 12px; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; font-size: 13px; line-height: 1.55; }
    .success-message { padding: 9px 12px; font-size: 13px; opacity: 0.8; }
    .analytics-subheading { margin: 20px 0 10px; font-size: 15px; font-weight: 700; }
    .visual-analytics-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .visual-card { border: 1px solid rgba(255,255,255,0.10); border-radius: 14px; padding: 18px; }
    .visual-card h3 { margin: 4px 0 6px; font-size: 19px; }
    .visual-subtitle { font-size: 13px; opacity: 0.65; }
    .visual-chart { margin-top: 12px; }
    .visual-chart svg { width: 100%; height: auto; }
    .visual-chart .axis { stroke: rgba(255,255,255,0.18); stroke-width: 1; }
    .visual-chart .line-path { fill: none; stroke: currentColor; stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
    .visual-chart .line-point, .visual-chart .bar-shape { fill: currentColor; }
    .axis-label, .point-label, .donut-total, .donut-unit { fill: currentColor; opacity: 0.72; font-size: 11px; }
    .point-label { opacity: 0.92; }
    .donut-total { font-size: 18px; font-weight: 700; }
    .donut-unit { font-size: 10px; }
    .legend { margin-top: 8px; }
    .legend-row { display: grid; grid-template-columns: 14px 1fr auto; gap: 8px; align-items: center; font-size: 12px; padding: 4px 0; }
    .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
    .visual-trend { margin-top: 8px; font-size: 13px; opacity: 0.72; }
    .visual-kpi-value { margin-top: 16px; font-size: 40px; font-weight: 800; }
    .visual-kpi-value span { font-size: 15px; margin-left: 6px; opacity: 0.6; }
    .visual-kpi-label { font-size: 12px; opacity: 0.6; margin-top: 2px; }
    .visual-evidence { margin-top: 12px; padding: 9px 11px; border-left: 2px solid rgba(255,255,255,0.20); font-size: 12px; line-height: 1.45; opacity: 0.65; }
    .confirm-modal {
        position: fixed !important;
        inset: 0 !important;
        z-index: 9999 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 24px !important;
        background: rgba(0, 0, 0, 0.62) !important;
    }
    .confirm-modal > .wrap {
        width: auto !important;
        max-width: none !important;
        height: auto !important;
        min-height: 0 !important;
        flex: 0 0 auto !important;
    }
    .confirm-modal .modal-card {
        width: min(520px, 92vw) !important;
        height: auto !important;
        min-height: 0 !important;
        max-height: calc(100vh - 48px) !important;
        flex: 0 0 auto !important;
        padding: 28px !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        border-radius: 14px !important;
        background: #1d1d1f !important;
        box-shadow: 0 24px 80px rgba(0,0,0,0.55) !important;
    }
    .confirm-modal .modal-card > .wrap {
        height: auto !important;
        min-height: 0 !important;
    }
    .confirm-modal .modal-title { margin: 0 0 10px 0 !important; font-size: 22px !important; font-weight: 700 !important; }
    .confirm-modal .modal-body { margin: 0 0 22px 0 !important; font-size: 15px !important; line-height: 1.5 !important; opacity: 0.82 !important; }
    .confirm-modal .modal-actions { justify-content: flex-end !important; gap: 10px !important; }
    @media (max-width: 850px) { .topic-grid, .two-column, .visual-analytics-grid { grid-template-columns: 1fr; } }
    """

    with gr.Blocks(title="MeetingOS", css=css) as demo:
        gr.Markdown(
            """
            # MeetingOS
            ### AI-Powered Meeting Intelligence

            Turn raw meeting recordings into structured, actionable intelligence.
            """,
            elem_id="header",
        )

        # -----------------------------------------------------
        # 1. NEW MEETING
        # -----------------------------------------------------

        gr.Markdown("## New Meeting")

        with gr.Row():
            with gr.Column(scale=1):
                topic_input = gr.Textbox(
                    label="Meeting Topic",
                    placeholder="e.g. Q2 Product Launch Planning",
                    value="Meeting Discussion",
                )
                audio_input = gr.Audio(label="Meeting Recording", type="filepath")
                analyze_button = gr.Button(
                    "Analyze Recording & Detect Speakers",
                    variant="primary",
                    elem_id="analyze",
                )

            with gr.Column(scale=1):
                analytics_output = gr.HTML(
                    '<div class="empty-page"><strong>No meeting metrics yet.</strong><br>Analyze a recording to calculate duration, segments, and word count.</div>'
                )

        # -----------------------------------------------------
        # 2. SPEAKER REVIEW
        # -----------------------------------------------------

        speaker_review_heading = gr.Markdown("## Speaker Review", visible=False)
        speaker_setup = gr.HTML(visible=False)
        speaker_confirmation = gr.Radio(
            choices=["Yes", "No"],
            label="Is the detected speaker count correct?",
            visible=False,
        )

        with gr.Column(visible=False) as speaker_mapping_group:
            gr.Markdown(
                """
                **Map the detected speakers to names.**

                The sample utterances above are taken directly from the recording.
                Leave any name blank to keep the generic speaker label.
                """,
                elem_classes=["speaker-help"],
            )
            name1 = gr.Textbox(label="Name for Speaker 1", visible=False)
            name2 = gr.Textbox(label="Name for Speaker 2", visible=False)
            name3 = gr.Textbox(label="Name for Speaker 3", visible=False)
            name4 = gr.Textbox(label="Name for Speaker 4", visible=False)
            name5 = gr.Textbox(label="Name for Speaker 5", visible=False)
            name6 = gr.Textbox(label="Name for Speaker 6", visible=False)

        continue_speakers_button = gr.Button(
            "Continue",
            variant="primary",
            elem_id="confirm-speakers",
            visible=False,
        )

        # -----------------------------------------------------
        # 3. GENERATE
        # -----------------------------------------------------

        generate_button = gr.Button(
            "Generate Meeting Intelligence",
            variant="primary",
            elem_id="generate",
            visible=False,
        )

        transcript_state = gr.State("")
        speaker_state = gr.State({})

        # -----------------------------------------------------
        # 4. CURRENT MEETING
        # -----------------------------------------------------

        gr.Markdown("## Current Meeting")
        gr.Markdown("### Meeting Intelligence")
        intelligence_output = gr.HTML(
            '<div class="empty-page"><strong>No meeting results yet.</strong><br>Analyze a recording, review the speakers, and generate the meeting intelligence.</div>'
        )
        visual_analytics_output = gr.HTML("")

        # -----------------------------------------------------
        # 5. WORKSPACE
        # -----------------------------------------------------

        gr.Markdown("## Workspace")

        with gr.Accordion("Task Tracker", open=True):
            with gr.Row():
                with gr.Column(scale=2):
                    task_filter_dropdown = gr.Dropdown(
                        label="Filter tasks",
                        choices=["All", "Pending", "In Progress", "Completed"],
                        value="All",
                        interactive=True,
                    )
                with gr.Column(scale=4):
                    task_dropdown = gr.Dropdown(
                        label="Select task",
                        choices=build_task_choices(),
                        value=None,
                        interactive=True,
                    )

            with gr.Row():
                with gr.Column(scale=1):
                    task_status_dropdown = gr.Dropdown(
                        label="Status for selected task",
                        choices=["Pending", "In Progress", "Completed"],
                        value="Pending",
                        interactive=False,
                    )
                with gr.Column(scale=1):
                    update_task_button = gr.Button(
                        "Update Status",
                        variant="secondary",
                        interactive=False,
                    )

            task_status_message = gr.HTML("")

        with gr.Accordion("Meeting History & Search", open=False):
            with gr.Row():
                history_dropdown = gr.Dropdown(
                    label="Saved Meetings",
                    choices=build_history_choices(),
                    value=None,
                    interactive=True,
                    scale=3,
                )
                search_input = gr.Textbox(
                    label="Search meetings",
                    placeholder="Search topic, transcript, decisions, tasks...",
                    scale=3,
                )
                search_button = gr.Button("Search", variant="secondary", scale=1)

            with gr.Row():
                open_meeting_button = gr.Button("Open Meeting", variant="secondary", interactive=False)
                close_meeting_button = gr.Button("Close Meeting", variant="secondary", interactive=False)
                delete_meeting_button = gr.Button("Delete Meeting", variant="stop", interactive=False)

        with gr.Accordion("Workspace Analytics", open=False):
            workspace_analytics_output = gr.HTML(
                build_workspace_analytics_html(workspace_analytics_data())
            )

        # -----------------------------------------------------
        # CONFIRMATION MODALS
        # -----------------------------------------------------

        with gr.Column(visible=False, elem_id="speaker-confirm-modal", elem_classes=["confirm-modal"]) as speaker_confirm_modal:
            with gr.Column(elem_classes=["modal-card"]):
                gr.HTML("<div class='modal-title'>Confirm speaker names?</div><div class='modal-body'>These names will be applied to the detected speakers for this meeting.</div>")
                with gr.Row(elem_classes=["modal-actions"]):
                    speaker_cancel_button = gr.Button("Cancel", variant="secondary")
                    speaker_confirm_button = gr.Button("Confirm Names", variant="primary")

        with gr.Column(visible=False, elem_id="delete-confirm-modal", elem_classes=["confirm-modal"]) as delete_confirm_modal:
            with gr.Column(elem_classes=["modal-card"]):
                gr.HTML("<div class='modal-title'>Delete this meeting?</div><div class='modal-body'>This will permanently remove the meeting, transcript, intelligence, and tasks.</div>")
                with gr.Row(elem_classes=["modal-actions"]):
                    delete_cancel_button = gr.Button("Cancel", variant="secondary")
                    delete_confirm_button = gr.Button("Delete Meeting", variant="stop")

        # -----------------------------------------------------
        # EVENT WIRING
        # -----------------------------------------------------

        analyze_button.click(
            fn=ui_prepare_meeting,
            inputs=[audio_input],
            outputs=[
                transcript_state,
                speaker_state,
                speaker_review_heading,
                speaker_setup,
                speaker_confirmation,
                speaker_mapping_group,
                name1,
                name2,
                name3,
                name4,
                name5,
                name6,
                continue_speakers_button,
                generate_button,
            ],
        )

        speaker_confirmation.change(
            fn=ui_update_mapping_visibility,
            inputs=[speaker_confirmation],
            outputs=[speaker_mapping_group, continue_speakers_button],
        )

        continue_speakers_button.click(
            fn=ui_open_confirm_modal,
            inputs=[],
            outputs=[speaker_confirm_modal],
        )

        speaker_confirm_button.click(
            fn=ui_confirm_speakers,
            inputs=[transcript_state, speaker_state, speaker_confirmation, name1, name2, name3, name4, name5, name6],
            outputs=[
                transcript_state, speaker_review_heading, speaker_setup, speaker_confirmation,
                speaker_mapping_group, name1, name2, name3, name4, name5, name6,
                continue_speakers_button, generate_button, speaker_confirm_modal,
            ],
        )

        speaker_cancel_button.click(
            fn=ui_cancel_confirm_modal,
            inputs=[],
            outputs=[speaker_confirm_modal],
        )

        generate_event = generate_button.click(
            fn=ui_generate_brief,
            inputs=[transcript_state, speaker_state, topic_input],
            outputs=[
                intelligence_output,
                analytics_output,
                visual_analytics_output,
                history_dropdown,
                task_dropdown,
                task_status_dropdown,
                task_status_message,
            ],
            show_progress="hidden",
        )

        generate_event.then(
            fn=ui_refresh_workspace_analytics,
            inputs=[],
            outputs=[workspace_analytics_output],
        )

        search_button.click(
            fn=ui_search,
            inputs=[search_input],
            outputs=[history_dropdown],
        )

        history_dropdown.change(
            fn=ui_history_selection,
            inputs=[history_dropdown],
            outputs=[
                open_meeting_button,
                close_meeting_button,
                delete_meeting_button,
                update_task_button,
                task_dropdown,
                task_status_dropdown,
                task_status_message,
            ],
        )

        task_filter_dropdown.change(
            fn=ui_refresh_task_tracker,
            inputs=[task_filter_dropdown],
            outputs=[
                task_dropdown,
                task_status_dropdown,
                update_task_button,
                task_status_message,
            ],
        )

        task_dropdown.change(
            fn=lambda task_id: task_selection_changed(get_selected_task, task_id),
            inputs=[task_dropdown],
            outputs=[task_status_dropdown, update_task_button, task_status_message],
        )

        update_task_event = update_task_button.click(
            fn=ui_save_task_status,
            inputs=[task_dropdown, task_status_dropdown, task_filter_dropdown],
            outputs=[task_dropdown, task_status_dropdown, task_status_message],
        )

        update_task_event.then(
            fn=ui_refresh_workspace_analytics,
            inputs=[],
            outputs=[workspace_analytics_output],
        )

        open_meeting_button.click(
            fn=ui_open_saved_meeting,
            inputs=[history_dropdown],
            outputs=[
                intelligence_output,
                analytics_output,
                visual_analytics_output,
                speaker_review_heading,
                speaker_setup,
                speaker_confirmation,
                speaker_mapping_group,
                name1,
                name2,
                name3,
                name4,
                name5,
                name6,
                continue_speakers_button,
                generate_button,
            ],
        )

        close_event = close_meeting_button.click(
            fn=ui_close_saved_meeting,
            inputs=[],
            outputs=[
                history_dropdown,
                intelligence_output,
                analytics_output,
                visual_analytics_output,
                speaker_review_heading,
                speaker_setup,
                speaker_confirmation,
                speaker_mapping_group,
                name1,
                name2,
                name3,
                name4,
                name5,
                name6,
                continue_speakers_button,
                generate_button,
            ],
        )

        close_event.then(
            fn=ui_history_selection,
            inputs=[history_dropdown],
            outputs=[
                open_meeting_button,
                close_meeting_button,
                delete_meeting_button,
                update_task_button,
                task_dropdown,
                task_status_dropdown,
                task_status_message,
            ],
        )

        delete_meeting_button.click(
            fn=ui_open_confirm_modal,
            inputs=[],
            outputs=[delete_confirm_modal],
        )

        delete_event = delete_confirm_button.click(
            fn=ui_confirm_delete,
            inputs=[history_dropdown],
            outputs=[
                history_dropdown, intelligence_output, analytics_output, visual_analytics_output,
                speaker_review_heading, speaker_setup, speaker_confirmation, speaker_mapping_group,
                name1, name2, name3, name4, name5, name6,
                continue_speakers_button, generate_button, delete_confirm_modal,
            ],
        )

        delete_cancel_button.click(
            fn=ui_cancel_confirm_modal,
            inputs=[],
            outputs=[delete_confirm_modal],
        )

        delete_event.then(
            fn=ui_history_selection,
            inputs=[history_dropdown],
            outputs=[
                open_meeting_button,
                close_meeting_button,
                delete_meeting_button,
                update_task_button,
                task_dropdown,
                task_status_dropdown,
                task_status_message,
            ],
        ).then(
            fn=ui_refresh_workspace_analytics,
            inputs=[],
            outputs=[workspace_analytics_output],
        )

    return demo
