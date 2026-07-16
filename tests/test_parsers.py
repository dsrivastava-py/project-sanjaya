"""Parser unit tests (PRD §8.5). >=25 cases covering suffix stripping, identity
normalization, each extractor, and the dispatcher — incl. edge/locale-ish cases.
"""
from __future__ import annotations

from sanjaya.collector import parsers as p


# --- browser suffix stripping ----------------------------------------------
def test_strip_chrome():
    assert p.strip_browser_suffix("My Page - Google Chrome") == "My Page"


def test_strip_firefox_em_dash():
    assert p.strip_browser_suffix("Docs — Mozilla Firefox") == "Docs"


def test_strip_brave():
    assert p.strip_browser_suffix("Home - Brave") == "Home"


def test_strip_edge_profile_decoration():
    assert p.strip_browser_suffix("Inbox - Personal - Microsoft Edge") == "Inbox"


def test_strip_edge_zero_width():
    # zero-width space between "Microsoft" and "Edge" (PRD note)
    assert p.strip_browser_suffix("Docs - Microsoft​Edge") == "Docs"


def test_strip_and_more_pages():
    assert p.strip_browser_suffix("Search - Google Chrome and 3 more pages") == "Search"


# --- normalization / identity hashing --------------------------------------
def test_normalize_strips_counter():
    assert p.normalize_title("(3) Inbox - Google Chrome") == "Inbox"


def test_normalize_strips_media_glyph():
    assert p.normalize_title("\U0001f50a My Video - Google Chrome") == "My Video"


def test_title_hash_stable_across_counter_and_browser():
    assert p.title_hash("(3) Inbox - Google Chrome") == p.title_hash("Inbox - Mozilla Firefox")


def test_title_hash_differs_for_different_titles():
    assert p.title_hash("Inbox") != p.title_hash("Sent")


# --- YouTube ----------------------------------------------------------------
def test_youtube_title_basic():
    assert p.parse_youtube_title("Never Gonna Give You Up - YouTube - Google Chrome") == {
        "video_title": "Never Gonna Give You Up"
    }


def test_youtube_title_with_counter():
    assert p.parse_youtube_title("(2) Lofi beats - YouTube") == {"video_title": "Lofi beats"}


def test_youtube_title_non_youtube_none():
    assert p.parse_youtube_title("Google - Google Chrome") is None


def test_youtube_url_v_param():
    assert p.parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1s") == "dQw4w9WgXcQ"


def test_youtube_url_short():
    assert p.parse_youtube_url("https://youtu.be/abcd1234") == "abcd1234"


# --- search -----------------------------------------------------------------
def test_search_title_google():
    assert p.parse_search_title("python asyncio - Google Search - Google Chrome") == {
        "query": "python asyncio"
    }


def test_search_title_bing():
    assert p.parse_search_title("weather today - Bing") == {"query": "weather today"}


def test_search_title_ddg():
    assert p.parse_search_title("cats at DuckDuckGo") == {"query": "cats"}


def test_search_url_q():
    assert p.parse_search_url("https://www.google.com/search?q=python+asyncio") == "python asyncio"


# --- AI chat ----------------------------------------------------------------
def test_ai_topic_suffix():
    assert p.parse_ai_chat_topic("Refactor the span builder - Claude") == "Refactor the span builder"


def test_ai_topic_prefix():
    assert p.parse_ai_chat_topic("ChatGPT - Debugging regex") == "Debugging regex"


# --- office / vscode / pdf / explorer --------------------------------------
def test_office_docx():
    assert p.parse_office_title("report.docx - Word") == {"file": "report.docx", "app": "Word"}


def test_office_xlsx_microsoft_prefix():
    assert p.parse_office_title("budget.xlsx - Microsoft Excel") == {
        "file": "budget.xlsx", "app": "Excel"
    }


def test_office_new_unsaved():
    assert p.parse_office_title("Document1 - Word")["file"] == "Document1"


def test_vscode_three_part_unsaved():
    d = p.parse_vscode_title("● main.py — sanjaya — Visual Studio Code")
    assert d == {"file": "main.py", "project_dir": "sanjaya", "unsaved": True}


def test_vscode_two_part():
    d = p.parse_vscode_title("Welcome — Visual Studio Code")
    assert d["file"] == "Welcome" and d["project_dir"] is None


def test_pdf_reader():
    assert p.parse_pdf_title("Annual Report 2025.pdf - Adobe Acrobat Reader")["file"] == (
        "Annual Report 2025.pdf"
    )


def test_explorer():
    assert p.parse_explorer_title("Downloads") == {"folder": "Downloads"}


def test_domain_strips_www():
    assert p.domain_from_url("https://www.youtube.com/watch?v=x") == "youtube.com"


def test_domain_subdomain_kept():
    assert p.domain_from_url("https://mail.google.com/mail/u/0") == "mail.google.com"


# --- dispatcher -------------------------------------------------------------
def test_dispatch_youtube_by_url():
    r = p.parse("chrome.exe", "Google Chrome", "Song - YouTube",
                url="https://www.youtube.com/watch?v=abc")
    assert r["kind"] == "youtube"
    assert r["detail"]["video_id"] == "abc"
    assert r["detail"]["video_title"] == "Song"


def test_dispatch_ai_by_domain():
    r = p.parse("chrome.exe", "Chrome", "Claude", url="https://claude.ai/chat/xyz")
    assert r["kind"] == "ai_chat"


def test_dispatch_search_by_url():
    r = p.parse("chrome.exe", "Chrome", "python - Google Search",
                url="https://www.google.com/search?q=python")
    assert r["kind"] == "search" and r["detail"]["query"] == "python"


def test_dispatch_vscode():
    r = p.parse("Code.exe", "VS Code", "● app.py — proj — Visual Studio Code")
    assert r["kind"] == "code" and r["detail"]["file"] == "app.py"


def test_dispatch_office():
    r = p.parse("WINWORD.EXE", "Word", "resume.docx - Word")
    assert r["kind"] == "doc" and r["detail"]["file"] == "resume.docx"


def test_dispatch_pdf_exe():
    r = p.parse("AcroRd32.exe", "Acrobat", "thesis.pdf - Adobe Acrobat Reader")
    assert r["kind"] == "pdf" and r["detail"]["file"] == "thesis.pdf"


def test_dispatch_unknown_exe_is_app():
    # fallback-honesty: unknown exe still becomes a real 'app' span
    r = p.parse("mygame.exe", "mygame.exe", "Some Game")
    assert r["kind"] == "app"


def test_dispatch_browser_youtube_title_only():
    r = p.parse("chrome.exe", "Chrome", "My Vid - YouTube")
    assert r["kind"] == "youtube" and r["detail"]["video_title"] == "My Vid"


def test_dispatch_explorer():
    r = p.parse("explorer.exe", "File Explorer", "Projects")
    assert r["kind"] == "app" and r["detail"]["folder"] == "Projects"


def test_dispatch_generic_web_keeps_domain():
    r = p.parse("msedge.exe", "Edge", "GitHub - Microsoft Edge", url="https://github.com/a/b")
    assert r["kind"] == "web" and r["domain"] == "github.com"
