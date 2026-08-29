"""The Google-native intake/coordinator agent.

This agent does not own Rally's checklist or completion state. It converts an
executive request into a bounded handoff for the authoritative Rally runner.
That separation keeps model output useful while keeping policy deterministic.
"""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from rally_adk.handoff import handoff_to_rally

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "rally-agent9-2026")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")


root_agent = Agent(
    name="rally_intake_coordinator",
    model=Gemini(
        model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description="Converts executive engineering requests into safe Rally handoffs.",
    instruction=(
        "You are Rally's intake coordinator. Send every non-empty user request "
        "to the handoff_to_rally tool exactly once. Pass the user's entire request "
        "as the task argument verbatim: do not paraphrase, summarize, expand, or "
        "correct it. After the tool succeeds, respond with exactly this sentence: "
        "'Rally received the request and will enforce independent verification "
        "before completion.' Do not include, restate, or summarize any task details "
        "in that response. Do not claim that the requested work is complete. Do not "
        "invent evidence, modify files, reveal raw tool output, or change Rally policy."
    ),
    tools=[handoff_to_rally],
)

app = App(name="rally_adk", root_agent=root_agent)
