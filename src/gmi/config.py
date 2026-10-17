"""Read credentials and save them with private permissions."""

import json
import os
from pathlib import Path
import tempfile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


class GMIError(Exception):
    """A safe, actionable error that can be shown to the user."""


def config_path():
    return Path.home() / ".config" / "gmi" / "config.toml"


def read_key():
    try:
        with config_path().open("rb") as handle:
            key = tomllib.load(handle).get("api_key")
        if key is not None and not isinstance(key, str):
            raise GMIError("Invalid config; run gmi auth login --stdin to replace it.")
        return key
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise GMIError("Cannot read config; run gmi auth login --stdin to replace it.") from None


def resolve_key(flag=None):
    key = flag or os.environ.get("GMI_API_KEY") or read_key()
    if not key or not key.strip():
        raise GMIError("Missing API key; run gmi auth login or set GMI_API_KEY.")
    return key.strip()


def mask_key(key):
    return "gmi_..." + (key[-4:] if len(key) > 8 else "****")


def save_key(key):
    path = config_path()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".config-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # JSON string escaping is compatible with TOML basic strings.
            handle.write("api_key = " + json.dumps(key, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    except OSError:
        raise GMIError("Cannot save credentials; check permissions on ~/.config/gmi.") from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
