import json

import pytest

from gmi.media import build_payload, filter_junk_ids, price_info, validate_payload, MediaClient
from gmi.config import GMIError


def test_junk_filter_and_price():
    assert filter_junk_ids(["ok", "capture/foo", "probe-x", "", "550e8400-e29b-41d4-a716-446655440000"]) == ["ok"]
    assert price_info({"price_info": {"price": 85000, "unit": "image"}}) == "$0.085 / image"


def test_schema_payload_and_validation():
    schema = {"parameters": [{"name": "text", "type": "string", "required": True}, {"name": "duration", "type": "integer", "required": False, "enum": [5, 10]}]}
    assert build_payload(schema, "ok", {"duration": "5"}) == {"text": "ok", "duration": 5}
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

