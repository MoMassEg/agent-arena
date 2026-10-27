#!/usr/bin/env python3
"""
AI Agent Comparison Lab — Unified Interactive Web Dashboard
============================================================

Provides an immediate, rich browser-based UI to interact with all 3 agents:
  1. LangGraph Agent (Project 1)
  2. n8n Visual Workflow (Project 2)
  3. Hermes Autonomous Agent (Project 3)

Runs with zero external web dependencies using Python's standard library.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Ensure local python_libs is on path
_lib_dir = Path.home() / "python_libs"
if _lib_dir.exists() and str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_1_DIR = ROOT_DIR / "1_langgraph_agent"
PROJECT_2_DIR = ROOT_DIR / "2_n8n_agent"
PROJECT_3_DIR = ROOT_DIR / "3_hermes_agent"
SHARED_DIR = ROOT_DIR / "shared"

sys.path.insert(0, str(PROJECT_1_DIR))
sys.path.insert(0, str(PROJECT_2_DIR))
sys.path.insert(0, str(PROJECT_3_DIR))

# Import agent components
try:
    from agent import run_review as run_langgraph_review
except Exception as e:
    run_langgraph_review = None

try:
    from server import run_workflow_pipeline as run_n8n_pipeline
except Exception as e:
    run_n8n_pipeline = None

try:
    from agent_runner import GroqReviewClient, PersistentMemory
    from scheduled_reviewer import FileStateTracker, ReviewMemory, scan_directory
    from skills.code_review_skill import _static_code_analysis_impl as static_code_analysis
except Exception as e:
    logger.error("Hermes import error: %s", e)
    static_code_analysis = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("web_dashboard")

PORT = 8000
HTML_FILE = ROOT_DIR / "web_dashboard.html"

# Load .env if present
env_path = PROJECT_1_DIR / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Load shared test cases
def get_sample_cases() -> list[dict]:
    p = SHARED_DIR / "test_inputs.json"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Concise logging
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, data: dict | list, status=HTTPStatus.OK):
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, content: str):
        body = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            if HTML_FILE.exists():
                with open(HTML_FILE, "r", encoding="utf-8") as f:
                    self._send_html(f.read())
            else:
                self._send_html("<h1>Dashboard HTML not found</h1>")
            return

        if path == "/api/samples":
            self._send_json(get_sample_cases())
            return

        if path == "/api/hermes/memory":
            mem_file = PROJECT_3_DIR / "memory_store" / "review_history.json"
            if mem_file.exists():
                with open(mem_file, "r", encoding="utf-8") as f:
                    self._send_json(json.load(f))
            else:
                self._send_json([])
            return

        if path == "/api/status":
            import urllib.request
            n8n_online = False
            try:
                with urllib.request.urlopen("http://localhost:5678/healthz", timeout=1) as resp:
                    n8n_online = resp.status == 200
            except Exception:
                n8n_online = False

            self._send_json({
                "n8n_online": n8n_online,
                "n8n_url": "http://localhost:5678",
                "langgraph_ready": run_langgraph_review is not None,
                "hermes_ready": static_code_analysis is not None,
                "port": PORT,
            })
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        payload = {}
        if post_data:
            try:
                payload = json.loads(post_data.decode("utf-8"))
            except Exception:
                payload = {}

        if path == "/api/langgraph/review":
            code = payload.get("code", "")
            language = payload.get("language", "auto")
            model = payload.get("model", "openai/gpt-oss-120b")
            os.environ["GROQ_MODEL"] = model

            if not run_langgraph_review:
                self._send_json({"status": "error", "message": "LangGraph module not loaded"}, status=500)
                return

            try:
                t0 = time.time()
                report = run_langgraph_review(code, language=language)
                report["execution_time_seconds"] = round(time.time() - t0, 2)
                report["model"] = model
                self._send_json(report)
            except Exception as exc:
                logger.error("LangGraph error: %s", exc, exc_info=True)
                self._send_json({"status": "error", "message": str(exc)}, status=500)
            return

        if path == "/api/hermes/review":
            code = payload.get("code", "")
            language = payload.get("language", "auto")
            model = payload.get("model", "openai/gpt-oss-120b")

            try:
                t0 = time.time()
                static_res = static_code_analysis(code, language)
                findings = static_res["findings"]
                summary = static_res["summary"]

                # Persistent memory check
                mem = PersistentMemory(PROJECT_3_DIR / "memory_store" / "review_history.json")
                past_reviews = mem.recall("review_history", default=[])
                
                # Check recurring
                recurring_count = sum(1 for r in past_reviews if r.get("severity") == summary["overall_severity"] and summary["overall_severity"] == "critical")

                # Call Groq LLM
                client = GroqReviewClient(
                    api_key=os.getenv("GROQ_API_KEY", ""),
                    model=model,
                    base_url="https://api.groq.com/openai/v1"
                )
                review_text = client.review_code(code, language, findings, past_reviews=past_reviews)

                # Persist to memory
                new_entry = {
                    "test_name": payload.get("name", "User Submission"),
                    "language": language,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "severity": summary["overall_severity"],
                    "issue_count": summary["total_issues"],
                    "findings": findings,
                    "review": review_text[:300] + "...",
                }
                mem.append("review_history", new_entry)
                sess = mem.recall("session_count", default=0) + 1
                mem.store("session_count", sess)

                self._send_json({
                    "status": "success",
                    "execution_time_seconds": round(time.time() - t0, 2),
                    "model": model,
                    "static_analysis": static_res,
                    "persistent_memory": {
                        "total_stored_reviews": len(past_reviews) + 1,
                        "recurring_critical_count": recurring_count,
                    },
                    "llm_review": review_text,
                })
            except Exception as exc:
                logger.error("Hermes error: %s", exc, exc_info=True)
                self._send_json({"status": "error", "message": str(exc)}, status=500)
            return

        if path == "/api/hermes/clear-memory":
            mem_file = PROJECT_3_DIR / "memory_store" / "review_history.json"
            if mem_file.exists():
                mem_file.unlink()
            self._send_json({"status": "cleared"})
            return

        if path == "/api/hermes/scan":
            try:
                watch_dir = PROJECT_3_DIR / "code_to_review"
                sched_mem = ReviewMemory(PROJECT_3_DIR / "memory_store" / "scheduled_reviews.json")
                tracker = FileStateTracker(PROJECT_3_DIR / "memory_store" / "file_hashes.json")
                count = scan_directory(watch_dir, tracker, sched_mem, use_llm=True)
                self._send_json({"status": "success", "files_reviewed": count})
            except Exception as exc:
                self._send_json({"status": "error", "message": str(exc)}, status=500)
            return

        if path == "/api/n8n/test":
            import urllib.request
            import urllib.error
            url = payload.get("url", "http://localhost:5678/webhook/code-review")
            test_payload = payload.get("payload", {})
            code = test_payload.get("code", "")
            language = test_payload.get("language", "")
            
            # 1. Try real n8n webhook
            n8n_succeeded = False
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(test_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res_body = resp.read().decode("utf-8")
                    try:
                        self._send_json(json.loads(res_body))
                        n8n_succeeded = True
                    except Exception:
                        self._send_json({"raw": res_body})
                        n8n_succeeded = True
            except urllib.error.HTTPError as he:
                try:
                    err_body = he.read().decode("utf-8")
                    err_json = json.loads(err_body)
                    # If n8n returned a structured validation error response, send it
                    if "status" in err_json or "error" in err_json:
                        self._send_json(err_json, status=he.code)
                        n8n_succeeded = True
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("n8n webhook direct request failed: %s", exc)

            if not n8n_succeeded:
                # 2. Fallback to direct n8n DAG workflow execution
                if run_n8n_pipeline:
                    try:
                        report, status_code, steps = run_n8n_pipeline(code, language)
                        self._send_json(report, status=status_code)
                    except Exception as pipe_err:
                        self._send_json({"status": "error", "message": str(pipe_err)}, status=500)
                else:
                    self._send_json({"status": "error", "message": "n8n workflow runner unavailable"}, status=502)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def start_server(port=PORT):
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    logger.info("Serving AI Agent Comparison Lab Dashboard on http://localhost:%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    start_server(PORT)
