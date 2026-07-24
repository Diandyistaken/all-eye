"""Minik HTTP katmani - stdlib urllib uzerine SSE/NDJSON akisi.

Bagimlilik eklememek bilincli: arka planda surekli duran bir surecin
60-80 MB'da kalmasi icin her paket sayiliyor.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status}: {_api_message(body) or body[:200]}")
        self.status = status
        self.body = body
        self.message = _api_message(body) or body[:200]


def _api_message(body: str) -> str:
    """Saglayici JSON hatasindan okunabilir mesaji cikar."""
    try:
        err = json.loads(body).get("error")
    except (json.JSONDecodeError, AttributeError):
        return ""
    if isinstance(err, dict):
        return str(err.get("message", ""))
    return str(err or "")


def _request(url: str, payload: dict, headers: dict, timeout: float):
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "text/event-stream", **headers}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise HttpError(exc.code, body, url) from None
    except urllib.error.URLError as exc:
        raise HttpError(0, str(exc.reason), url) from None


def stream_sse(url: str, payload: dict, headers: dict, timeout: float = 45.0) -> Iterator[dict]:
    """`data: {...}` satirlarini cozup akitir (Gemini, Groq/OpenAI uyumlu)."""
    with _request(url, payload, headers, timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                return
            try:
                yield json.loads(chunk)
            except json.JSONDecodeError:
                continue


def stream_ndjson(url: str, payload: dict, headers: dict, timeout: float = 300.0) -> Iterator[dict]:
    """Satir basina bir JSON (Ollama)."""
    with _request(url, payload, headers, timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def get_json(url: str, timeout: float = 3.0) -> dict | list:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - erisilebilirlik testi, sebebi onemsiz
        raise HttpError(0, str(exc), url) from None
