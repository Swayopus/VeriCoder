"""Streamlit dashboard for VeriCoder experiment results.

Run with::

    streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from report.storage import ResultStore  # noqa: E402

st.set_page_config(page_title="VeriCoder", page_icon="✅", layout="wide")
st.title("VeriCoder — Coding Agent Reliability")
st.caption("Internal diagnostics; synthetic challenges and real-agent evidence are separate sources")

store = ResultStore(config.DATABASE_PATH)
rows = store.rows()

if not rows:
    st.info("No runs recorded yet. Run `python vericoder.py study --save` first.")
    st.stop()

frame = pd.DataFrame(rows)
batch = st.selectbox("Run batch", list(dict.fromkeys(frame['run_id']))[::-1])
frame = frame[frame['run_id'] == batch]
experiments = sorted(frame["experiment"].unique())
selected = st.multiselect("Experiments", experiments, default=experiments)
frame = frame[frame["experiment"].isin(selected)]
if frame.empty:
    st.info("Select at least one condition.")
    st.stop()
st.info("Paired conditions share their first attempt. Do not sum per-condition token totals; use study.json actual_tokens. Human actions count only recorded events.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Runs", len(frame))
col2.metric("Internal success", f"{frame['success'].mean():.0%}")
col3.metric("First-attempt success", f"{frame['first_attempt_success'].mean():.0%}")
col4.metric("Avg retries", f"{frame['retries'].mean():.2f}")

st.subheader("Per-task results")
st.dataframe(
    frame[
        [
            "experiment",
            "repository",
            "task_id",
            "agent",
            "verdict",
            "repeat_index",
            "success",
            "first_attempt_success",
            "retries",
            "out_of_scope",
            "test_modified",
            "trace_anomalies",
            "failed_requirements",
            "retry_tokens",
            "duration_ms",
            "human_intervention_count",
        ]
    ],
    use_container_width=True,
)

st.subheader("Aggregate comparison")
aggregate = (
    frame.groupby("experiment")
    .agg(
        task_success_rate=("success", "mean"),
        first_attempt_success_rate=("first_attempt_success", "mean"),
        average_retries=("retries", "mean"),
        out_of_scope_warning_rate=("out_of_scope", "mean"),
        test_modification_count=("test_modified", "sum"),
        trace_anomaly_count=("trace_anomalies", "sum"),
        human_intervention_count=("human_intervention_count", "sum"),
        retry_tokens=("retry_tokens", "sum"),
    )
    .round(3)
)
st.dataframe(aggregate, use_container_width=True)

st.subheader("Run detail")
for _, row in frame.sort_values("id", ascending=False).head(20).iterrows():
    payload = json.loads(row["payload"])
    with st.expander(f"[{row['experiment']}] {row['repository']}/{row['task_id']} — success={bool(row['success'])}"):
        final = payload.get("final_report") or {}
        st.write("Held-out acceptance", payload.get("acceptance"))
        st.write("Human action events", payload.get("human_interventions", []))
        st.write("Feedback", final.get("feedback", {}))
        st.write("Trace anomalies", final.get("trace_result", {}).get("anomalies", []))
        st.write("Diff", {
            "changed_files": final.get("diff_result", {}).get("changed_files"),
            "out_of_scope": final.get("diff_result", {}).get("out_of_scope_files"),
        })
        st.json(payload)
