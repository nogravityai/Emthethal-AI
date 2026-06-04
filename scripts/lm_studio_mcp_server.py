#!/usr/bin/env python3
"""
LM Studio MCP Server — stdio transport, zero external dependencies.
Exposes the local LM Studio model as a tool callable by Antigravity.

Protocol: MCP over stdio (JSON-RPC 2.0)
Run via: wsl python3 scripts/lm_studio_mcp_server.py
"""
import sys
import json
import os
import subprocess
import urllib.request
import urllib.error

# ── Config ────────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("LM_STUDIO_PORT", "12345"))
HOST = os.environ.get("LM_STUDIO_HOST", "")  # set to LAN IP e.g. 192.168.1.104

# ── LM Studio connection ───────────────────────────────────────────────────────
def get_gateway_ip():
    """Get Windows host IP from WSL perspective."""
    # Try /etc/hosts first (WSL2 adds host.docker.internal)
    try:
        with open("/etc/hosts") as f:
            for line in f:
                if "host.docker.internal" in line or "host.wsl.internal" in line:
                    ip = line.split()[0]
                    if ip and not ip.startswith("#"):
                        return ip
    except Exception:
        pass
    # Fallback: parse ip route
    try:
        routes = subprocess.check_output(["ip", "route"]).decode()
        for line in routes.splitlines():
            if line.startswith("default via"):
                return line.split()[2]
    except Exception:
        pass
    return "127.0.0.1"

def call_lm_studio(prompt: str, system_prompt: str = "") -> str:
    # Use explicit host if set, otherwise auto-detect WSL gateway
    if HOST:
        host = HOST
    else:
        host = get_gateway_ip()
    urls = [f"http://{host}:{PORT}/v1/chat/completions"]

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": "local-model",
        "messages": messages,
        "temperature": 0.3,
        "stream": False
    }).encode("utf-8")

    last_error = None
    for url in urls:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
        except urllib.error.URLError as e:
            last_error = str(e.reason)

    return f"ERROR: Cannot reach LM Studio on port {PORT}. Details: {last_error}"

# ── MCP Protocol Handlers ──────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "map_file",
        "description": (
            "Send a large code file (800+ lines) to the local LM Studio model for structural mapping. "
            "Returns: classes, functions, data flow, and the top 3 most complex functions to review manually. "
            "DO NOT use for files under 400 lines — read those directly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the code file to map."
                },
                "question": {
                    "type": "string",
                    "description": "Optional specific question about the file structure.",
                    "default": "Map this file."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "query_local_model",
        "description": (
            "Send any prompt to the local LM Studio model. "
            "Best for: high-level architectural questions, brainstorming, or summarizing large content "
            "that would flood the primary agent's context. "
            "NOT reliable for: exact line numbers, bug detection, or variable names."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question or instruction to send to the local model."
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system prompt to configure model behavior.",
                    "default": ""
                }
            },
            "required": ["prompt"]
        }
    }
]

CARTOGRAPHER_SYSTEM = """You are a File Cartographer. Your ONLY job is to produce a structural map.

STRICT RULES:
1. DO NOT give line numbers.
2. DO NOT say "no bugs found", "code is correct", "robust", or "well-handled".
3. DO NOT invent functions or classes not present in the file.
4. If a function's purpose is unclear, write: "purpose unclear — flag for manual review".
5. Keep every description under 15 words.

OUTPUT FORMAT (follow exactly):

## Classes
<ClassName> — <one sentence, max 15 words>

## Functions
<function_name> — <one sentence, max 15 words> [Low/Medium/High]

## Data Flow
<input> → <transformation> → <output>

## Manual Review Priority
1. <function_name> — <why complex, max 10 words>
2. <function_name> — <why>
3. <function_name> — <why>

REMINDER: Output only the 4 sections. No intro, no conclusion, no disclaimers."""


def handle_tool_call(name: str, arguments: dict) -> str:
    if name == "map_file":
        file_path = arguments.get("file_path", "")
        question = arguments.get("question", "Map this file.")

        # Read the file
        if not os.path.isabs(file_path):
            # Try relative to project root
            candidates = [
                file_path,
                os.path.join("/home/hya/emthethal-ai", file_path),
            ]
        else:
            candidates = [file_path]

        content = None
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    file_path = path
                    break
                except Exception as e:
                    return f"ERROR reading file: {e}"

        if content is None:
            return f"ERROR: File not found: {arguments.get('file_path')}"

        lines = len(content.splitlines())
        size_kb = len(content) / 1024

        prompt = f"Here is the content of '{os.path.basename(file_path)}' ({lines} lines, {size_kb:.1f}KB):\n\n```\n{content}\n```\n\n{question}"
        result = call_lm_studio(prompt, CARTOGRAPHER_SYSTEM)

        return f"[File: {file_path} | {lines} lines | {size_kb:.1f}KB]\n\n{result}"

    elif name == "query_local_model":
        prompt = arguments.get("prompt", "")
        system_prompt = arguments.get("system_prompt", "")
        return call_lm_studio(prompt, system_prompt)

    return f"ERROR: Unknown tool '{name}'"


# ── MCP stdio loop ─────────────────────────────────────────────────────────────
def send(obj: dict):
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

def run():
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        # ── initialize ──
        if method == "initialize":
            send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "lm-studio-mcp", "version": "1.0.0"}
                }
            })

        # ── tools/list ──
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": TOOLS}
            })

        # ── tools/call ──
        elif method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            result_text = handle_tool_call(tool_name, arguments)

            send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                    "isError": result_text.startswith("ERROR")
                }
            })

        # ── notifications (no response needed) ──
        elif method.startswith("notifications/"):
            pass

        # ── unknown ──
        elif msg_id is not None:
            send({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            })

if __name__ == "__main__":
    run()
