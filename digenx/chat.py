"""Interactive chat REPL with SSE streaming and slash commands."""

import mimetypes
import os
import sys

from . import config
from .api import DigenClient, ApiError
from .sse import iter_response_events

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

HELP_TEXT = """Slash commands:
  /new                 Start a new conversation
  /switch <id>         Switch to an existing conversation
  /sessions            List your conversations
  /history             Print this conversation's history
  /workflow [name]     Show or change the workflow
  /attach <path>       Stage a local image to send with your next message
  /attachments         List staged images
  /detach [n|all]      Remove a staged image (default: all)
  /cancel              Cancel the currently running task
  /confirm             Confirm a pending await_confirmation prompt
  /set duration <sec>  Set video length in seconds (0 = no limit request)
  /set aspect <WxH>    Set frame size, e.g. 16:9, 9:16, 1:1, 1920x1080
  /help                Show this list
  /quit                Exit
Ctrl-C while streaming cancels the task; Ctrl-C/D at the prompt exits."""


def make_client():
    return DigenClient(
        api_url=config.api_url(),
        token=config.token(),
        user_id=config.user_id(),
        session_id=config.ensure_session_id(),
        language=config.language(),
        token_expires_at=config.token_expires_at(),
    )


def require_login(client):
    if not config.token():
        print("Not logged in. Run: digenx login")
        sys.exit(1)


def render_event(ev):
    """Turn a chat event into printable text lines."""
    etype = ev.get("type", "")
    lines = []
    if etype == "text":
        content = ev.get("content") or ""
        if content:
            lines.append(content)
    elif etype == "tool_call":
        tool = ev.get("tool") or "tool"
        phase = ev.get("phase")
        if phase == "start":
            lines.append(f"\n[tool] {tool} ...")
        elif phase == "end":
            lines.append(f"[tool] {tool} done")
    elif etype == "asset":
        data = ev.get("data") or {}
        url = data.get("url") or ev.get("content") or ""
        kind = (ev.get("agent") or "asset")
        name = data.get("filename") or url.rsplit("/", 1)[-1]
        lines.append(f"\n[asset] {name}: {url}")
    elif etype == "error":
        lines.append(f"\n[error] {ev.get('content') or ev.get('data')}")
    elif etype == "done":
        pass
    else:
        content = ev.get("content")
        if content:
            lines.append(str(content))
    return lines


class ChatSession:
    def __init__(self, client, conversation_id=None, workflow=None,
                 duration=None, aspect=None):
        self.client = client
        self.workflow = workflow or config.default_workflow()
        self.duration = duration or config.default_duration()
        self.aspect = aspect or config.default_aspect()
        self.conversation_id = conversation_id
        self.attachments = []  # list of dicts {path, asset}
        self.current_task = None
        if not self.conversation_id:
            self.new_conversation()

    def _client_env(self):
        env = {}
        if self.duration:
            env["duration"] = self.duration
            env["max_duration"] = self.duration
        if self.aspect:
            env["aspect_ratio"] = self.aspect
            env["frame_size"] = self.aspect
        return env

    def new_conversation(self):
        conv = self.client.create_conversation(self.workflow,
                                               self._client_env())
        self.conversation_id = conv.get("conversation_id")
        self.attachments = []
        extra = ""
        if self.duration:
            extra += f" | duration: {self.duration}s"
        if self.aspect:
            extra += f" | aspect: {self.aspect}"
        print(f"[new conversation: {self.conversation_id} | workflow: {self.workflow}{extra}]")

    def upload_attachment(self, path):
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            print(f"File not found: {path}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS:
            print(f"Only images supported ({', '.join(sorted(IMAGE_EXTS))})")
            return
        ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            data = f.read()
        print(f"Uploading {os.path.basename(path)} ...")
        presign = self.client.presign_upload(
            self.conversation_id,
            os.path.basename(path), ctype)
        self.client.upload_bytes(presign["upload_url"], data, ctype)
        asset = self.client.register_asset(
            self.conversation_id, presign["final_url"],
            "image", ctype, os.path.basename(path))
        self.attachments.append({"path": path, "asset": asset})
        print(f"Staged ({len(self.attachments)}).")

    def build_blocks(self, text):
        blocks = []
        for att in self.attachments:
            asset = att["asset"]
            blocks.append({"type": "image",
                           "content": asset.get("uri") or asset.get("url")})
        self.attachments = []
        if text:
            blocks.append({"type": "text", "content": text})
        return blocks

    def send(self, text):
        blocks = self.build_blocks(text)
        if not blocks:
            return
        task_id, resp = self.client.chat_stream(
            blocks, self.conversation_id, self.workflow)
        self.current_task = task_id
        last_seq = 0
        try:
            with resp:
                for ev in iter_response_events(resp):
                    last_seq = ev.get("sequence", last_seq)
                    for line in render_event(ev):
                        print(line, end="" if ev.get("type") == "text" else "\n",
                              flush=True)
                    status = ev.get("status")
                    if status in ("completed", "error", "cancelled"):
                        break
            print()
        except KeyboardInterrupt:
            print("\n[cancelling...]")
            if task_id:
                try:
                    self.client.cancel_task(task_id)
                except ApiError:
                    pass
            # try to resume to show partial output state
            if task_id and last_seq:
                try:
                    r2 = self.client.resume_stream(task_id, last_seq)
                    with r2:
                        for ev in iter_response_events(r2):
                            for line in render_event(ev):
                                print(line, end="" if ev.get("type") == "text" else "\n",
                                      flush=True)
                    print()
                except ApiError:
                    pass
        finally:
            self.current_task = None

    def handle_command(self, cmd):
        parts = cmd.strip().split(None, 1)
        name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if name == "/new":
            self.new_conversation()
        elif name == "/switch":
            if not arg:
                print("Usage: /switch <conversation_id>")
            else:
                self.conversation_id = arg.strip()
                self.attachments = []
                print(f"[switched to {self.conversation_id}]")
        elif name == "/sessions":
            for c in self.client.list_conversations():
                print(f"{c.get('conversation_id')}  [{c.get('workflow')}]  "
                      f"{c.get('name') or ''}  {c.get('updated_at') or ''}")
        elif name == "/history":
            msgs = self.client.get_messages(self.conversation_id, limit=50)
            items = msgs.get("items") if isinstance(msgs, dict) else msgs
            for m in items or []:
                role = m.get("role", "?")
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        b.get("content", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
                print(f"\n[{role}] {content}")
            print()
        elif name == "/workflow":
            if arg:
                self.workflow = arg.strip()
                print(f"[workflow: {self.workflow}]")
            else:
                print(f"[workflow: {self.workflow}]")
        elif name == "/attach":
            if not arg:
                print("Usage: /attach <path>")
            else:
                self.upload_attachment(arg.strip())
        elif name == "/attachments":
            for i, a in enumerate(self.attachments, 1):
                print(f"{i}. {a['path']}")
            if not self.attachments:
                print("(none)")
        elif name == "/detach":
            if not self.attachments:
                print("(none)")
            elif not arg or arg == "all":
                self.attachments = []
                print("Detached all.")
            else:
                try:
                    idx = int(arg) - 1
                    self.attachments.pop(idx)
                    print("Detached.")
                except (ValueError, IndexError):
                    print("Usage: /detach [n|all]")
        elif name == "/cancel":
            if self.current_task:
                self.client.cancel_task(self.current_task)
                print("[cancelled]")
            else:
                print("No running task.")
        elif name == "/confirm":
            if self.current_task:
                self.client.confirm_task(self.current_task, "confirm")
                print("[confirmed]")
            else:
                print("No pending task.")
        elif name == "/set":
            sub = arg.split(None, 1)
            if len(sub) < 2:
                print("Usage: /set duration <seconds> | /set aspect <WxH>")
                print(f"Current: duration={self.duration or 'not set'}, "
                      f"aspect={self.aspect or 'not set'}")
            elif sub[0] == "duration":
                try:
                    self.duration = int(sub[1])
                    print(f"[duration: {self.duration}s — applies to new conversations "
                          f"(/new)]")
                except ValueError:
                    print("Duration must be a number (seconds).")
            elif sub[0] == "aspect":
                self.aspect = sub[1].strip()
                print(f"[aspect: {self.aspect} — applies to new conversations (/new)]")
            else:
                print("Usage: /set duration <seconds> | /set aspect <WxH>")
        elif name == "/help":
            print(HELP_TEXT)
        elif name in ("/quit", "/exit"):
            raise EOFError
        else:
            print(f"Unknown command: {name}  (try /help)")
        return True

    def repl(self):
        print(HELP_TEXT.split("\n")[0])
        print("Type /help for commands. Ctrl-D to exit.\n")
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break
            if not line:
                continue
            if line.startswith("/"):
                try:
                    self.handle_command(line)
                except EOFError:
                    break
                continue
            try:
                self.send(line)
            except ApiError as e:
                print(f"[api error] {e}")


def run_chat(conversation_id=None, workflow=None, duration=None, aspect=None):
    client = make_client()
    require_login(client)
    session = ChatSession(client, conversation_id, workflow, duration, aspect)
    session.repl()
