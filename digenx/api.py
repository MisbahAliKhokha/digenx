"""HTTP client for the Digen agent API (fresh implementation)."""

import json
import urllib.request
import urllib.parse
import urllib.error

GATEWAY_PREFIX = "/v2/gateway/agent"


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.code = code


def compose_token(token, user_id=None, expires_at=None):
    """Build the digen-token header value."""
    parts = [token]
    if user_id is not None:
        parts.append(str(user_id))
    if expires_at is not None:
        parts.append(str(expires_at))
    return ":".join(parts)


class DigenClient:
    def __init__(self, api_url, token=None, user_id=None,
                 session_id=None, language="en", token_expires_at=None,
                 timeout=60):
        self.base = api_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "digen-language": language or "en",
        }
        if token:
            self.headers["digen-token"] = compose_token(token, user_id, token_expires_at)
        if session_id:
            self.headers["digen-sessionid"] = session_id

    def _url(self, path):
        return f"{self.base}{GATEWAY_PREFIX}{path}"

    def _request(self, method, path, body=None, extra_headers=None, stream=False):
        url = self._url(path)
        headers = dict(self.headers)
        if extra_headers:
            headers.update(extra_headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise self._to_error(e)
        if stream:
            return resp
        raw = resp.read().decode("utf-8", errors="replace")
        if resp.status >= 400:
            raise self._to_error_raw(resp.status, raw)
        if not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        # API sometimes returns HTTP 200 with an error envelope
        if isinstance(parsed, dict) and parsed.get("errCode"):
            raise ApiError(resp.status, str(parsed.get("errMsg") or raw)[:500],
                           parsed.get("errCode"))
        return parsed

    def _to_error(self, e):
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return self._to_error_raw(e.code, raw)

    def _to_error_raw(self, status, raw):
        msg, code = raw, None
        try:
            obj = json.loads(raw) if raw else None
            if isinstance(obj, dict):
                m = obj.get("message")
                if isinstance(m, dict):
                    msg = m.get("message", raw)
                    code = m.get("code")
                else:
                    msg = obj.get("detail") or obj.get("message") or obj.get("errMsg") or raw
                    code = obj.get("errCode")
        except Exception:
            pass
        return ApiError(status, str(msg)[:500], code)

    # ---- workflows ----
    def list_workflows(self):
        return self._request("GET", "/public/v1/workflows") or []

    # ---- conversations ----
    def create_conversation(self, workflow, client_env=None):
        qs = urllib.parse.urlencode({"workflow": workflow})
        return self._request("POST", f"/api/v1/conversations?{qs}", body={
            "client_env": client_env or {},
        })

    def get_conversation(self, conv_id):
        return self._request("GET", f"/api/v1/conversations/{conv_id}")

    def list_conversations(self, limit=50, offset=0):
        qs = urllib.parse.urlencode({"limit": limit, "offset": offset})
        data = self._request("GET", f"/api/v1/conversations?{qs}")
        if isinstance(data, list):
            return data
        return (data or {}).get("items", [])

    def get_messages(self, conv_id, limit=None, before=None):
        qs = {}
        if limit:
            qs["limit"] = limit
        if before:
            qs["before"] = before
        suffix = ("?" + urllib.parse.urlencode(qs)) if qs else ""
        return self._request("GET", f"/api/v1/conversations/{conv_id}/messages{suffix}")

    def delete_conversation(self, conv_id):
        self._request("DELETE", f"/api/v1/conversations/{conv_id}")

    def rename_conversation(self, conv_id, name):
        self._request("PATCH", f"/api/v1/conversations/{conv_id}/name", body={"name": name})

    # ---- chat (streaming) ----
    def chat_stream(self, blocks, conversation_id, workflow):
        resp = self._request("POST", "/api/v1/chat", body={
            "blocks": blocks,
            "conversation_id": conversation_id,
            "workflow": workflow,
        }, stream=True)
        task_id = resp.headers.get("x-task-id")
        return task_id, resp

    def resume_stream(self, task_id, after_sequence=0):
        qs = urllib.parse.urlencode({"after_sequence": after_sequence})
        return self._request("GET", f"/api/v1/chat/resume/{task_id}?{qs}", stream=True)

    # ---- assets ----
    def presigned_urls(self, items):
        return self._request("POST", "/api/v1/assets/presigned-urls", body={"items": items})

    def presign_upload(self, conversation_id, filename, content_type):
        qs = urllib.parse.urlencode({"conversation_id": conversation_id})
        return self._request("POST", f"/api/v1/upload/presign?{qs}", body={
            "filename": filename, "content_type": content_type,
        })

    def upload_bytes(self, upload_url, data, content_type):
        req = urllib.request.Request(upload_url, data=data, method="PUT", headers={
            "Content-Type": content_type, "x-amz-acl": "public-read",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    raise ApiError(resp.status, f"upload failed: HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, f"upload failed: HTTP {e.code}")

    def register_asset(self, conversation_id, url, asset_type,
                       content_type=None, filename=None):
        return self._request(
            "POST", f"/api/v1/conversations/{conversation_id}/assets/upload",
            body={"url": url, "asset_type": asset_type,
                  "content_type": content_type, "filename": filename})

    # ---- tasks ----
    def get_task(self, task_id):
        return self._request("GET", f"/api/v1/tasks/{task_id}")

    def cancel_task(self, task_id):
        self._request("DELETE", f"/api/v1/tasks/{task_id}")

    def confirm_task(self, task_id, action):
        self._request("POST", f"/api/v1/tasks/{task_id}/countdown",
                      body={"action": action})
