"""Render admin-edited plain text safely: paragraphs, '- ' bullet lists and links to e-mail addresses."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

EMAIL_RE = re.compile(r"([\w.+-]+@[\w-]+\.[\w.-]*\w)")


def _inline(text):
    return EMAIL_RE.sub(r'<a href="mailto:\1">\1</a>', escape(text))


@register.filter
def plaintext_html(value):
    blocks = re.split(r"\n\s*\n", (value or "").strip())
    html = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.lstrip().startswith("- ") for line in lines):
            items = "".join(f"<li>{_inline(line.lstrip()[2:])}</li>" for line in lines)
            html.append(f"<ul>{items}</ul>")
        else:
            html.append("<p>" + "<br>".join(_inline(line) for line in lines) + "</p>")
    return mark_safe("".join(html))
