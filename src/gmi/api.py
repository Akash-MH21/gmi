"""Small HTTP client for GMI inference."""

import json
import sys
import time
from contextlib import contextmanager

import httpx

from . import __version__
from .config import GMIError


def _error_details(response):
    try:
        error = response.json().get("error", {})
    except (ValueError, TypeError):
        error = {}
    return error if isinstance(error, dict) else {}


def is_overloaded(response):
    error = _error_details(response)
    return error.get("type") == "service_unavailable" or "overloaded" in str(error.get("message", "")).lower()


def check_response(response, model="<unknown>"):
    status = response.status_code
    if status == 401:
        raise GMIError("API key rejected (401); run gmi auth login with a valid key.")
    if status == 429:
        if is_overloaded(response):
            raise GMIError(f"Model {model} is overloaded on GMI right now. Wait a minute and retry.")
        raise GMIError("Rate limit reached (429); wait and retry or check your quota.")
    if status == 404:
        raise GMIError(f"Model {model} was not found on GMI. Check the id with: gmi models --search <text>")
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


def _retry_after(response):
    value = response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else 0.0
    except ValueError:
        return 0.0


def _wait_retry(response, attempt, retry):
    if not retry or response.status_code != 429 or attempt >= 2:
        return False
    delay = min(_retry_after(response), 30.0)
    print(f"GMI returned 429; retrying in {delay:g}s.", file=sys.stderr)
    time.sleep(delay)
    return True


def complete(key, payload, retry=True):
    with client(key) as connection:
        for attempt in range(3):
            response = connection.post("chat/completions", json=payload)
            if response.status_code == 429 and _wait_retry(response, attempt, retry):
                continue
            check_response(response, payload.get("model", "<unknown>"))
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


def stream_events(key, payload, retry=True):
    """Yield complete stream chunks, including the API's usage event."""
    with client(key) as connection:
        for attempt in range(3):
            with connection.stream("POST", "chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    response.read()
                if response.status_code == 429 and _wait_retry(response, attempt, retry):
                    continue
                check_response(response, payload.get("model", "<unknown>"))
                for event in sse_events(response.iter_lines()):
                    if event == "[DONE]":
                        return
                    chunk = json.loads(event)
                    if "error" in chunk:
                        raise GMIError("GMI reported a stream error; retry or check your account quota.")
                    yield chunk
                return


def stream(key, payload, retry=True):
    for chunk in stream_events(key, payload, retry):
        for choice in chunk.get("choices", []):
            content = choice.get("delta", {}).get("content")
            if content:
                yield content
