# src/ingestion/html.py
import re
import logging
from markdownify import markdownify

logger = logging.getLogger(__name__)

ALLOWED_TAGS = [
    "p", "br",
    "strong", "em", "b", "i",
    "a",
    "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6",
]


def html_to_markdown(html: str | None) -> str | None:
    """
    Convert HTML description to markdown.
    Only converts allowed tags — everything else is stripped.
    Returns None if input is None or result is empty.
    """
    if not html:
        return None

    md = markdownify(
        html,
        convert=ALLOWED_TAGS,
        heading_style="ATX",   # use # style headings
        autolinks=False
    )

    # Collapse 3+ consecutive newlines to 2 (markdownify can be verbose)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = md.strip()

    return md or None