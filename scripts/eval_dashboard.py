"""
scripts/eval_dashboard.py

OttO Evaluation Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━
Streamlit dashboard that reads all scored sessions from evaluation/results/
and visualizes OttO's performance across dimensions, sessions, and categories.

Run:
    streamlit run scripts/eval_dashboard.py
"""

import json
from pathlib import Path
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
RESULTS_DIR    = Path("evaluation/results")
SCENARIOS_FILE = Path("evaluation/scenarios/scenarios.json")

DIMENSIONS = {
    "tool_routing":        "Tool Routing",
    "tool_selection":      "Tool Selection",
    "rag_faithfulness":    "RAG Faithfulness",
    "response_discipline": "Response Discipline",
    "discovery_quality":   "Discovery Quality",
    "guardrail_adherence": "Guardrail Adherence",
    "conversation_arc":    "Conversation Arc",
}

VERDICT_COLORS = {
    "PASS":              "#2ecc71",
    "NEEDS IMPROVEMENT": "#f39c12",
    "FAIL":              "#e74c3c",
}

SEVERITY_COLORS = {
    "critical": "#e74c3c",
    "major":    "#f39c12",
    "minor":    "#3498db",
}

# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_results() -> list[dict]:
    files = sorted(RESULTS_DIR.glob("eval_*.json"), reverse=True)
    results = []
    for f in files:
        try:
            with open(f) as fp:
                results.append(json.load(fp))
        except Exception:
            pass
    return results


@st.cache_data(ttl=300)
def load_scenarios() -> dict:
    if not SCENARIOS_FILE.exists():
        return {}
    with open(SCENARIOS_FILE) as f:
        data = json.load(f)
    return {s["id"]: s for s in data["scenarios"]}


def build_dataframe(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        dims = r.get("dimensions", {})
        row = {
            "session_id":      r.get("session_id", "—"),
            "evaluated_at":    r.get("evaluated_at", ""),
            "overall_score":   r.get("overall_score", 0),
            "verdict":         r.get("overall_verdict", "—"),
            "scenario":        r.get("scenario_matched") or "Generic",
        }
        for key in DIMENSIONS:
            row[key] = dims.get(key, {}).get("score", None)
        rows.append(row)
    return pd.DataFrame(rows)


# ── Chart builders ────────────────────────────────────────────────────────────

def radar_chart(scores: dict, title: str) -> go.Figure:
    labels = list(DIMENSIONS.values())
    values = [scores.get(k, 0) or 0 for k in DIMENSIONS]
    values_closed = values + [values[0]]
    labels_closed = labels + [labels[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=labels_closed,
        fill="toself",
        fillcolor="rgba(52, 152, 219, 0.2)",
        line=dict(color="#3498db", width=2),
        name="Score",
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 5], tickvals=[1, 2, 3, 4, 5]),
            bgcolor="#0e1117",
        ),
        showlegend=False,
        title=dict(text=title, font=dict(size=14, color="#ffffff")),
        paper_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        margin=dict(t=60, b=20, l=40, r=40),
        height=380,
    )
    return fig


def score_history_chart(df: pd.DataFrame) -> go.Figure:
    df_sorted = df.sort_values("session_id")
    colors = [VERDICT_COLORS.get(v, "#95a5a6") for v in df_sorted["verdict"]]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sorted["session_id"],
        y=df_sorted["overall_score"],
        mode="lines+markers",
        line=dict(color="#3498db", width=2),
        marker=dict(color=colors, size=10, line=dict(color="#ffffff", width=1)),
        hovertemplate="<b>%{x}</b><br>Score: %{y}<extra></extra>",
    ))
    fig.add_hline(y=4.0, line_dash="dash", line_color="#2ecc71",
                  annotation_text="PASS threshold (4.0)", annotation_font_color="#2ecc71")
    fig.add_hline(y=3.0, line_dash="dash", line_color="#f39c12",
                  annotation_text="FAIL threshold (3.0)", annotation_font_color="#f39c12")
    fig.update_layout(
        title=dict(text="Overall Score per Session", font=dict(size=14, color="#ffffff")),
        xaxis=dict(title="Session", showgrid=False, color="#aaaaaa",
                   tickangle=-30, tickfont=dict(size=10)),
        yaxis=dict(title="Score", range=[0, 5.2], color="#aaaaaa", showgrid=True,
                   gridcolor="#1f2937"),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        margin=dict(t=50, b=60, l=50, r=20),
        height=320,
    )
    return fig


def dimension_avg_chart(df: pd.DataFrame) -> go.Figure:
    avgs = {DIMENSIONS[k]: df[k].mean() for k in DIMENSIONS if k in df.columns}
    labels = list(avgs.keys())
    values = [round(v, 2) for v in avgs.values()]
    colors = ["#2ecc71" if v >= 4 else "#f39c12" if v >= 3 else "#e74c3c" for v in values]

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker=dict(color=colors),
        text=[f"{v:.1f}" for v in values],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Avg: %{x}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Average Score by Dimension (all sessions)", font=dict(size=14, color="#ffffff")),
        xaxis=dict(range=[0, 5.5], showgrid=True, gridcolor="#1f2937", color="#aaaaaa"),
        yaxis=dict(color="#aaaaaa"),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        margin=dict(t=50, b=30, l=180, r=60),
        height=320,
    )
    return fig


def verdict_donut(df: pd.DataFrame) -> go.Figure:
    counts = df["verdict"].value_counts()
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        hole=0.55,
        marker=dict(colors=[VERDICT_COLORS.get(v, "#95a5a6") for v in counts.index]),
        textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>%{value} sessions<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Verdict Distribution", font=dict(size=14, color="#ffffff")),
        paper_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        margin=dict(t=50, b=20, l=20, r=20),
        height=300,
        showlegend=False,
    )
    return fig


def flagged_turns_chart(results: list[dict]) -> go.Figure:
    counts = {"critical": 0, "major": 0, "minor": 0}
    for r in results:
        for flag in r.get("flagged_turns", []):
            sev = flag.get("severity", "minor").lower()
            if sev in counts:
                counts[sev] += 1

    fig = go.Figure(go.Bar(
        x=list(counts.keys()),
        y=list(counts.values()),
        marker=dict(color=[SEVERITY_COLORS[k] for k in counts]),
        text=list(counts.values()),
        textposition="outside",
    ))
    fig.update_layout(
        title=dict(text="Flagged Turns by Severity (all sessions)", font=dict(size=14, color="#ffffff")),
        xaxis=dict(color="#aaaaaa"),
        yaxis=dict(color="#aaaaaa", showgrid=True, gridcolor="#1f2937"),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        margin=dict(t=50, b=30, l=40, r=20),
        height=280,
    )
    return fig


# ── Page sections ─────────────────────────────────────────────────────────────

def render_kpi_row(df: pd.DataFrame):
    col1, col2, col3, col4 = st.columns(4)
    avg  = df["overall_score"].mean()
    best = df["overall_score"].max()
    worst= df["overall_score"].min()
    n    = len(df)

    with col1:
        st.metric("Sessions Evaluated", n)
    with col2:
        color = "normal" if avg >= 4 else "inverse"
        st.metric("Average Score", f"{avg:.1f} / 5.0", delta=f"{'▲' if avg >= 4 else '▼'} {avg:.1f}")
    with col3:
        st.metric("Best Session", f"{best:.1f}")
    with col4:
        st.metric("Worst Session", f"{worst:.1f}")


def render_session_detail(result: dict, scenarios: dict):
    session_id = result.get("session_id", "—")
    verdict    = result.get("overall_verdict", "—")
    score      = result.get("overall_score", 0)
    scenario_id= result.get("scenario_matched")
    dims       = result.get("dimensions", {})
    flags      = result.get("flagged_turns", [])
    strengths  = result.get("strengths", [])
    improvements = result.get("improvements", [])
    summary    = result.get("session_summary", {})
    notes      = result.get("judge_notes", "")

    verdict_color = VERDICT_COLORS.get(verdict, "#95a5a6")
    st.markdown(f"""
    <div style='background:#1a1a2e;border-radius:10px;padding:20px;margin-bottom:16px;'>
        <h3 style='color:#ffffff;margin:0'>Session: {session_id}</h3>
        <span style='color:{verdict_color};font-size:22px;font-weight:bold;'>{verdict}</span>
        <span style='color:#aaaaaa;font-size:18px;margin-left:16px;'>Overall: {score} / 5.0</span>
        <br><span style='color:#888888;font-size:13px;'>
            Scenario: {scenario_id or "Generic evaluation"}
        </span>
    </div>
    """, unsafe_allow_html=True)

    # Radar + dimension table
    col_radar, col_table = st.columns([1, 1])
    with col_radar:
        scores_dict = {k: dims.get(k, {}).get("score", 0) or 0 for k in DIMENSIONS}
        st.plotly_chart(radar_chart(scores_dict, "Dimension Scores"), use_container_width=True)

    with col_table:
        st.markdown("**Dimension breakdown**")
        for key, label in DIMENSIONS.items():
            dim   = dims.get(key, {})
            score_d = dim.get("score", "—")
            reasoning = dim.get("reasoning", "")
            color = "#2ecc71" if isinstance(score_d, int) and score_d >= 4 else \
                    "#f39c12" if isinstance(score_d, int) and score_d >= 3 else "#e74c3c"
            st.markdown(
                f"<span style='color:{color};font-weight:bold'>{score_d}/5</span> "
                f"<span style='color:#dddddd'>{label}</span>",
                unsafe_allow_html=True
            )
            if reasoning:
                st.caption(reasoning)

    st.divider()

    # Session summary
    if summary:
        st.markdown("### Session Summary")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown("**What happened**")
            st.info(summary.get("what_happened", "—"))
        with col_b:
            st.markdown("**What OttO did well**")
            st.success(summary.get("what_otto_did_well", "—"))
        with col_c:
            st.markdown("**Where OttO fell short**")
            st.warning(summary.get("where_otto_fell_short", "—"))

    st.divider()

    # Flagged turns
    if flags:
        st.markdown("### Flagged Turns")
        for flag in flags:
            sev   = flag.get("severity", "minor").lower()
            color = SEVERITY_COLORS.get(sev, "#95a5a6")
            label = sev.upper()
            with st.expander(
                f"🔴 [{label}] Turn {flag.get('turn_index', '?')} — {flag.get('issue', '')[:60]}"
                if sev == "critical" else
                f"🟡 [{label}] Turn {flag.get('turn_index', '?')} — {flag.get('issue', '')[:60]}"
                if sev == "major" else
                f"🔵 [{label}] Turn {flag.get('turn_index', '?')} — {flag.get('issue', '')[:60]}"
            ):
                st.markdown(f"> *\"{flag.get('quote', '')}\"*")
                st.markdown(f"**Issue:** {flag.get('issue', '')}")

    # Strengths and improvements
    col_s, col_i = st.columns(2)
    with col_s:
        if strengths:
            st.markdown("### Strengths")
            for s in strengths:
                st.markdown(f"✅ {s}")
    with col_i:
        if improvements:
            st.markdown("### Improvements Needed")
            for imp in improvements:
                st.markdown(f"⚠️ {imp}")

    if notes:
        st.divider()
        st.markdown("### Judge Notes")
        st.markdown(f"*{notes}*")


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="OttO Evaluation Dashboard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; }
    [data-testid="stSidebar"] { background-color: #1a1a2e; }
    h1, h2, h3 { color: #ffffff; }
    .stMetric label { color: #aaaaaa !important; }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown("## 🤖 OttO — LLM Evaluation Dashboard")
    st.caption("Powered by Claude claude-sonnet-4-6 as judge · EV Land Voice AI")
    st.divider()

    # ── Load data ─────────────────────────────────────────────────────────
    results   = load_results()
    scenarios = load_scenarios()

    if not results:
        st.warning("No evaluation results found in `evaluation/results/`.")
        st.info("Run `python scripts/judge_session.py` to evaluate a session first.")
        return

    df = build_dataframe(results)

    # ── Sidebar — session selector ─────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Session Explorer")
        session_options = ["All sessions"] + [r.get("session_id", "—") for r in results]
        selected = st.selectbox("Select session", session_options)

        st.divider()
        st.markdown("### Filters")
        verdict_filter = st.multiselect(
            "Verdict",
            options=["PASS", "NEEDS IMPROVEMENT", "FAIL"],
            default=["PASS", "NEEDS IMPROVEMENT", "FAIL"],
        )
        min_score = st.slider("Minimum score", 0.0, 5.0, 0.0, 0.1)

        st.divider()
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            st.rerun()

        st.caption(f"Last loaded: {datetime.now().strftime('%H:%M:%S')}")

    # Apply filters
    df_filtered = df[
        df["verdict"].isin(verdict_filter) &
        (df["overall_score"] >= min_score)
    ]

    # ── Global overview (when All sessions selected) ───────────────────────
    if selected == "All sessions":
        st.markdown("### Overview — All Sessions")

        if df_filtered.empty:
            st.warning("No sessions match the current filters.")
            return

        render_kpi_row(df_filtered)
        st.divider()

        # Row 1: Score history + Verdict donut
        col1, col2 = st.columns([2, 1])
        with col1:
            st.plotly_chart(score_history_chart(df_filtered), use_container_width=True)
        with col2:
            st.plotly_chart(verdict_donut(df_filtered), use_container_width=True)

        # Row 2: Dimension averages + Flagged turns
        col3, col4 = st.columns([2, 1])
        with col3:
            st.plotly_chart(dimension_avg_chart(df_filtered), use_container_width=True)
        with col4:
            filtered_results = [r for r in results
                                 if r.get("session_id") in df_filtered["session_id"].values]
            st.plotly_chart(flagged_turns_chart(filtered_results), use_container_width=True)

        # Row 3: Radar — average across all sessions
        st.divider()
        col5, col6 = st.columns([1, 1])
        with col5:
            avg_scores = {k: df_filtered[k].mean() for k in DIMENSIONS if k in df_filtered.columns}
            st.plotly_chart(radar_chart(avg_scores, "Average Dimension Scores — All Sessions"),
                            use_container_width=True)
        with col6:
            st.markdown("### All Sessions")
            for _, row in df_filtered.iterrows():
                verdict = row["verdict"]
                color   = VERDICT_COLORS.get(verdict, "#95a5a6")
                st.markdown(
                    f"<span style='color:{color}'>●</span> "
                    f"**{row['session_id']}** — {row['overall_score']}/5 "
                    f"<span style='color:#888888'>({row['scenario']})</span>",
                    unsafe_allow_html=True
                )

        # Row 4: Score breakdown table
        st.divider()
        st.markdown("### Score Breakdown Table")
        display_cols = ["session_id", "overall_score", "verdict"] + list(DIMENSIONS.keys())
        display_df   = df_filtered[display_cols].copy()
        display_df.columns = ["Session", "Overall", "Verdict"] + list(DIMENSIONS.values())
        st.dataframe(
            display_df.set_index("Session").style.background_gradient(
                subset=list(DIMENSIONS.values()), cmap="RdYlGn", vmin=1, vmax=5
            ).format("{:.1f}", subset=["Overall"] + list(DIMENSIONS.values())),
            use_container_width=True,
        )

    # ── Single session detail ──────────────────────────────────────────────
    else:
        result = next((r for r in results if r.get("session_id") == selected), None)
        if result:
            render_session_detail(result, scenarios)
        else:
            st.error(f"Session {selected} not found.")


if __name__ == "__main__":
    main()
