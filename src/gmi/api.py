"""Small HTTP client for GMI inference."""

import json
from contextlib import contextmanager

import httpx

from . import __version__
from .config import GMIError


def check_response(response):
    status = response.status_code
    if status == 401:
        raise GMIError("API key rejected (401); run gmi auth login with a valid key.")
    if status == 429:
        raise GMIError("Rate limit reached (429); wait and retry or check your quota.")
    if status >= 400:
        raise GMIError(f"GMI API returned HTTP {status}; check your request and account access.")


@contextmanager
def client(key):
    try:
        with httpx.Client(
            base_url="https://api.gmi-serving.com/v1/",
            headers={"Authorization": f"Bearer {key}", "User-Agent": f"gmi-cli/{__version__}"},
            timeout=httpx.Timeout(120, connect=15),
        ) as connection:
            yield connection
    except httpx.RequestError:
        raise GMIError("Network request failed; check your connection and retry.") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise GMIError("Invalid response from GMI; retry the request.") from None


def models(key):
    with client(key) as connection:
        response = connection.get("models")
        check_response(response)
        return response.json()


def complete(key, payload):
    with client(key) as connection:
        response = connection.post("chat/completions", json=payload)
        check_response(response)
        return response.json()


def sse_events(lines):
    """Decode SSE data fields, including multiline events and keepalives."""
    data = []
    for line in lines:
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield "\n".join(data)


def stream(key, payload):
    with client(key) as connection:
        with connection.stream("POST", "chat/completions", json=payload) as response:
            check_response(response)
            for event in sse_events(response.iter_lines()):
                if event == "[DONE]":
                    return
                chunk = json.loads(event)
                if "error" in chunk:
                    raise GMIError("GMI reported a stream error; retry or check your account quota.")
                for choice in chunk.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if content:
                        yield content
