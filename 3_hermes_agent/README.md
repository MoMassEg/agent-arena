# 🤖 3. Hermes Agent — Autonomous Code Review Agent

> **Tool Category:** Ready-Made Autonomous Agent Framework  
> **Framework:** Hermes Agent (Nous Research)  
> **LLM:** Groq API (`llama-3.3-70b-versatile`)  
> **Unique Superpowers:** Persistent Memory Across Sessions & Scheduled Recurring Background Tasks

---

## 🌟 Overview

The **Hermes Agent** project implements our Code Review Agent using an autonomous, goal-oriented paradigm. Unlike **LangGraph** (which requires explicitly coding a state graph and transitions) and **n8n** (which requires drawing a node-and-wire visual DAG), **Hermes Agent**:

1. Operates as an **autonomous agent** with an internal ReAct/tool-calling loop.
2. Incorporates **Persistent Memory**, retaining context of previous reviews across restarts.
3. Implements **Scheduled Recurring Reviews**, executing background sweeps of code folders without external cron engines.
4. Uses a **Custom Static Code Analysis Skill** (`skills/code_review_skill.py`) utilizing Python AST parsing and regex security patterns to complement the LLM.

---

## 📁 Project Structure

```
3_hermes_agent/
├── config.yaml               # Hermes agent & Groq LLM configuration
├── agent_runner.py           # Dual-mode runner (Official Hermes + Standalone Groq)
├── scheduled_reviewer.py     # Recurring background review scheduler
├── setup_guide.md            # Detailed installation and setup guide
├── README.md                 # Project documentation (this file)
├── skills/
│   ├── __init__.py
│   └── code_review_skill.py  # Custom AST + regex static analysis tool
├── memory_store/             # Persistent memory storage (JSON/SQLite)
│   └── review_history.json
└── code_to_review/           # Monitored directory for scheduled sweeps
```

---

## 🛠️ Key Differentiators: What Hermes Offers

| Capability | LangGraph | n8n | Hermes Agent |
|---|---|---|---|
| **Control Model** | Deterministic Code (Graph) | Visual Flowchart (DAG) | Autonomous Loop + Prompts |
| **Persistent Memory** | Requires external DB integration | Requires external DB / Redis | **Built-in out-of-the-box** |
| **Scheduled Tasks** | Requires external orchestrator | Requires server cron trigger | **Built-in background task runner** |
| **Tool Integration** | Code functions bound to model | Pre-built integrations & HTTP | **Plug-and-play skills directory** |
| **Setup Velocity** | High code effort | Fast visual setup | **Fastest: declare config + skills** |

---

## 🚀 Quick Start

### 1. Install Requirements
```bash
pip install requests pyyaml
```

### 2. Run the Review Test Suite
Run the 6 shared test cases across the static analysis skill and Groq LLM:
```bash
python agent_runner.py
```

### 3. Test Persistent Memory
Demonstrate how memory is retained across runs:
```bash
python agent_runner.py --demo-memory
```

### 4. Run the Background Scheduled Scanner
Start a watcher that automatically reviews any files dropped into `./code_to_review/`:
```bash
python scheduled_reviewer.py --interval 30 --watch-dir ./code_to_review
```

---

## 🧩 Custom Skill: Static Code Analysis

The agent uses `skills/code_review_skill.py` to inspect incoming code before or alongside LLM reasoning:

- **AST Checks:**
  - Bare `except:` statements (anti-pattern)
  - Mutable default arguments (`def f(x=[])`)
  - Missing function/class docstrings
  - Unused local variables
- **Security Regex:**
  - SQL injection patterns (`SELECT ... + userInput`)
  - Cross-site scripting (`.innerHTML =`)
  - Arbitrary code execution (`eval()`)
  - Hardcoded API keys, JWTs, and database passwords

---

## 📊 Output Schema

Hermes Agent outputs standardized reports matching the LangGraph and n8n formats:

```json
{
  "status": "reviewed",
  "language": "javascript",
  "severity": "critical",
  "static_analysis": {
    "issues_count": 2,
    "security_alerts": ["Potential SQL injection concatenation"]
  },
  "llm_findings": {
    "bugs": ["Direct string concatenation in SQL queries"],
    "security_issues": ["Critical SQL Injection vulnerability"],
    "summary": "User parameter is unsanitized in db query."
  },
  "memory_context": {
    "is_recurring_issue": true,
    "times_seen_previously": 3
  }
}
```

See [setup_guide.md](file:///c:/Users/Dell/Documents/AI_projects/projects/agent%20lab/3_hermes_agent/setup_guide.md) for full installation and deep architectural notes.
