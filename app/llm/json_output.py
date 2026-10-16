"""Remove a whole JSON code fence without repairing or guessing model output."""
import re


def json_text(text: str) -> str:
    """Accept bare JSON or one enclosing Markdown JSON block; retain strict parsing."""
    text = text.strip()
    fenced = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```', text,
                          flags=re.IGNORECASE | re.DOTALL)
    return fenced.group(1).strip() if fenced else text
