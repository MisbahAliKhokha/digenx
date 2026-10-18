"""digenx — apna Digen agent CLI (fresh implementation, same features)."""

import argparse
import sys

from . import config
from .api import DigenClient, ApiError
from .auth import loopback_login
from .chat import run_chat
from .mcp import serve as mcp_serve

VERSION = "0.1.0"


def make_client():
    return DigenClient(
        api_url=config.api_url(),
        token=config.token(),
        user_id=config.user_id(),
        session_id=config.ensure_session_id(),
        language=config.language(),
        token_expires_at=config.token_expires_at(),
    )


def cmd_login(args):
    if args.token:
        config.save_login(args.token)
        print("Token saved.")
        return
    if args.manual:
        url = f"{config.login_url().rstrip('/')}/cli/login?hint=digenx"
        print("Open this URL, log in, then paste the token:\n  " + url)
        token = input("token: ").strip()
        if token:
            config.save_login(token)
            print("Saved.")
        return
    result = loopback_login(config.login_url())
    if not result:
        print("Login timed out.")
        sys.exit(1)
    uid = None
    try:
        uid = int(result["id"]) if result.get("id") else None
    except (ValueError, TypeError):
        pass
    config.save_login(result["token"], user_id=uid, name=result.get("name"),
                      email=result.get("email"), session_id=result.get("sessionid"))
    print(f"Logged in as {result.get('name') or result.get('email') or 'user'}.")


def cmd_logout(args):
    config.clear_login()
    print("Logged out.")


def cmd_whoami(args):
    cfg = config.load()
    if not cfg.get("token"):
        print("Not logged in.")
        return
    print(f"name:  {cfg.get('name') or '-'}")
    print(f"email: {cfg.get('email') or '-'}")
    print(f"user_id: {cfg.get('user_id') or '-'}")


def cmd_config(args):
    if args.action == "show":
        cfg = config.load()
        for k in ("api_url", "login_url", "default_workflow", "language",
                  "default_duration", "default_aspect",
                  "name", "email", "user_id"):
            print(f"{k}: {cfg.get(k) or '(default)'}")
    elif args.action == "set-api":
        config.set_value("api_url", args.value)
        print(f"api_url = {args.value}")
    elif args.action == "set-login-url":
        config.set_value("login_url", args.value)
        print(f"login_url = {args.value}")
    elif args.action == "set-workflow":
        config.set_value("default_workflow", args.value)
        print(f"default_workflow = {args.value}")
    elif args.action == "set-duration":
        config.set_value("default_duration", int(args.value))
        print(f"default_duration = {args.value} seconds")
    elif args.action == "set-aspect":
        config.set_value("default_aspect", args.value)
        print(f"default_aspect = {args.value}")


def cmd_workflows(args):
    client = make_client()
    for w in client.list_workflows():
        name = w.get("name")
        disp = w.get("display_name") or ""
        print(f"{name}  {disp}")


def cmd_chat(args):
    run_chat(conversation_id=args.conversation, workflow=args.workflow,
             duration=args.duration, aspect=args.aspect)


def cmd_sessions(args):
    client = make_client()
    for c in client.list_conversations(limit=args.limit):
        print(f"{c.get('conversation_id')}  [{c.get('workflow')}]  "
              f"{c.get('name') or ''}  {c.get('updated_at') or ''}")


def cmd_history(args):
    client = make_client()
    msgs = client.get_messages(args.conversation_id, limit=args.limit)
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


def cmd_delete(args):
    client = make_client()
    client.delete_conversation(args.conversation_id)
    print("Deleted.")


def cmd_mcp(args):
    mcp_serve()


def build_parser():
    p = argparse.ArgumentParser(prog="digenx",
                                description="Apna Digen agent CLI — chat with Digen agents from the terminal.")
    p.add_argument("--version", action="version", version=f"digenx {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("login", help="Log in and save credentials")
    s.add_argument("--token", help="Save this token directly")
    s.add_argument("--manual", action="store_true",
                   help="Print login URL and paste the token manually")
    s.set_defaults(fn=cmd_login)

    s = sub.add_parser("logout", help="Clear saved credentials")
    s.set_defaults(fn=cmd_logout)

    s = sub.add_parser("whoami", help="Show the current logged-in identity")
    s.set_defaults(fn=cmd_whoami)

    s = sub.add_parser("config", help="Show or change configuration")
    s.add_argument("action", choices=["show", "set-api", "set-login-url",
                                      "set-workflow", "set-duration", "set-aspect"])
    s.add_argument("value", nargs="?")
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("workflows", help="List available workflows")
    s.set_defaults(fn=cmd_workflows)

    s = sub.add_parser("chat", help="Start an interactive chat session")
    s.add_argument("-w", "--workflow", default=None)
    s.add_argument("-c", "--conversation", default=None)
    s.add_argument("--duration", type=int, default=None,
                   help="Video length in seconds (sent as preference)")
    s.add_argument("--aspect", default=None,
                   help="Frame size, e.g. 16:9, 9:16, 1:1, 1920x1080")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("sessions", help="List your conversations")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_sessions)

    s = sub.add_parser("history", help="Print a conversation's message history")
    s.add_argument("conversation_id")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("delete", help="Delete a conversation")
    s.add_argument("conversation_id")
    s.set_defaults(fn=cmd_delete)

    s = sub.add_parser("mcp", help="Run as an MCP server over stdio")
    s.set_defaults(fn=cmd_mcp)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except ApiError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
