# n8n Code Review Agent — Setup Guide

This guide walks you through installing n8n, importing the Code Review Agent workflow, configuring your Groq API key, and running your first test.

---

## Table of Contents

1. [Install n8n](#1-install-n8n)
2. [Import the Workflow](#2-import-the-workflow)
3. [Configure the Groq API Key](#3-configure-the-groq-api-key)
4. [Activate the Workflow](#4-activate-the-workflow)
5. [Test with curl](#5-test-with-curl)
6. [Node-by-Node Walkthrough](#6-node-by-node-walkthrough)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Install n8n

Choose **one** of the three installation methods below.

### Option A — Docker (Recommended)

```bash
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  docker.n8n.io/n8nio/n8n
```

This starts n8n on `http://localhost:5678`. Data is persisted in a Docker volume.

### Option B — npm (Global Install)

```bash
npm install n8n -g
n8n start
```

### Option C — npx (No Install)

```bash
npx n8n
```

> **Note:** npx downloads n8n each time. For repeated use, the npm or Docker method is better.

After any of these, open your browser to **http://localhost:5678** and create your admin account.

---

## 2. Import the Workflow

1. Open n8n in your browser → **http://localhost:5678**
2. Click the **☰ menu** (top-left) → **Workflows**
3. Click the **"+ Add Workflow"** button (top-right), or use the **Import from File** option:
   - Click the **⋮** (three dots) menu → **Import from File**
   - Select the `workflow.json` file from this project
4. The workflow canvas should now display all 10 nodes connected in order

> **Alternative:** You can also import via the n8n CLI:
> ```bash
> n8n import:workflow --input=workflow.json
> ```

---

## 3. Configure the Groq API Key

The workflow uses **HTTP Header Auth** to authenticate with the Groq API. You need to create this credential in n8n:

1. In the workflow editor, **double-click** the "Groq - Code Review" node
2. In the node settings panel, find the **Authentication** section
3. Click **"Create New Credential"** under HTTP Header Auth
4. Configure it:
   - **Name**: `Groq API Key`
   - **Header Name**: `Authorization`
   - **Header Value**: `Bearer <your_groq_api_key>`
5. Click **Save**
6. Now do the same for the **"Groq - Deep Analysis"** node — select the same credential from the dropdown

> **Important:** Both HTTP Request nodes ("Groq - Code Review" and "Groq - Deep Analysis") must use the same credential.

---

## 4. Activate the Workflow

1. In the workflow editor, toggle the **Active** switch in the top-right corner (it should turn green)
2. The webhook endpoint is now live at:
   ```
   http://localhost:5678/webhook/code-review
   ```

> **Test Mode:** While developing, you can also use the **"Test Webhook"** URL (shown when you click the Webhook Trigger node):
> ```
> http://localhost:5678/webhook-test/code-review
> ```
> This lets you see execution data in the n8n UI but requires you to click "Listen for Test Event" first.

---

## 5. Test with curl

### Basic test — SQL Injection vulnerability (Python)

```bash
curl -X POST http://localhost:5678/webhook/code-review \
  -H "Content-Type: application/json" \
  -d '{
    "code": "import sqlite3\n\ndef get_user(username):\n    conn = sqlite3.connect(\"users.db\")\n    query = \"SELECT * FROM users WHERE username = \\\"\" + username + \"\\\"\"\n    cursor = conn.cursor()\n    cursor.execute(query)\n    return cursor.fetchone()",
    "language": "python"
  }'
```

### Test — Clean code

```bash
curl -X POST http://localhost:5678/webhook/code-review \
  -H "Content-Type: application/json" \
  -d '{
    "code": "from typing import Optional\n\ndef add(a: int, b: int) -> int:\n    \"\"\"Add two integers.\"\"\"\n    return a + b\n\ndef divide(a: float, b: float) -> Optional[float]:\n    \"\"\"Safely divide a by b.\"\"\"\n    if b == 0:\n        return None\n    return a / b",
    "language": "python"
  }'
```

### Test — Validation error (empty code)

```bash
curl -X POST http://localhost:5678/webhook/code-review \
  -H "Content-Type: application/json" \
  -d '{
    "code": "",
    "language": "python"
  }'
```

Expected: HTTP 400 with a validation error message.

### Test — Validation error (missing language)

```bash
curl -X POST http://localhost:5678/webhook/code-review \
  -H "Content-Type: application/json" \
  -d '{
    "code": "print(\"hello\")"
  }'
```

### Using the Python test runner

```bash
pip install requests
python test_workflow.py
python test_workflow.py --url http://localhost:5678/webhook-test/code-review
```

---

## 6. Node-by-Node Walkthrough

Here's what each node in the workflow does:

### Node 1: **Webhook Trigger**
> *[Visual: Green webhook icon, first node on the left]*

Listens for `POST` requests at `/code-review`. Accepts a JSON body with `code` (string) and `language` (string) fields. Configured in **"Response Node"** mode so the response is sent later by a Respond to Webhook node.

### Node 2: **Input Validation** (Code Node)
> *[Visual: Orange code icon with { } brackets]*

JavaScript function that validates the incoming request:
- Checks that `code` is not empty
- Verifies the input contains programming keywords (not random text)
- Confirms `language` is in the supported list (Python, JavaScript, Java, Go, etc.)

Outputs a JSON object with `isValid`, `code`, `language`, and `errors` fields.

### Node 3: **Valid Input?** (IF Node)
> *[Visual: Purple diamond-shaped conditional node]*

Routes execution based on `isValid`:
- **True branch** (output 0) → continues to the Groq LLM call
- **False branch** (output 1) → jumps to the error response node

### Node 4: **Groq - Code Review** (HTTP Request)
> *[Visual: Blue HTTP globe icon]*

Makes a `POST` request to `https://api.groq.com/openai/v1/chat/completions` with:
- Model: `llama-3.3-70b-versatile`
- Temperature: `0.1` (deterministic output)
- System prompt instructing the LLM to act as an expert code reviewer and return structured JSON
- User message containing the submitted code

### Node 5: **Parse LLM Response** (Code Node)
> *[Visual: Orange code icon]*

Extracts the assistant's message from the Groq response, strips any markdown code fences, parses the JSON, and determines the overall severity (`critical`, `warning`, `info`, or `clean`) based on the highest-severity issue found.

### Node 6: **Severity Router** (Switch Node)
> *[Visual: Blue switch/router icon with multiple outputs]*

Routes based on severity level:
- **Output 0 — "Critical"** → Deep Analysis node
- **Output 1 — "Warning"** → Format Final Report
- **Output 2 — "Clean"** → Format Final Report
- **Output 3 — "Info"** → Format Final Report

### Node 7: **Groq - Deep Analysis** (HTTP Request)
> *[Visual: Blue HTTP globe icon]*

Only triggered for **critical** severity. Makes a second LLM call with a security-focused prompt that asks for:
- Exploit scenarios with attack vectors and impact assessment
- Fix suggestions with before/after code
- Prioritized remediation actions

### Node 8: **Format Final Report** (Code Node)
> *[Visual: Orange code icon]*

Compiles everything into a structured JSON report matching the standard output format:
- Input metadata (language, code length, preview)
- Review (summary, severity, issues array, metrics)
- Deep analysis (if available)
- Metadata (model, tokens, engine)

### Node 9: **Respond - Success** (Respond to Webhook)
> *[Visual: Green response icon]*

Returns the final report as a JSON response with HTTP 200.

### Node 10: **Respond - Error** (Respond to Webhook)
> *[Visual: Red response icon]*

Returns a structured error message with HTTP 400 for invalid inputs.

---

## 7. Troubleshooting

### "Connection refused" when testing

- **Is n8n running?** Check that the n8n process/container is active.
- **Is the workflow active?** The toggle in the top-right must be green/ON.
- **Correct URL?** The production webhook is `/webhook/code-review`. The test webhook is `/webhook-test/code-review`.

### "Could not find credentials" error in n8n

- Open each HTTP Request node (Groq - Code Review, Groq - Deep Analysis)
- Re-select the "Groq API Key" credential from the dropdown
- Save the workflow

### Groq API returns 401 Unauthorized

- Verify the API key is correct in the credential settings
- Make sure the header name is `Authorization` and the value starts with `Bearer ` (note the space)
- Check your Groq API key hasn't expired at [console.groq.com](https://console.groq.com)

### Groq API returns 429 Too Many Requests

- Groq's free tier has rate limits. Wait 60 seconds and try again.
- If running all test cases, add a delay between requests in the test script.

### LLM response parsing fails

- The Parse LLM Response node handles markdown-wrapped JSON (```json blocks)
- If you still see parse errors, check the raw Groq response in the n8n execution log
- Temperature is set to 0.1 for consistency; raising it may cause more varied (and harder to parse) output

### Webhook returns empty response

- Check the n8n execution history (click the clock icon in the workflow editor)
- Look for errors in any node — red nodes indicate failures
- Verify the Respond to Webhook nodes are properly connected

### n8n runs out of memory

- For Docker: increase memory limit with `--memory=2g`
- Large code inputs may cause issues — the workflow doesn't enforce a size limit, but Groq's context window is finite

### Port 5678 is already in use

```bash
# Find and kill the process using port 5678
# Linux/Mac:
lsof -ti:5678 | xargs kill -9
# Windows:
netstat -ano | findstr :5678
taskkill /PID <PID> /F
```
