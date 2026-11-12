"""Strict offline HTML sandbox renderer and sanitization engine (F06.1).

Sanitizes HTML artifacts by:
- Stripping all external script sources (<script src="http(s)://...">, <script src="//...">).
- Stripping all external stylesheets (<link href="http(s)://...">, <link href="//...">).
- Stripping untrusted author Content-Security-Policy meta tags.
- Stripping CSS @import and external url(...) references from <style> blocks and inline style attributes.
- Injecting a strict offline Content-Security-Policy meta tag into <head>.
- Injecting a clean base offline CSS reset.
- Ensuring fragment HTML is cleanly wrapped in <!DOCTYPE html><html><head>...</head><body>...</body></html>.
"""

from __future__ import annotations

import re
from typing import List, Tuple
from bs4 import BeautifulSoup, Tag

STRICT_CSP_CONTENT = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; "
    "img-src data: blob:;"
)

OFFLINE_CSS_RESET = """/* Base offline CSS reset */
*, *::before, *::after { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #1a1a1a;
  background-color: #ffffff;
}
"""

_EXTERNAL_URL_PATTERN = re.compile(r"^(?:https?:)?//", re.IGNORECASE)
_CSS_IMPORT_PATTERN = re.compile(
    r"@import\s+(?:url\s*\(\s*['\"]?|['\"])(?P<url>[^'\"\)]+)['\"]?\s*\)?\s*;?",
    re.IGNORECASE,
)
_CSS_URL_PATTERN = re.compile(
    r"url\s*\(\s*['\"]?(?P<url>(?:https?:)?//[^'\"\)]+)['\"]?\s*\)",
    re.IGNORECASE,
)


def is_external_url(url: str | None) -> bool:
    """Check if a URL points to an external remote resource (http, https, or protocol-relative //)."""
    if not url:
        return False
    return bool(_EXTERNAL_URL_PATTERN.match(url.strip()))


def _sanitize_css_content(css_text: str, warnings: List[str]) -> str:
    """Sanitize CSS by removing external @import statements and external url() references."""
    # 1. Strip external @import statements
    def replace_import(match: re.Match[str]) -> str:
        url = match.group("url").strip()
        if is_external_url(url):
            warnings.append(f"Blocked external CSS @import: {url}")
            return ""
        return match.group(0)

    cleaned = _CSS_IMPORT_PATTERN.sub(replace_import, css_text)

    # 2. Strip external url(...) references
    def replace_url(match: re.Match[str]) -> str:
        url = match.group("url").strip()
        if is_external_url(url):
            warnings.append(f"Blocked external style url: {url}")
            return "none"
        return match.group(0)

    cleaned = _CSS_URL_PATTERN.sub(replace_url, cleaned)
    return cleaned


def sanitize_offline_html(raw_html: str) -> Tuple[str, List[str]]:
    """Sanitize raw HTML for secure offline sandbox rendering.
    
    Returns:
        tuple[str, list[str]]: (sanitized_html, list_of_warning_messages)
    """
    if not raw_html:
        raw_html = ""

    soup = BeautifulSoup(raw_html, "html.parser")
    warnings: List[str] = []

    # 1. Strip external scripts (<script src="http(s)://..." or src="//...">)
    for script in soup.find_all("script"):
        src = script.get("src")
        if src and is_external_url(src):
            warnings.append(f"Blocked external script: {src}")
            script.decompose()

    # 2. Strip external stylesheets / links (<link href="http(s)://..." or href="//...">)
    for link in soup.find_all("link"):
        href = link.get("href")
        if href and is_external_url(href):
            warnings.append(f"Blocked external stylesheet: {href}")
            link.decompose()

    # 3. Strip all <base> tags to prevent link and form-action hijacking
    for base_tag in soup.find_all("base"):
        href = base_tag.get("href", "")
        warnings.append(f"Blocked base tag: {href}")
        base_tag.decompose()

    # 4. Strip any author-provided Content-Security-Policy meta tags to prevent policy bypass
    for meta in soup.find_all("meta"):
        http_equiv = meta.get("http-equiv", "")
        if isinstance(http_equiv, str) and http_equiv.strip().lower() == "content-security-policy":
            meta.decompose()

    # 5. Sanitize <style> tags content (using get_text to handle comments and multi-node children)
    for style_tag in soup.find_all("style"):
        css_text = style_tag.get_text()
        if css_text:
            cleaned_css = _sanitize_css_content(css_text, warnings)
            style_tag.clear()
            style_tag.append(cleaned_css)

    # 6. Sanitize inline style attributes
    for tag_with_style in soup.find_all(attrs={"style": True}):
        orig_style = tag_with_style.get("style", "")
        if orig_style:
            sanitized_style = _sanitize_css_content(orig_style, warnings)
            tag_with_style["style"] = sanitized_style

    # 7. Ensure full HTML structure exists
    has_html = soup.html is not None
    has_head = soup.head is not None

    if not has_html:
        # Wrap fragment inside a new document
        new_soup = BeautifulSoup(
            "<!DOCTYPE html><html><head></head><body></body></html>",
            "html.parser",
        )
        assert new_soup.body is not None
        assert new_soup.head is not None
        # Move all current contents of soup into the new body
        for element in list(soup.contents):
            new_soup.body.append(element)
        soup = new_soup
    elif not has_head:
        new_head = soup.new_tag("head")
        assert soup.html is not None
        soup.html.insert(0, new_head)

    assert soup.head is not None

    # 7. Inject strict offline CSP meta tag as the very first element in <head>
    csp_meta = soup.new_tag(
        "meta",
        attrs={
            "http-equiv": "Content-Security-Policy",
            "content": STRICT_CSP_CONTENT,
        },
    )
    soup.head.insert(0, csp_meta)

    # 8. Inject base offline CSS reset into <head>
    reset_style = soup.new_tag("style")
    reset_style.string = OFFLINE_CSS_RESET
    soup.head.append(reset_style)

    # Ensure <!DOCTYPE html> preamble exists if not present
    rendered = str(soup)
    if not rendered.strip().lower().startswith("<!doctype html"):
        rendered = "<!DOCTYPE html>\n" + rendered

    return rendered, warnings
