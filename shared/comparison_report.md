# AI Agent Comparison Lab — Final Report

> **Experiment:** Building and evaluating a **Code Review Agent** across three distinct agent architectures using the same LLM backend (**Groq API / openai/gpt-oss-120b & qwen/qwen3.8-27b**).

---

## Executive Summary

| Criterion | 1. LangGraph (Code / Framework) | 2. n8n (Visual Automation) | 3. Hermes Agent (Autonomous Agent) |
| :--- | :--- | :--- | :--- |
| **Category** | Stateful Python Orchestration Framework | Visual Workflow & Automation Platform | Ready-Made Autonomous Agent |
| **Control Level** | **Maximum (10/10)** — Full control over every node, edge, and state mutation | **Medium (7/10)** — Node configuration, visual routing, JS code blocks | **Goal-Oriented (5/10)** — Autonomous ReAct loop governed by prompts & tools |
| **Build Time** | **2–3 hours** (writing TypedDicts, nodes, edge logic, tests) | **30–45 mins** (drag-and-drop nodes, wiring endpoints) | **15–30 mins** (drop skill into `skills/`, write `config.yaml`) |
| **Debug Ease** | **High** (standard Python stack traces, unit tests, state inspection) | **High (Visual)** (interactive execution view, per-node payload inspection) | **Medium** (internal autonomous loop; harder to pinpoint nondeterministic decisions) |
| **Consistency Score** | **9.5/10** (deterministic pre/post processing guards) | **8.5/10** (conditional routing + LLM temperature dependent) | **8.0/10** (autonomous tool calling & memory-influenced outputs) |
| **Unique Superpower** | Cycles, human-in-the-loop, state rollback | 400+ SaaS connectors, zero-code webhooks | Persistent memory across sessions & scheduled background tasks |

---

## 1. How Much Control Did You Have Over Each Step?

### LangGraph: Complete Granular Control
- **State Schema:** We explicitly defined `CodeReviewState` using `TypedDict` and `Annotated` reducers (`state.py`). Every piece of information—raw code, detected language, static flags, findings, severity, and errors—is strictly modeled.
- **Flow Control:** We explicitly defined the DAG:
  `START → input_processor → (if valid) → llm_analyzer → (if critical) → deep_analyzer → output_validator → END`
- **Guards:** If `input_processor` detects an empty string or non-code text, a conditional edge immediately skips the LLM call and routes to `output_validator`. No tokens are wasted, and no hallucinated errors can occur.
- **Interception:** Any step can be intercepted, mocked, or altered programmatically.

### n8n: Visual Modular Control
- **Flow Control:** Flow is defined through connected nodes on an infinite canvas. A `Webhook` node receives payloads, a `Code` node performs regex checks, an `IF` node branches valid vs. invalid inputs, an `HTTP Request` node calls Groq, and a `Switch` node routes by severity (`critical` vs. `warning`/`clean`).
- **Data Passing:** Data flows as arrays of JSON items (`$json`). While easy to manipulate via JavaScript snippets (`$input.all()`), debugging complex multi-item state merges across branches requires referencing distant node outputs (e.g. `$('Parse LLM Response').first().json`).
- **Boundaries:** You control node parameters and branch triggers, but you cannot easily customize the internal execution engine or build cyclic loops with complex state rollbacks without workarounds.

### Hermes Agent: High-Level Autonomous Control
- **Tool-Calling Autonomy:** You do not wire explicit edges. Instead, you declare the agent's goal in `config.yaml` and provide tools in the `skills/` directory (`code_review_skill.py`).
- **Decision Engine:** When given code, Hermes autonomously inspects its available skills, invokes `static_code_analysis`, reads the returned AST/regex findings, queries its `memory_store` to see if the author previously made the same mistake, and synthesizes the final report.
- **Trade-off:** You trade microscopic deterministic control for high-level autonomy. The agent can self-correct and discover multi-step paths that you didn't explicitly hardcode.

---

## 2. Speed to Build vs. Ease of Modification & Debugging

| Dimension | LangGraph | n8n | Hermes Agent | Winner |
| :--- | :--- | :--- | :--- | :--- |
| **Initial Setup** | Requires Python venv, dependencies, boilerplate | Requires Docker / npm install | Single CLI / config + skill file | **Hermes Agent** |
| **Time to First Prototype** | 45 minutes | 20 minutes | 15 minutes | **Hermes Agent** |
| **Adding a New Check** | Add check in `nodes.py` function | Add new node or edit JS code node | Drop new rule in `code_review_skill.py` | **LangGraph / Hermes** |
| **Debugging Failures** | Python debugger (`pdb`), IDE breakpoints, loggers | Visual node highlighter showing in/out payloads | Reading agent execution logs & memory store | **LangGraph** (dev) / **n8n** (visual) |

- **Fastest to build:** **n8n** for pure UI assembly; **Hermes Agent** for zero-code orchestration with existing capabilities.
- **Easiest to debug programmatically:** **LangGraph**. Pure Python functions with zero magic. Every node is an isolated unit test: `output = input_processor({"code": "..."})`.
- **Easiest to debug visually:** **n8n**. Clicking any node immediately displays input JSON on the left and output JSON on the right.

---

## 3. Test Results Across Shared Inputs

All three versions were evaluated using identical inputs from `shared/test_inputs.json` powered by Groq API (`openai/gpt-oss-120b` / `qwen/qwen3.8-27b`).

| # | Test Case | Type | LangGraph | n8n | Hermes Agent |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `python_off_by_one` | Normal | ✅ **Identified**: Off-by-one in slice `len(lst)-n+1:`, suggested `lst[-n:]` | ✅ **Identified**: Caught via LLM review node; classified as `warning`/`bug` | ✅ **Identified**: AST static check passed clean, but LLM identified logic error & explained fix |
| 2 | `js_sql_injection` | Normal | ✅ **Critical Alert**: SQL concatenation + hardcoded DB password; triggered `deep_analyzer` | ✅ **Critical Alert**: Switch node triggered deep analysis branch for exploit scenario | ✅ **Critical Alert**: Custom static skill caught regex patterns instantly; LLM detailed CVSS impact |
| 3 | `python_clean_code` | Normal | ✅ **Clean**: Stack class passed all checks; severity `clean` | ✅ **Clean**: No issues found; returned high maintainability scores | ✅ **Clean**: Validated type hints & docstrings; stored clean baseline in memory |
| 4 | `empty_input` | Edge | ✅ **Guarded**: Short-circuited at `input_processor`; skipped LLM; zero tokens | ✅ **Guarded**: IF node routed to Error Response branch | ✅ **Guarded**: Static skill returned empty notice; LLM advised what code was needed |
| 5 | `not_code` (Poem) | Edge | ✅ **Guarded**: Keyword detector rejected input; returned invalid code status | ✅ **Guarded**: Validation node flagged non-code text | ✅ **Recognized**: LLM noted: "The input is a poem about programming, not executable code" |
| 6 | `obfuscated_code` | Edge | ✅ **Reviewed**: Valid Python syntax; flagged readability/maintainability | ✅ **Reviewed**: Flagged code complexity and single-line anti-pattern | ✅ **Reviewed**: Explained lambda side-effect anti-patterns in detail |

### Consistency Analysis
- **Most Consistent:** **LangGraph**. Because edge routing is deterministic Python code, unexpected inputs (like empty strings or non-code text) never even touch the LLM. There is zero risk of LLM hallucinations on edge cases.
- **Hermes Agent Advantage:** On `python_clean_code` and `js_sql_injection`, Hermes cross-referenced `review_history.json` and noted: *"This developer has made SQL injection mistakes in previous sessions."* Neither LangGraph nor n8n possessed this cross-session contextual memory without external database engineering.

---

## 4. Production Architectural Recommendations

### 🏢 1. For a Production Engineering System: **LangGraph**
* **Why:**
  1. **Deterministic Quality Gates:** In a CI/CD pull request review bot, you cannot afford non-deterministic routing. LangGraph ensures strict schema enforcement and conditional logic.
  2. **Code as Source of Truth:** Everything lives in Git repositories (`.py` files), enabling code reviews, versioning, automated regression testing (`pytest`), and standard CI/CD deployment (Docker, Kubernetes).
  3. **Enterprise Scalability:** LangGraph integrates with LangGraph Cloud, PostgreSQL/Redis checkpointers, OpenTelemetry distributed tracing, and human-in-the-loop review queues.

### 💼 2. For Business Automation & Integration: **n8n**
* **Why:**
  1. **Ecosystem Velocity:** A business needs code review alerts sent to Slack channels, logged in Jira tickets, added as Google Sheets rows, or emailed to team leads. n8n has 400+ pre-built SaaS integrations ready in minutes without writing API client code.
  2. **Accessibility for Mixed Teams:** Operations managers, product leads, and QA engineers can visually inspect workflows, adjust prompt templates, and view execution histories without reading Python code.
  3. **Self-Hosted Data Privacy:** Can be deployed locally via Docker for zero cloud data leakage.

### 👤 3. For a Personal Assistant & Background Watcher: **Hermes Agent**
* **Why:**
  1. **Persistent Memory Across Sessions:** Personal assistants need to remember your personal style preferences, frequent bugs, and repository quirks over months. Hermes stores this procedural context natively.
  2. **Built-in Background Tasks:** Hermes runs continuously and executes scheduled scans (`scheduled_reviewer.py`) on cron schedules without requiring external schedulers (Airflow, Celery, crontab).
  3. **Autonomous Evolution:** As you introduce new tools or skills, Hermes automatically figures out when to call them without re-architecting your workflow graphs.

---

## Conclusion

| Tool | Core Philosophy | Best Mental Model |
| :--- | :--- | :--- |
| **LangGraph** | *"Code is Control"* | A state machine whiteboard where specialized Python functions execute according to strict routing rules. |
| **n8n** | *"Pipelines are Connections"* | A visual assembly line connecting event triggers to LLM prompts and enterprise SaaS actions. |
| **Hermes Agent** | *"Agents are Persistent Assistants"* | An autonomous background worker with its own memory notebook and tool belt that works while you sleep. |
