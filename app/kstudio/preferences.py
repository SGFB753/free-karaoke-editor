"""Small machine-local preferences, independent of the WebView session."""
import json
import os
import tempfile

ENGINES = ("auto", "qwen", "energy")


def _timing_settings(root):
    try:
        with open(os.path.join(root, ".timing-engine.json"), encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def timing_engine(root):
    value = _timing_settings(root).get('engine')
    return value if value in ENGINES else None


def whisper_review(root):
    return _timing_settings(root).get('whisperReview') is not False


def save_timing_engine(root, engine, whisper_review=None):
    if engine not in ENGINES:
        raise ValueError("Unsupported timing engine")
    os.makedirs(root, exist_ok=True)
    settings = _timing_settings(root)
    settings['engine'] = engine
    if whisper_review is not None:
        if not isinstance(whisper_review, bool):
            raise ValueError('whisperReview must be boolean')
        settings['whisperReview'] = whisper_review
    fd, temporary = tempfile.mkstemp(prefix=".timing-engine-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(settings, stream)
        os.replace(temporary, os.path.join(root, ".timing-engine.json"))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
