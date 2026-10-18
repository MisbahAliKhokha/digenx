"""Config file handling. Same file/format as the reference CLI (~/.digen/cli.yaml)
so credentials transfer between tools."""

import os
import uuid

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_API_URL = "https://api.digen.ai"
DEFAULT_LOGIN_URL = "https://agent.digen.ai"
DEFAULT_WORKFLOW = "skill_agent"

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".digen")
CONFIG_FILE = os.path.join(CONFIG_DIR, "cli.yaml")


def _ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load():
    _ensure_dirs()
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) if yaml else {}
    return data or {}


def save(cfg):
    _ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        if yaml:
            yaml.safe_dump(cfg, f, default_flow_style=False)
        else:
            for k, v in cfg.items():
                f.write(f"{k}: {v}\n")


def get(key, default=None):
    return load().get(key, default)


def set_value(key, value):
    cfg = load()
    cfg[key] = value
    save(cfg)


def api_url():
    return get("api_url") or DEFAULT_API_URL


def login_url():
    return get("login_url") or DEFAULT_LOGIN_URL


def token():
    return get("token")


def user_id():
    v = get("user_id")
    return None if v is None else int(v)


def token_expires_at():
    v = get("token_expires_at")
    return None if v is None else int(v)


def language():
    return get("language") or "en"


def default_workflow():
    return get("default_workflow") or DEFAULT_WORKFLOW


def default_duration():
    v = get("default_duration")
    return None if v is None else int(v)


def default_aspect():
    return get("default_aspect")


def session_id():
    return get("session_id")


def ensure_session_id():
    sid = session_id()
    if sid:
        return sid
    sid = str(uuid.uuid4())
    set_value("session_id", sid)
    return sid


def save_login(token, user_id=None, name=None, email=None,
               language=None, session_id=None, token_expires_at=None):
    cfg = load()
    cfg["token"] = token
    cfg["session_id"] = session_id or cfg.get("session_id") or str(uuid.uuid4())
    if user_id is not None:
        cfg["user_id"] = user_id
    if name:
        cfg["name"] = name
    if email:
        cfg["email"] = email
    if language:
        cfg["language"] = language
    if token_expires_at is not None:
        cfg["token_expires_at"] = token_expires_at
    save(cfg)


def clear_login():
    cfg = load()
    for k in ("token", "user_id", "name", "email",
              "language", "session_id", "token_expires_at"):
        cfg.pop(k, None)
    save(cfg)
