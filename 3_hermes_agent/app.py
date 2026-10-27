#!/usr/bin/env python3
"""
Hermes Agent — Streamlit Interactive Frontend

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

# Add project directory to sys.path
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st
import yaml

from agent_runner import GroqReviewClient, PersistentMemory
from scheduled_reviewer import ReviewMemory, scan_directory
from skills.code_review_skill import _static_code_analysis_impl as static_code_analysis

# ---------------------------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Hermes Autonomous Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .hermes-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 0.2rem;
    }
    .hermes-sub {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .memory-badge {
        background-color: #EDE9FE;
        color: #5B21B6;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #C4B5FD;
    }
    .sched-badge {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #FDE68A;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Setup Paths & Memory
# ---------------------------------------------------------------------------
MEMORY_FILE = PROJECT_DIR / "memory_store" / "review_history.json"
CONFIG_FILE = PROJECT_DIR / "config.yaml"
SHARED_TEST_INPUTS = PROJECT_DIR.parent / "shared" / "test_inputs.json"

@st.cache_data
def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()
memory = PersistentMemory(MEMORY_FILE)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image("https://img.shields.io/badge/Hermes-Autonomous_Agent-purple?style=for-the-badge", use_container_width=True)
    st.markdown("### 🤖 Hermes Agent Controls")
    
    # Model configuration
    model_name = st.selectbox(
        "Groq Model",
        ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
        index=0,
    )
    
    st.markdown("---")
    st.markdown("### 🧠 Persistent Memory Stats")
    past_reviews = memory.recall("review_history", default=[])
    session_count = memory.recall("session_count", default=0)
    
    st.metric("Total Reviews in Memory", len(past_reviews))
    st.metric("Total Active Sessions", session_count)
    
    if st.button("🗑️ Clear Persistent Memory", type="secondary"):
        if MEMORY_FILE.exists():
            MEMORY_FILE.unlink()
        memory._data = {}
        st.success("Persistent memory cleared!")
        st.rerun()

    st.markdown("---")
    st.markdown("### ⚡ Unique Superpowers")
    st.markdown('<span class="memory-badge">Cross-Session Memory</span>', unsafe_allow_html=True)
    st.caption("Retains context of previous reviews across restarts.")
    
    st.markdown('<span class="sched-badge">Scheduled Background Tasks</span>', unsafe_allow_html=True)
    st.caption("Auto-scans codebase folders on intervals without external cron.")

# ---------------------------------------------------------------------------
# Main Tabs: Reviewer vs. Memory Browser vs. Scheduled Watcher
# ---------------------------------------------------------------------------
st.markdown('<div class="hermes-header">🤖 Hermes Autonomous Code Review Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="hermes-sub">Autonomous AI agent featuring persistent memory and custom static AST skills.</div>', unsafe_allow_html=True)

tab_review, tab_memory, tab_scheduler = st.tabs([
    "🔍 Code Reviewer",
    "📚 Persistent Memory Explorer",
    "⏱️ Scheduled Background Watcher",
])

# ---------------------------------------------------------------------------
# TAB 1: Code Reviewer
# ---------------------------------------------------------------------------
with tab_review:
    # Benchmark preset loader
    sample_cases = []
    if SHARED_TEST_INPUTS.exists():
        try:
            with open(SHARED_TEST_INPUTS, "r", encoding="utf-8") as f:
                sample_cases = json.load(f)
        except Exception:
            pass
            
    sample_options = ["(Custom Code)"] + [f"{c['name']} ({c['type']})" for c in sample_cases]
    selected_sample = st.selectbox("Load Benchmark Preset", sample_options, index=0)
    
    initial_code = ""
    initial_lang = "python"
    if selected_sample != "(Custom Code)":
        preset_name = selected_sample.split(" (")[0]
        for c in sample_cases:
            if c["name"] == preset_name:
                initial_code = c.get("code", "")
                initial_lang = c.get("language", "python")
                st.info(f"💡 **Description:** {c.get('description', '')}")
                break

    c_ed, c_opt = st.columns([4, 1])
    with c_opt:
        lang = st.selectbox("Language", ["auto", "python", "javascript", "typescript"], index=0 if initial_lang == "unknown" else (1 if initial_lang == "python" else 2))
        run_review_btn = st.button("🚀 Analyze Code", type="primary", use_container_width=True)

    with c_ed:
        code_input = st.text_area("Source Code", value=initial_code, height=240, placeholder="// Paste code here...")

    if run_review_btn:
        start_t = time.time()
        
        # Step 1: Custom Static Tool
        with st.spinner("Step 1: Running custom AST/regex static analysis skill..."):
            static_res = static_code_analysis(code_input, lang)
            findings = static_res["findings"]
            summary = static_res["summary"]
            
        st.markdown(f"### 📊 Static Skill Findings ({summary['total_issues']} issues)")
        if findings:
            for f in findings:
                icon = "🔴" if f["severity"] == "critical" else ("🟡" if f["severity"] == "warning" else "🔵")
                st.markdown(f"- {icon} **[{f['severity'].upper()}]** Line {f.get('line', 'N/A')}: {f['message']}")
        else:
            st.success("✅ Static analysis found zero syntactic or pattern violations.")
            
        # Step 2: Query Memory for Context
        st.markdown("---")
        with st.spinner("Step 2: Checking persistent memory for recurring patterns..."):
            past_revs = memory.recall("review_history", default=[])
            recurring_count = 0
            if past_revs:
                for pr in past_revs:
                    if summary["overall_severity"] == "critical" and pr.get("severity") == "critical":
                        recurring_count += 1
            if recurring_count > 0:
                st.warning(f"🧠 **Persistent Memory Insight:** Similar critical vulnerabilities were observed {recurring_count} time(s) in previous sessions!")
            else:
                st.info("🧠 **Persistent Memory Insight:** No prior matching regressions found in history.")

        # Step 3: LLM Synthesis
        with st.spinner("Step 3: Hermes Agent LLM reasoning with Groq LPU..."):
            api_key = os.getenv("GROQ_API_KEY") or config.get("provider", {}).get("api_key", "")
            base_url = config.get("provider", {}).get("base_url", "https://api.groq.com/openai/v1")
            client = GroqReviewClient(api_key=api_key, model=model_name, base_url=base_url)
            
            review_text = client.review_code(code_input, lang, findings, past_reviews=past_revs)
            
        elapsed_t = time.time() - start_t
        st.success(f"Review completed in {elapsed_t:.2f}s")
        
        st.markdown("### 🤖 Hermes Agent Review")
        st.markdown(review_text)
        
        # Save to persistent memory
        new_entry = {
            "test_name": selected_sample if selected_sample != "(Custom Code)" else "Custom User Code",
            "language": lang,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "severity": summary["overall_severity"],
            "issue_count": summary["total_issues"],
            "findings": findings,
            "review": review_text[:300] + "...",
        }
        memory.append("review_history", new_entry)
        curr_sessions = memory.recall("session_count", default=0) + 1
        memory.store("session_count", curr_sessions)
        st.toast("💾 Review persisted to Hermes memory_store!")

# ---------------------------------------------------------------------------
# TAB 2: Persistent Memory Explorer
# ---------------------------------------------------------------------------
with tab_memory:
    st.markdown("### 📚 Hermes Long-Term Persistent Memory")
    st.markdown("Hermes Agent persists past reviews, learned rules, and recurring regressions in `memory_store/review_history.json`.")
    
    all_reviews = memory.recall("review_history", default=[])
    if all_reviews:
        st.markdown(f"**{len(all_reviews)} reviews stored across sessions:**")
        search_term = st.text_input("🔍 Search memory store", placeholder="Filter by keyword (e.g. sql, stack, error)...")
        
        filtered = [r for r in all_reviews if search_term.lower() in json.dumps(r).lower()] if search_term else all_reviews
        
        for idx, entry in enumerate(reversed(filtered), 1):
            with st.expander(f"Review #{len(filtered) - idx + 1}: {entry.get('test_name', 'Unnamed')} • [{entry.get('severity', 'info').upper()}] at {entry.get('timestamp', '')}"):
                st.json(entry)
    else:
        st.info("Persistent memory is currently empty. Run a code review in Tab 1 to populate memory!")

# ---------------------------------------------------------------------------
# TAB 3: Scheduled Background Watcher
# ---------------------------------------------------------------------------
with tab_scheduler:
    st.markdown("### ⏱️ Scheduled Codebase Watcher")
    st.markdown("Hermes Agent includes an autonomous recurring task engine that monitors folders, hashes files, and triggers background reviews without external cron or workflow engines.")
    
    watch_dir = PROJECT_DIR / "code_to_review"
    st.info(f"📁 **Monitored Directory:** `{watch_dir}`")
    
    files_in_dir = list(watch_dir.glob("*.*")) if watch_dir.exists() else []
    st.markdown(f"**Files currently in watch folder ({len(files_in_dir)}):**")
    for f in files_in_dir:
        st.markdown(f"- 📄 `{f.name}` ({f.stat().st_size} bytes)")
        
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Trigger On-Demand Scheduled Scan Now", type="primary"):
            from scheduled_reviewer import FileStateTracker
            sched_mem = ReviewMemory(PROJECT_DIR / "memory_store" / "scheduled_reviews.json")
            tracker = FileStateTracker(PROJECT_DIR / "memory_store" / "file_hashes.json")
            
            with st.spinner("Scanning monitored folder for changed files..."):
                reviewed_count = scan_directory(watch_dir, tracker, sched_mem, use_llm=True)
                
            st.success(f"Scan complete: {reviewed_count} file(s) reviewed and indexed into scheduled memory.")
            st.rerun()

    with c2:
        sched_stats_file = PROJECT_DIR / "memory_store" / "scheduled_reviews.json"
        if sched_stats_file.exists():
            with open(sched_stats_file, "r", encoding="utf-8") as f:
                s_data = json.load(f)
            st.markdown(f"**Background Scan History:** {len(s_data.get('reviews', []))} files reviewed.")
