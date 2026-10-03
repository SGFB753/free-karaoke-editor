"""Small machine-local preferences, independent of the WebView session."""
import json
import os
import tempfile

ENGINES = ("auto", "qwen", "energy")


def timing_engine(root):
    try:
        with open(os.path.join(root, ".timing-engine.json"), encoding="utf-8") as stream:
            value = json.load(stream).get("engine")
        return value if value in ENGINES else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def save_timing_engine(root, engine):
    if engine not in ENGINES:
        raise ValueError("Unsupported timing engine")
    os.makedirs(root, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".timing-engine-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"engine": engine}, stream)
        os.replace(temporary, os.path.join(root, ".timing-engine.json"))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
