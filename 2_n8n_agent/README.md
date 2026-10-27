# 2. n8n Code Review Agent

A visual workflow implementation of the AI Code Review Agent built with [n8n](https://n8n.io), using the Groq API (Llama 3.3 70B) for intelligent code analysis.

> **Part of the Agent Lab series** — comparing different approaches to building the same AI agent across multiple frameworks.

---

## What This Is

This project implements the same Code Review Agent as the other implementations in this series, but using **n8n's visual workflow automation platform** instead of writing code. The entire agent logic — input validation, LLM calls, routing, response formatting — is defined as a drag-and-drop workflow that can be imported into any n8n instance.

The agent accepts code snippets via a webhook, analyzes them for bugs, security vulnerabilities, and performance issues using an LLM, and returns a structured JSON report.

---

## Workflow Diagram

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
│   Webhook    │───▶│ Input Validation │───▶│ Valid Input?  │
│   Trigger    │    │   (Code Node)    │    │  (IF Node)   │
│  POST /code- │    │                  │    │              │
│   review     │    │ • code not empty │    │              │
└─────────────┘    │ • has keywords   │    └──────┬───────┘
                    │ • lang supported │           │
                    └──────────────────┘      ┌────┴────┐
                                              │         │
                                          Valid ✓    Invalid ✗
                                              │         │
                                              ▼         ▼
                                   ┌──────────────┐  ┌────────────────┐
                                   │ Groq API Call │  │ Respond - Error│
                                   │ Code Review   │  │   HTTP 400     │
                                   │ (HTTP Request)│  └────────────────┘
                                   └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │ Parse LLM    │
                                   │ Response     │
                                   │ (Code Node)  │
                                   └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  Severity    │
                                   │  Router      │
                                   │ (Switch Node)│
                                   └──┬───┬───┬───┘
                                      │   │   │
                            Critical  │   │   │  Warning/Clean/Info
                                      │   │   │
                                      ▼   │   └──────────────┐
                             ┌─────────── │ ─┐               │
                             │ Groq API   │  │               │
                             │ Deep       │  │               │
                             │ Analysis   │  │               │
                             └─────┬───── │ ─┘               │
                                   │      │                  │
                                   ▼      ▼                  ▼
                                   ┌──────────────────────────┐
                                   │   Format Final Report    │
                                   │      (Code Node)         │
                                   └────────────┬─────────────┘
                                                │
                                                ▼
                                   ┌──────────────────────────┐
                                   │   Respond - Success      │
                                   │      HTTP 200            │
                                   └──────────────────────────┘
```

---

## Project Structure

```
2_n8n_agent/
├── workflow.json       # The n8n workflow (import this into n8n)
├── test_inputs.json    # Test cases for the webhook
├── test_workflow.py    # Python test runner script
├── setup_guide.md      # Detailed installation & configuration guide
└── README.md           # This file
```

---

## Quick Start

### 1. Start n8n

```bash
# Using Docker (recommended)
docker run -it --rm -p 5678:5678 -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n

# Or using npx
npx n8n
```

### 2. Import the Workflow

Open `http://localhost:5678` → Menu → Import from File → select `workflow.json`

### 3. Configure Groq API Key

In the workflow editor, open each HTTP Request node → create an HTTP Header Auth credential:
- **Header Name:** `Authorization`
- **Header Value:** `Bearer <your-groq-api-key>`

### 4. Activate & Test

Toggle the workflow to **Active**, then:

```bash
curl -X POST http://localhost:5678/webhook/code-review \
  -H "Content-Type: application/json" \
  -d '{"code": "eval(input())", "language": "python"}'
```

Or use the Python test runner:

```bash
pip install requests
python test_workflow.py
```

See [setup_guide.md](setup_guide.md) for the full detailed walkthrough.

---

## What You CAN Control in n8n vs. Code

| Aspect | n8n | Code (e.g., LangGraph) |
|--------|-----|------------------------|
| **Workflow visualization** | ✅ Built-in canvas with real-time execution view | ❌ Requires external tools (Mermaid, etc.) |
| **Branching & routing** | ✅ IF/Switch nodes — visual, easy to modify | ✅ Full programmatic control |
| **LLM integration** | ✅ HTTP Request nodes or built-in AI nodes | ✅ Direct SDK access |
| **Input validation** | ✅ Code nodes with JavaScript | ✅ Any language, any library |
| **Error handling** | ✅ Built-in error workflows, retry on failure | ✅ try/catch, custom strategies |
| **Credential management** | ✅ Encrypted credential store, no keys in code | ⚠️ Env vars, .env files |
| **Deployment** | ✅ Docker, n8n Cloud — zero code deployment | ⚠️ Requires infrastructure setup |
| **Monitoring** | ✅ Execution history, logs, timing per node | ⚠️ Custom logging needed |
| **Webhook endpoints** | ✅ One-click webhook creation | ⚠️ Need web framework (Flask, FastAPI) |
| **Collaboration** | ✅ Non-developers can read/modify the workflow | ❌ Requires coding knowledge |

## What You CANNOT Control in n8n vs. Code

| Aspect | n8n Limitation | Code Advantage |
|--------|----------------|----------------|
| **Complex state management** | Limited to passing data between nodes | Full state machines, databases, caches |
| **Custom retry logic** | Basic retry (count + delay) only | Exponential backoff, circuit breakers, custom strategies |
| **Streaming responses** | ❌ Not supported for webhooks | ✅ SSE, WebSockets, chunked transfer |
| **Parallel LLM calls** | Limited — Split In Batches node | Full async/await, thread pools |
| **Dynamic prompt engineering** | Possible but awkward in expression syntax | Clean template engines, f-strings, builders |
| **Fine-grained token control** | Can't easily count tokens pre-request | tiktoken, token budgets, truncation |
| **Unit testing** | No built-in test framework | pytest, jest, full CI/CD |
| **Type safety** | JavaScript in Code nodes (no TypeScript) | TypeScript, Python type hints, Rust, etc. |
| **LLM response validation** | Manual JSON parsing in Code nodes | Pydantic, Zod, structured output APIs |
| **Multi-turn conversations** | Requires external state (database) | In-memory state, conversation objects |
| **Plugin/tool ecosystem** | Limited to n8n's community nodes | pip/npm — unlimited libraries |

---

## Limitations Encountered

### 1. Expression Syntax Complexity
n8n's expression syntax (`={{ }}`) for constructing JSON bodies is powerful but becomes unwieldy for complex nested structures like the LLM prompt. Multi-line strings with escaped JSON schemas inside expressions are hard to read and debug.

### 2. JSON Body Construction
Building the Groq API request body requires careful escaping of quotes within the system prompt. A single misplaced quote breaks the entire node. In code, this is a simple dictionary/object.

### 3. No Native Streaming
n8n's Respond to Webhook node cannot stream responses. For long-running LLM calls, the client must wait for the full response. Code-based implementations can use SSE or WebSockets.

### 4. Limited Testing Workflow
There's no built-in way to run automated tests against the workflow. You either test manually through the UI or write external test scripts (like `test_workflow.py`). Code-based implementations can use standard testing frameworks.

### 5. Credential Reference by ID
The workflow JSON references credentials by ID (`"id": "GROQ_CREDENTIAL_ID"`), which doesn't exist in a fresh n8n instance. Users must manually re-link credentials after import. There's no way to include the credential value in the workflow file (by design — security).

### 6. Cross-Node Data Access
Accessing data from non-adjacent nodes (e.g., the original code in the Format Report node) requires using `$('Node Name')` expressions, which are fragile — renaming a node breaks all references. Code-based implementations use variables or state objects.

### 7. Error Handling Granularity
n8n's error handling is per-workflow or per-node (retry on failure). There's no easy way to implement fallback LLM calls, graceful degradation, or circuit-breaker patterns without adding significant complexity.

### 8. Version Control Challenges
The workflow is a single large JSON file. Diffing changes between versions is possible but not as readable as diffing code files. Branch merges can be painful.

---

## API Response Format

### Success (HTTP 200)

```json
{
  "status": "success",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "input": {
    "language": "python",
    "codeLength": 245,
    "codePreview": "import sqlite3..."
  },
  "review": {
    "summary": "Critical SQL injection vulnerability found.",
    "severity": "critical",
    "issueCount": 3,
    "issues": [
      {
        "severity": "critical",
        "category": "security",
        "line": "5",
        "description": "SQL injection via string concatenation",
        "suggestion": "Use parameterized queries"
      }
    ],
    "metrics": {
      "readability": 7,
      "maintainability": 5,
      "security": 2,
      "performance": 6,
      "overall": 4
    }
  },
  "deepAnalysis": {
    "exploitScenarios": [...],
    "fixSuggestions": [...],
    "prioritizedActions": [...]
  },
  "metadata": {
    "model": "llama-3.3-70b-versatile",
    "tokensUsed": 1234,
    "engine": "n8n-workflow",
    "version": "1.0.0"
  }
}
```

### Error (HTTP 400)

```json
{
  "status": "error",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "error": {
    "type": "VALIDATION_ERROR",
    "message": "Validation failed: Code field is empty or missing.",
    "details": ["Code field is empty or missing."]
  },
  "metadata": {
    "engine": "n8n-workflow",
    "version": "1.0.0"
  }
}
```
