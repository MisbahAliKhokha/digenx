"""Minimal SSE (Server-Sent Events) parser for the chat stream."""

import json


def parse_sse_lines(line_iter):
    """Yield parsed JSON dicts from SSE `data:` lines."""
    buf = []
    for line in line_iter:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.rstrip("\r\n")
        if line == "":
            if buf:
                payload = "".join(buf)
                buf = []
                if payload.strip():
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        pass
            continue
        if line.startswith(":"):
            continue  # comment / heartbeat
        if line.startswith("data:"):
            buf.append(line[5:].lstrip(" "))
        # ignore other fields (event:, id:, retry:)
    if buf:
        try:
            yield json.loads("".join(buf))
        except json.JSONDecodeError:
            pass


def iter_response_events(resp, chunk_size=8192):
    """Yield chat events from an open urllib response object."""
    leftover = b""

    def gen():
        nonlocal leftover
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            data = leftover + chunk
            *lines, leftover = data.split(b"\n")
            for ln in lines:
                yield ln + b"\n"
        if leftover:
            yield leftover

    yield from parse_sse_lines(gen())
