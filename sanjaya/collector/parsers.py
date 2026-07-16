"""Deterministic title/URL parsers (PRD §8.5). Pure functions only — no Windows
APIs, no I/O — so they are fully unit-testable on any platform.

Two jobs:
  * ``normalize_title`` / ``title_hash`` — stable identity key for the span
    builder (strip counters, media glyphs, browser suffixes before hashing).
  * ``parse`` — dispatch a raw (exe, title, url?) sample to a span ``kind`` plus
    an extracted ``detail`` dict (video_title, query, topic, file, project_dir…).

Fallback-honesty rule (§8.5): if only the exe is known, the span is still kind
``app`` — Sanjaya never drops time on the floor.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlparse

# --- constants ---------------------------------------------------------------
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)
_DASH = r"[-–—]"  # hyphen, en dash, em dash

BROWSER_EXES = {
    "chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe",
    "opera_gx.exe", "vivaldi.exe", "arc.exe", "chromium.exe",
}
CODE_EXES = {"code.exe", "cursor.exe", "windsurf.exe"}
OFFICE_EXES = {"winword.exe", "excel.exe", "powerpnt.exe"}
PDF_EXES = {"acrord32.exe", "acrobat.exe", "sumatrapdf.exe"}
MEDIA_EXES = {"vlc.exe", "spotify.exe"}
DESKTOP_AI_EXES = {"claude.exe", "chatgpt.exe"}
EXPLORER_EXES = {"explorer.exe"}

AI_HOSTS = {
    "chatgpt.com", "chat.openai.com", "claude.ai", "gemini.google.com",
    "bard.google.com", "perplexity.ai", "groq.com", "copilot.microsoft.com",
}
SEARCH_HOSTS = {"google.com", "bing.com", "duckduckgo.com"}

_OFFICE_APP = {"Word": "Word", "Excel": "Excel", "PowerPoint": "PowerPoint"}

# --- suffix / normalization --------------------------------------------------
_EDGE_SUFFIX_RE = re.compile(
    rf"\s*{_DASH}\s*(?:[^-–—]+\s*{_DASH}\s*)?Microsoft\s*Edge\s*$"
)
_OTHER_SUFFIX_RE = re.compile(
    rf"\s*{_DASH}\s*(?:Google Chrome|Mozilla Firefox|Brave|Opera(?: GX)?"
    r"|Vivaldi|Chromium)\s*$"
)
_MORE_PAGES_RE = re.compile(r"\s+and \d+ more pages?\s*$", re.I)
_COUNTER_RE = re.compile(r"^\s*\(\d+\)\s*")
_MEDIA_GLYPH_RE = re.compile(r"^[▶⏸⏹\U0001f50a\U0001f507●•\s]+")


def _clean(title: str) -> str:
    return (title or "").translate(ZERO_WIDTH)


def strip_browser_suffix(title: str) -> str:
    """Remove a trailing ' - <Browser>' (incl. Edge profile decoration)."""
    t = _clean(title)
    t = _MORE_PAGES_RE.sub("", t)
    t = _EDGE_SUFFIX_RE.sub("", t)
    t = _OTHER_SUFFIX_RE.sub("", t)
    return t.strip()


def normalize_title(title: str) -> str:
    """Identity-key normalization: drop counters, media glyphs, browser suffix."""
    t = strip_browser_suffix(title)
    t = _COUNTER_RE.sub("", t)
    t = _MEDIA_GLYPH_RE.sub("", t)
    return t.strip()


def title_hash(title: str) -> str:
    norm = normalize_title(title).lower()
    return hashlib.blake2b(norm.encode("utf-8"), digest_size=8).hexdigest()


# --- URL helpers -------------------------------------------------------------
def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0] or None


def _registrable(domain: str | None) -> str | None:
    """Best-effort last-two-labels registrable domain ('mail.google.com'->
    'google.com') for host-set membership checks. Good enough for our fixed sets.
    """
    if not domain:
        return None
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def parse_youtube_url(url: str | None) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    if p.netloc.endswith("youtu.be"):
        return p.path.lstrip("/") or None
    v = parse_qs(p.query).get("v")
    return v[0] if v else None


def parse_search_url(url: str | None) -> str | None:
    if not url:
        return None
    q = parse_qs(urlparse(url).query).get("q")
    return q[0] if q else None


# --- title parsers -----------------------------------------------------------
_YT_TITLE_RE = re.compile(r"^(?:\(\d+\)\s*)?(.*) - YouTube$")
_SEARCH_TITLE_RES = [
    re.compile(r"^(.*) - Google Search$"),
    re.compile(r"^(.*) - Bing$"),
    re.compile(r"^(.*) - Search$"),
    re.compile(r"^(.*) at DuckDuckGo$"),
]
_AI_SUFFIX_RE = re.compile(rf"\s*{_DASH}\s*(ChatGPT|Claude|Gemini|Perplexity|Copilot)\s*$")
_AI_PREFIX_RE = re.compile(rf"^(?:ChatGPT|Claude|Gemini|Perplexity)\s*{_DASH}\s*")
_OFFICE_EXT_RE = re.compile(
    r"^(.*?\.(?:docx?|xlsx?|pptx?)) - (?:Microsoft )?(Word|Excel|PowerPoint)$", re.I
)
_OFFICE_PLAIN_RE = re.compile(r"^(.*) - (?:Microsoft )?(Word|Excel|PowerPoint)$")
_VSCODE_3_RE = re.compile(r"^(● )?(.*) — (.*) — Visual Studio Code$")
_VSCODE_2_RE = re.compile(r"^(● )?(.*) — Visual Studio Code$")
_PDF_RE = re.compile(r"([^\t\n/\\|<>:*?\"]+?\.pdf)\b", re.I)


def parse_youtube_title(title: str) -> dict | None:
    m = _YT_TITLE_RE.match(strip_browser_suffix(title))
    if m and m.group(1).strip():
        return {"video_title": m.group(1).strip()}
    return None


def parse_search_title(title: str) -> dict | None:
    t = strip_browser_suffix(title)
    for rx in _SEARCH_TITLE_RES:
        m = rx.match(t)
        if m and m.group(1).strip():
            return {"query": m.group(1).strip()}
    return None


def parse_ai_chat_topic(title: str) -> str | None:
    t = strip_browser_suffix(title)
    t = _AI_SUFFIX_RE.sub("", t)
    t = _AI_PREFIX_RE.sub("", t)
    t = t.strip()
    return t or None


def parse_pdf_title(title: str) -> dict | None:
    m = _PDF_RE.search(strip_browser_suffix(title))
    if m:
        return {"file": m.group(1).strip()}
    return None


def parse_office_title(title: str) -> dict | None:
    t = strip_browser_suffix(title)
    m = _OFFICE_EXT_RE.match(t)
    if m:
        return {"file": m.group(1).strip(), "app": _OFFICE_APP[m.group(2).title()]}
    m = _OFFICE_PLAIN_RE.match(t)
    if m and m.group(1).strip():
        return {"file": m.group(1).strip(), "app": _OFFICE_APP[m.group(2).title()]}
    return None


def parse_vscode_title(title: str) -> dict | None:
    t = strip_browser_suffix(title)
    m = _VSCODE_3_RE.match(t)
    if m:
        return {
            "file": m.group(2).strip(),
            "project_dir": m.group(3).strip(),
            "unsaved": bool(m.group(1)),
        }
    m = _VSCODE_2_RE.match(t)
    if m:
        return {"file": m.group(2).strip(), "project_dir": None, "unsaved": bool(m.group(1))}
    return None


def parse_explorer_title(title: str) -> dict | None:
    t = _clean(title).strip()
    return {"folder": t} if t else None


# --- dispatcher --------------------------------------------------------------
def parse(exe: str | None, app_name: str | None, title: str | None,
          url: str | None = None, domain: str | None = None) -> dict:
    """Map a raw sample to ``{kind, detail, domain, url}``.

    ``url``/``domain`` come from the browser extension when present and take
    precedence over title parsing (URL wins over title, §8.3).
    """
    exe_l = (exe or "").lower()
    title = _clean(title)
    if url and not domain:
        domain = domain_from_url(url)
    reg = _registrable(domain)
    detail: dict = {}

    # ---- browser / web context (has a domain, or is a browser exe) ----------
    if domain or exe_l in BROWSER_EXES:
        # YouTube
        if reg == "youtube.com" or domain == "youtu.be" or (
            not domain and parse_youtube_title(title)
        ):
            vid = parse_youtube_url(url)
            if vid:
                detail["video_id"] = vid
            yt = parse_youtube_title(title)
            if yt:
                detail.update(yt)
            return _res("youtube", detail, domain or "youtube.com", url)

        # AI chat (by host, or by title suffix when only the title is known)
        title_says_ai = bool(_AI_SUFFIX_RE.search(strip_browser_suffix(title)) or
                             _AI_PREFIX_RE.match(strip_browser_suffix(title)))
        if reg in AI_HOSTS or domain in AI_HOSTS or (not domain and title_says_ai):
            topic = parse_ai_chat_topic(title)
            if topic:
                detail["topic"] = topic
            return _res("ai_chat", detail, domain, url)

        # Web search
        q = parse_search_url(url) if url else None
        search_host = reg in SEARCH_HOSTS or domain in SEARCH_HOSTS
        if not q and (search_host or not domain):
            st = parse_search_title(title)
            q = st["query"] if st else None
        if q:
            detail["query"] = q
            return _res("search", detail, domain, url)

        # Browser PDF viewer
        pdf = parse_pdf_title(title)
        if pdf and (not domain or url and url.lower().endswith(".pdf")):
            detail.update(pdf)
            return _res("pdf", detail, domain, url)

        # Generic web page — keep the cleaned title as its own signal
        cleaned = strip_browser_suffix(title)
        if cleaned:
            detail["page_title"] = cleaned
        return _res("web", detail, domain, url)

    # ---- native apps --------------------------------------------------------
    if exe_l in CODE_EXES:
        vs = parse_vscode_title(title)
        if vs:
            detail.update(vs)
        return _res("code", detail, None, None)

    if exe_l in OFFICE_EXES:
        doc = parse_office_title(title)
        if doc:
            detail.update(doc)
        return _res("doc", detail, None, None)

    if exe_l in PDF_EXES:
        pdf = parse_pdf_title(title)
        if pdf:
            detail.update(pdf)
        return _res("pdf", detail, None, None)

    if exe_l in MEDIA_EXES:
        return _res("media", detail, None, None)

    if exe_l in DESKTOP_AI_EXES:
        topic = parse_ai_chat_topic(title)
        if topic:
            detail["topic"] = topic
        return _res("ai_chat", detail, None, None)

    if exe_l in EXPLORER_EXES:
        folder = parse_explorer_title(title)
        if folder:
            detail.update(folder)
        return _res("app", detail, None, None)

    # Fallback honesty: unknown exe still becomes a real 'app' span.
    return _res("app", detail, None, None)


def _res(kind: str, detail: dict, domain: str | None, url: str | None) -> dict:
    return {"kind": kind, "detail": detail, "domain": domain, "url": url}
