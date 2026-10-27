# Hermes Agent Code Review Agent — Setup Guide

This guide walks you through setting up and running the **Hermes Agent** implementation of the Code Review Agent. Hermes Agent (developed by Nous Research) is an autonomous agent framework built for persistent, long-term learning and background task execution.

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [Prerequisites](#2-prerequisites)
3. [Installation Methods](#3-installation-methods)
   - [Method 1: Standalone / Simulation Mode (Immediate, No Setup Required)](#method-1-standalone--simulation-mode-immediate-no-setup-required)
   - [Method 2: Official Hermes Agent CLI via pipx](#method-2-official-hermes-agent-cli-via-pipx)
   - [Method 3: Official Installer Script](#method-3-official-installer-script)
4. [Configuration](#4-configuration)
5. [Custom Skill: Static Code Analysis](#5-custom-skill-static-code-analysis)
6. [Unique Features in Action](#6-unique-features-in-action)
   - [Feature 1: Persistent Memory Across Sessions](#feature-1-persistent-memory-across-sessions)
   - [Feature 2: Scheduled Recurring Code Review Tasks](#feature-2-scheduled-recurring-code-review-tasks)
7. [Running Tests](#7-running-tests)
8. [Troubleshooting & Diagnostics](#8-troubleshooting--diagnostics)

---

## 1. Overview & Architecture

Hermes Agent differs fundamentally from LangGraph (a DAG orchestration library) and n8n (a visual workflow engine):
- **Autonomous Mindset**: Rather than defining every edge and branch manually, Hermes acts as an autonomous assistant with an internal tool-calling loop.
- **Persistent Memory**: Hermes stores facts, past mistakes, and workflow patterns in long-term storage (`memory_store/`), making it smarter over time.
- **Background Autonomy**: It can execute scheduled jobs (like nightly code reviews) autonomously without needing an external webhook or cron runner.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Hermes Agent Framework                          │
│                                                                        │
│   ┌─────────────────────┐             ┌────────────────────────────┐   │
│   │   Autonomous LLM    │             │     Persistent Memory      │   │
│   │     (Groq API /     │◄───────────►│  (review_history.json &    │   │
│   │ llama-3.3-70b-v)    │             │   cross-session learnings) │   │
│   └──────────┬──────────┘             └────────────────────────────┘   │
│              │                                                         │
│              ▼ Calls Tools / Skills                                    │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ Custom Skill: static_code_analysis (AST + Regex Rule Engine)   │   │
│   │  • Detects SQL injections, XSS, unhandled exceptions           │   │
│   │  • AST analysis for mutable defaults, missing docstrings       │   │
│   │  • Secret & credential regex scanner                           │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ Scheduler Engine: scheduled_reviewer.py                        │   │
│   │  • Watches repository folders                                  │   │
│   │  • Triggers automated reviews on schedule                      │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Prerequisites

- Python 3.10+ installed
- Groq API key: `<your_groq_api_key>`
- Python dependencies installed:
  ```bash
  pip install requests pyyaml
  ```

---

## 3. Installation Methods

### Method 1: Standalone / Simulation Mode (Immediate, No Setup Required)

To guarantee that tests run out-of-the-box on any machine without installing external system dependencies, `agent_runner.py` includes a complete standalone engine that mirrors Hermes Agent's architecture using the direct Groq API:

```bash
cd "3_hermes_agent"
python agent_runner.py --standalone
```

This mode:
1. Loads the Groq credentials from `config.yaml`
2. Invokes the custom AST/regex skill in `skills/code_review_skill.py`
3. Prompts the Groq LLM with the custom skill output and structured review schema
4. Stores findings into `memory_store/review_history.json` across sessions
5. Recalls past reviews to detect recurring regressions

---

### Method 2: Official Hermes Agent CLI via pipx

If you wish to run the full official `hermes-agent` CLI package in an isolated environment:

```bash
# 1. Install pipx if needed
python -m pip install --user pipx
python -m pipx ensurepath

# 2. Install Hermes Agent
pipx install hermes-agent

# 3. Verify
hermes --version
```

Then launch Hermes pointing to your config:
```bash
hermes setup --config config.yaml
```

---

### Method 3: Official Installer Script

For Unix / macOS / WSL2:
```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

For Windows PowerShell:
```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

---

## 4. Configuration

The configuration file is located at `config.yaml`:

```yaml
agent:
  name: "CodeReviewBot"
  description: "Autonomous code review agent with persistent memory & static analysis"
  model: "groq/llama-3.3-70b-versatile"

provider:
  name: "groq"
  api_key: "${GROQ_API_KEY}"
  base_url: "https://api.groq.com/openai/v1"

memory:
  enabled: true
  type: "persistent"
  storage: "./memory_store"

features:
  persistent_memory: true
  scheduled_tasks: true

skills_dir: "./skills"
```

---

## 5. Custom Skill: Static Code Analysis

The custom tool is located in `skills/code_review_skill.py`. It inspects code directly before or alongside LLM reasoning:

- **Python AST Inspection**:
  - Traverses the AST for `ast.FunctionDef`, `ast.ClassDef`, `ast.Try`
  - Detects bare `except:` statements (anti-pattern)
  - Detects mutable default arguments (e.g. `def foo(x=[])`)
  - Detects missing function docstrings
  - Identifies unused variables via scope tracking
- **Regex Security Pattern Matching**:
  - SQL string concatenations: `SELECT ... + var` or template literals `SELECT ... ${var}`
  - XSS patterns: `element.innerHTML = ...`
  - Arbitrary code execution: `eval(...)`
  - Hardcoded tokens, API keys, and credentials

You can test the skill independently:
```bash
python -c "
from skills.code_review_skill import static_code_analysis
result = static_code_analysis('def bad(items=[]):\n    try:\n        pass\n    except:\n        pass')
print(result)
"
```

---

## 6. Unique Features in Action

### Feature 1: Persistent Memory Across Sessions

LangGraph and n8n treat every execution as isolated unless an external database is manually wired in. In contrast, Hermes Agent natively persists memory:

1. **Record Review Findings**: When reviewing code, findings, author info, and code signatures are appended to `memory_store/review_history.json`.
2. **Contextual Memory Recall**: In subsequent reviews, the agent checks if the developer repeats previous security mistakes (e.g. SQL injection) or has fixed them.
3. **Run Memory Demo**:
   ```bash
   python agent_runner.py --demo-memory
   ```

### Feature 2: Scheduled Recurring Code Review Tasks

LangGraph requires an external scheduler (cron, Celery, or Airflow). n8n requires an active Cron trigger node running inside a continuous Docker server. Hermes has internal background task capabilities:

The `scheduled_reviewer.py` script demonstrates recurring automated sweeps:
```bash
python scheduled_reviewer.py --interval 60 --watch-dir ./code_to_review
```
- Automatically scans `code_to_review/`
- Compares file hashes to avoid redundant calls
- Performs AST analysis + LLM review
- Saves timestamped review summaries

---

## 7. Running Tests

To run the complete suite of 6 standard test inputs:

```bash
python agent_runner.py
```

This will:
1. Load test cases from `../shared/test_inputs.json`
2. Run static AST/pattern analysis
3. Invoke Groq `llama-3.3-70b-versatile`
4. Update persistent memory
5. Output results and write `test_results.json`

---

## 8. Troubleshooting & Diagnostics

- **429 Rate Limit**: If Groq rate limits your requests, `agent_runner.py` includes automatic exponential backoff.
- **Empty Output on Edge Cases**: Hermes handles empty inputs and non-code by short-circuiting during the static analysis phase before spending LLM tokens.
- **Memory Store Permission**: Ensure the script has write permissions in the `./memory_store` directory.
