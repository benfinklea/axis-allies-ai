"""JSON repair: local models sometimes wrap JSON in prose or fences."""
import json
import re


def parse(text):
    """Parse model output into a dict, tolerating fences and surrounding
    prose. Raises ValueError if no JSON object can be recovered."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    if not isinstance(text, str):
        raise ValueError("non-text model output")
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    for block in fenced:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    # last resort: outermost braces
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not recover JSON from: {text[:200]!r}")
