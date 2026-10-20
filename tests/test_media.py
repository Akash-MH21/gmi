import json

import pytest

from gmi.media import (build_payload, default_model, extract_urls, filter_junk_ids,
                       price_info, validate_payload, MediaClient)
from gmi.config import GMIError


def test_junk_filter_and_price():
    assert filter_junk_ids(["ok", "capture/foo", "probe-x", "hunt", "bypass", "", "550e8400-e29b-41d4-a716-446655440000"]) == ["ok"]
    for unit, expected in [("image", "$0.085 / image"), ("second", "$0.022 / second"), ("character", "$0.005 / character"), ("request", "$0.001 / request")]:
        assert price_info({"price_info": {"price": {"image": 85000, "second": 22000, "character": 5000, "request": 1000}[unit], "unit": unit}}) == expected


def test_qworkers_filter_and_default_choice():
    base = {"model_type": "image", "status": "active", "qworkers": 1, "model_metadata": {}, "modalities": {"output": [{"type": "image"}]}, "parameters": [{"name": "prompt", "required": True}], "price_info": {"price": 2}}
    dead = {**base, "model": "dead", "qworkers": 0}
    cheap = {**base, "model": "cheap", "price_info": {"price": 1}}
    assert not __import__("gmi.media", fromlist=["usable"]).usable(dead, "image")
    assert default_model([dead, cheap], "image")["model"] == "cheap"


def test_schema_payload_and_validation():
    schema = {"parameters": [{"name": "text", "type": "string", "required": True}, {"name": "duration", "type": "integer", "required": False, "options": [{"value": 5, "display_name": "five"}]}, {"name": "voice", "type": "string", "required": True, "default_value": "alloy"}]}
    assert build_payload(schema, "ok", {"duration": "5"}) == {"text": "ok", "duration": 5, "voice": "alloy"}
    with pytest.raises(GMIError, match="Valid values"):
        build_payload(schema, "ok", {"duration": "7"})


def test_poll_state_machine(tmp_path):
    class Fake:
        def __init__(self): self.states = iter([{"status": "dispatched"}, {"status": "processing"}, {"status": "success", "outcome": {}}])
        def get(self, path):
            class R:
                status_code = 200
                def json(inner): return next(fake.states)
            fake = self
            return R()
    client = MediaClient("key", transport=Fake())
    assert client.poll("id", sleep=lambda _: None)["status"] == "success"


@pytest.mark.parametrize("outcome,expected", [
    ({"media_urls": [{"id": "0", "url": "https://x/a.jpg"}], "thumbnail_image_url": "https://x/a.jpg"}, ["https://x/a.jpg"]),
    ({"audio_url": "https://x/a.mp3", "media": [{"url": "https://x/a.mp3"}], "media_urls": [{"url": "https://x/a.mp3"}], "medias": [{"url": "https://x/a.mp3"}]}, ["https://x/a.mp3"]),
    ({"video_url": "https://x/a.mp4", "thumbnail_image_url": "https://x/a.jpg"}, ["https://x/a.mp4"]),
])
def test_outcome_urls(outcome, expected):
    assert extract_urls(outcome) == expected

