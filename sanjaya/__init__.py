"""Sanjaya — an AI-powered, zero-effort activity journal for Windows.

Single-process design (PRD §5): collector thread + FastAPI server + AI layer,
all local except calls to the Groq API.
"""

__version__ = "0.1.0"
