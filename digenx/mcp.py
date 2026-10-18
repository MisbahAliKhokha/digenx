"""Minimal MCP server over stdio (JSON-RPC), exposing Digen tools.

Tools: digen_send, digen_poll, digen_confirm, digen_cancel,
       digen_list_workflows, digen_history
"""

import json
import sys
import threading
import time

from . import config
from .api import DigenClient, ApiError
from .sse import iter_response_events

SERVER_INFO = {"name": "digenx", "version": "0.1.0"}

# task_id -> {"events": [...], "status": str, "thread": Thread}
TASKS = {}
TASKS_LOCK = threading.Lock()
_task_counter = [0]


def make_client():
    return DigenClient(
        api_url=config.api_url(),
        token=config.token(),
        user_id=config.user_id(),
        session_id=config.ensure_session_id(),
        language=config.language(),
        token_expires_at=config.token_expires_at(),
    )


def _new_task_id():
    _task_counter[0] += 1
    return f"local_{int(time.time())}_{_task_counter[0]}"


def _run_send(task_id, client, workflow, conversation_id, text, image_urls):
    """Background worker: stream chat events into TASKS[task_id]."""
    entry = TASKS[task_id]
    try:
        if not conversation_id:
            conv = client.create_conversation(workflow)
            conversation_id = conv.get("conversation_id")
            entry["conversation_id"] = conversation_id
        blocks = []
        for u in image_urls or []:
            blocks.append({"type": "image", "content": u})
        if text:
            blocks.append({"type": "text", "content": text})
        real_task_id, resp = client.chat_stream(blocks, conversation_id, workflow)
        entry["remote_task_id"] = real_task_id
        with resp:
            for ev in iter_response_events(resp):
                entry["events"].append(ev)
                if ev.get("status") in ("completed", "error", "cancelled"):
                    entry["status"] = ev["status"]
                    break
            else:
                entry["status"] = "done"
    except ApiError as e:
        entry["status"] = "error"
        entry["events"].append({"type": "error", "content": str(e)})
    except Exception as e:  # noqa: BLE001
        entry["status"] = "error"
        entry["events"].append({"type": "error", "content": f"{type(e).__name__}: {e}"})


def tool_send(args):
    client = make_client()
    workflow = args.get("workflow") or config.default_workflow()
    task_id = _new_task_id()
    entry = {"events": [], "status": "running", "conversation_id": args.get("conversation_id")}
    TASKS[task_id] = entry
    t = threading.Thread(target=_run_send, args=(
        task_id, client, workflow, args.get("conversation_id"),
        args.get("text", ""), args.get("image_urls")), daemon=True)
    t.start()
    entry["thread"] = t
    return {"task_id": task_id,
            "conversation_id": entry["conversation_id"],
            "status": "running",
            "hint": "poll with digen_poll"}


def tool_poll(args):
    task_id = args.get("task_id")
    entry = TASKS.get(task_id)
    if not entry:
        return {"error": f"unknown task_id: {task_id}"}
    since = int(args.get("since", 0) or 0)
    events = entry["events"][since:]
    return {"task_id": task_id,
            "status": entry["status"],
            "conversation_id": entry.get("conversation_id"),
            "next_index": since + len(events),
            "events": events}


def tool_confirm(args):
    client = make_client()
    task_id = args.get("task_id")
    entry = TASKS.get(task_id)
    remote = (entry or {}).get("remote_task_id") or task_id
    action = args.get("action", "confirm")
    client.confirm_task(remote, action)
    return {"task_id": task_id, "action": action, "ok": True}


def tool_cancel(args):
    client = make_client()
    task_id = args.get("task_id")
    entry = TASKS.get(task_id)
    remote = (entry or {}).get("remote_task_id") or task_id
    try:
        client.cancel_task(remote)
    except ApiError:
        pass
    if entry:
        entry["status"] = "cancelled"
    return {"task_id": task_id, "ok": True}


def tool_list_workflows(args):
    client = make_client()
    return {"workflows": client.list_workflows()}


def tool_history(args):
    client = make_client()
    conv_id = args.get("conversation_id")
    msgs = client.get_messages(conv_id, limit=args.get("limit", 50))
    return {"conversation_id": conv_id, "messages": msgs}


TOOLS = {
    "digen_send": {
        "fn": tool_send,
        "desc": "Send a message to a Digen workflow; returns a task_id immediately. "
                "Poll with digen_poll until status is done/error/cancelled.",
        "schema": {"type": "object",
                   "properties": {
                       "text": {"type": "string"},
                       "workflow": {"type": "string"},
                       "conversation_id": {"type": "string"},
                       "image_urls": {"type": "array", "items": {"type": "string"}}},
                   "required": ["text"]},
    },
    "digen_poll": {
        "fn": tool_poll,
        "desc": "Check a task's status/output. Call repeatedly until done/error/cancelled.",
        "schema": {"type": "object",
                   "properties": {"task_id": {"type": "string"},
                                  "since": {"type": "integer"}},
                   "required": ["task_id"]},
    },
    "digen_confirm": {
        "fn": tool_confirm,
        "desc": "Confirm or cancel a task awaiting confirmation.",
        "schema": {"type": "object",
                   "properties": {"task_id": {"type": "string"},
                                  "action": {"type": "string",
                                             "enum": ["confirm", "cancel"]}},
                   "required": ["task_id"]},
    },
    "digen_cancel": {
        "fn": tool_cancel,
        "desc": "Cancel a running task.",
        "schema": {"type": "object",
                   "properties": {"task_id": {"type": "string"}},
                   "required": ["task_id"]},
    },
    "digen_list_workflows": {
        "fn": tool_list_workflows,
        "desc": "List available Digen workflows.",
        "schema": {"type": "object", "properties": {}},
    },
    "digen_history": {
        "fn": tool_history,
        "desc": "Fetch a conversation's message history.",
        "schema": {"type": "object",
                   "properties": {"conversation_id": {"type": "string"},
                                  "limit": {"type": "integer"}},
                   "required": ["conversation_id"]},
    },
}


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def handle(msg):
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": [
            {"name": n, "description": t["desc"], "inputSchema": t["schema"]}
            for n, t in TOOLS.items()]})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return _err(req_id, -32602, f"unknown tool: {name}")
        try:
            result = tool["fn"](args)
            return _ok(req_id, {"content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        except ApiError as e:
            return _ok(req_id, {"content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}],
                "isError": True})
        except Exception as e:  # noqa: BLE001
            return _err(req_id, -32603, f"{type(e).__name__}: {e}")
    return _err(req_id, -32601, f"method not found: {method}")


def serve():
    stdin = sys.stdin
    stdout = sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
