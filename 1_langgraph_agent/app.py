#!/usr/bin/env python3
"""
LangGraph Code Review Agent — Streamlit Interactive Frontend

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add local python_libs if present
_lib_dir = Path.home() / "python_libs"
if _lib_dir.exists() and str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

# Add parent directory for imports
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent import run_review
from nodes import _get_llm
from state import CodeReviewState

# ---------------------------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LangGraph Code Reviewer",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .severity-badge-critical {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #F87171;
    }
    .severity-badge-warning {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #FBBF24;
    }
    .severity-badge-clean {
        background-color: #DCFCE7;
        color: #166534;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #4ADE80;
    }
    .severity-badge-info {
        background-color: #E0F2FE;
        color: #075985;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #38BDF8;
    }
    .node-box {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 12px;
    }
    .node-title {
        font-weight: 600;
        font-size: 0.95rem;
        color: #334155;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Load Benchmark Test Cases
# ---------------------------------------------------------------------------
SHARED_DIR = PROJECT_DIR.parent / "shared"
TEST_INPUTS_PATH = SHARED_DIR / "test_inputs.json"

@st.cache_data
def load_sample_cases() -> list[dict]:
    if TEST_INPUTS_PATH.exists():
        try:
            with open(TEST_INPUTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

sample_cases = load_sample_cases()
sample_options = ["(Custom Code)"] + [f"{c['name']} ({c['type']})" for c in sample_cases]

# ---------------------------------------------------------------------------
# Sidebar Controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image("https://img.shields.io/badge/LangGraph-Framework-blue?style=for-the-badge&logo=python", use_container_width=True)
    st.markdown("### ⚙️ Agent Configuration")
    
    # Model Selection
    model_option = st.selectbox(
        "Groq LLM Model",
        ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
        index=0,
        help="Model running on Groq LPU inference",
    )
    os.environ["GROQ_MODEL"] = model_option
    
    # Preset Selector
    st.markdown("---")
    st.markdown("### 📂 Benchmark Presets")
    selected_sample = st.selectbox(
        "Load Test Case",
        sample_options,
        index=0,
        help="Select a benchmark test case or write your own code",
    )
    
    st.markdown("---")
    st.markdown("### 🧩 Graph Architecture")
    st.code("""
START ──► input_processor
              │
    (Valid?) ─┴─► (No) ──► output_validator
              │ (Yes)
              ▼
         llm_analyzer
              │
 (Critical?) ─┴─► (Yes) ─► deep_analyzer
              │ (No)           │
              ▼                ▼
         output_validator ◄────┘
              │
              ▼
             END
""", language="text")

# ---------------------------------------------------------------------------
# Main Content Header
# ---------------------------------------------------------------------------
st.markdown('<div class="main-header">🛡️ LangGraph Code Review Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Stateful, multi-node code auditor powered by LangGraph & Groq LPU inference.</div>', unsafe_allow_html=True)

# Determine initial code and language
initial_code = ""
initial_lang = "python"

if selected_sample != "(Custom Code)":
    # Find matching preset
    preset_name = selected_sample.split(" (")[0]
    for c in sample_cases:
        if c["name"] == preset_name:
            initial_code = c.get("code", "")
            initial_lang = c.get("language", "python")
            st.info(f"💡 **Test Case Info:** {c.get('description', '')}")
            break

# Input Form
col_editor, col_controls = st.columns([4, 1])

with col_controls:
    language_choice = st.selectbox(
        "Language",
        ["auto", "python", "javascript", "typescript", "java", "c", "cpp", "rust", "go"],
        index=0 if initial_lang == "unknown" else (["auto", "python", "javascript", "typescript", "java", "c", "cpp", "rust", "go"].index(initial_lang) if initial_lang in ["auto", "python", "javascript", "typescript", "java", "c", "cpp", "rust", "go"] else 0),
    )
    run_button = st.button("🚀 Run Review", type="primary", use_container_width=True)

with col_editor:
    code_input = st.text_area(
        "Source Code to Review",
        value=initial_code,
        height=260,
        placeholder="// Paste code snippet here...",
        help="Type or paste the code snippet you want the agent to analyze.",
    )

# ---------------------------------------------------------------------------
# Execution & Results
# ---------------------------------------------------------------------------
if run_button:
    if not code_input and selected_sample == "(Custom Code)":
        st.warning("⚠️ Code input is empty. The agent will run its empty-input validation check.")
    
    # Status progression placeholder
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    status_text.text("Node 1: Executing input_processor (validation & language detection)...")
    progress_bar.progress(25)
    time.sleep(0.3)
    
    start_time = time.time()
    
    with st.spinner("LangGraph state pipeline running..."):
        report = run_review(code_input, language=language_choice)
        elapsed = time.time() - start_time
        
    progress_bar.progress(100)
    status_text.empty()
    progress_bar.empty()
    
    st.success(f"✅ Review completed in **{elapsed:.2f}s** using **{model_option}**")
    
    # -----------------------------------------------------------------------
    # Summary Dashboard
    # -----------------------------------------------------------------------
    severity = report.get("severity", "info").lower()
    status = report.get("status", "reviewed")
    summary = report.get("input_summary", {})
    findings = report.get("findings", {})
    deep_analysis = report.get("deep_analysis")
    recs = report.get("recommendations", [])
    errors = report.get("errors", [])
    
    # Top Metrics Bar
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Pipeline Status", status.upper())
    with m2:
        badge_class = f"severity-badge-{severity}" if severity in ["critical", "warning", "clean", "info"] else "severity-badge-info"
        st.markdown(f"**Severity Level**<br><span class='{badge_class}'>{severity.upper()}</span>", unsafe_allow_html=True)
    with m3:
        st.metric("Detected Language", summary.get("language", "N/A"))
    with m4:
        st.metric("Lines of Code", summary.get("line_count", 0))
    
    st.markdown("---")
    
    # Detailed Tabs
    tab_summary, tab_deep, tab_recs, tab_state = st.tabs([
        "📋 Review Summary",
        "🚨 Deep Vulnerability Analysis",
        "💡 Actionable Fixes",
        "🧠 LangGraph Shared State Inspector",
    ])
    
    with tab_summary:
        if errors:
            st.error("### ⚠️ Validation Failures")
            for err in errors:
                st.markdown(f"- **{err}**")
        else:
            llm_summary = findings.get("summary", "No summary provided.")
            st.markdown(f"### 📝 Executive Assessment\n{llm_summary}")
            
            c_bugs, c_sec = st.columns(2)
            with c_bugs:
                st.markdown("#### 🐛 Bugs & Logic Flaws")
                bugs = findings.get("bugs", [])
                if bugs:
                    for b in bugs:
                        st.markdown(f"- 🔴 {b}")
                else:
                    st.markdown("*(None detected)*")
                    
            with c_sec:
                st.markdown("#### 🔒 Security Vulnerabilities")
                sec = findings.get("security_issues", [])
                if sec:
                    for s in sec:
                        st.markdown(f"- 🔴 **{s}**")
                else:
                    st.markdown("*(None detected)*")
            
            c_style, c_perf = st.columns(2)
            with c_style:
                st.markdown("#### 🎨 Style & Best Practices")
                style = findings.get("style_issues", [])
                if style:
                    for st_item in style:
                        st.markdown(f"- 🟡 {st_item}")
                else:
                    st.markdown("*(None detected)*")
                    
            with c_perf:
                st.markdown("#### ⚡ Performance Observations")
                perf = findings.get("performance_issues", [])
                if perf:
                    for p in perf:
                        st.markdown(f"- 🔵 {p}")
                else:
                    st.markdown("*(None detected)*")

    with tab_deep:
        if deep_analysis:
            st.markdown("### 🚨 Deep Security & Exploit Analysis (Node 3)")
            st.markdown("*(Triggered automatically by LangGraph conditional edge because severity == CRITICAL)*")
            
            exploits = deep_analysis.get("exploit_scenarios", [])
            if exploits:
                st.markdown("#### 🏴‍☠️ Exploit Scenarios")
                for exp in exploits:
                    st.markdown(f"- {exp}")
            
            fixes = deep_analysis.get("fix_suggestions", [])
            if fixes:
                st.markdown("#### 🛠️ Recommended Patches")
                for f in fixes:
                    st.markdown(f"- {f}")
            
            root_cause = deep_analysis.get("root_cause_analysis", "")
            if root_cause:
                st.markdown(f"#### 🔍 Root Cause\n{root_cause}")
        else:
            st.info("ℹ️ Deep analysis was not triggered for this code. (Conditional edge only routes here when severity is CRITICAL).")

    with tab_recs:
        st.markdown("### 💡 Prioritized Action Items")
        if recs:
            for idx, r in enumerate(recs, 1):
                st.markdown(f"**{idx}.** {r}")
        else:
            st.markdown("*(No action items required — code meets clean standard)*")

    with tab_state:
        st.markdown("### 🧠 Evolving State Inspection (`CodeReviewState`)")
        st.markdown("LangGraph passes this shared dictionary through every node, applying reducers and conditional edge routing.")
        st.json(report)

# Footer
st.markdown("---")
st.caption("AI Agent Comparison Lab • Project 1: LangGraph Agent • Powered by Groq LPU Inference")
