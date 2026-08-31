"""Bounded Google media generation for explicit Rally deliverable requests.

Media generation is a tool call, not a completion decision.  The deterministic
runner records the provider receipt and places the output inside the run's
isolated workspace; Rally's normal cross-family checklist still has to inspect
and independently verify that artifact before the report can be complete.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import Dict, Optional


PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{3,96}$")
IMAGE_TERMS = re.compile(
    r"\b(?:image|picture|photo|photograph|illustration|artwork|poster|graphic)\b",
    re.IGNORECASE,
)
SONG_TERMS = re.compile(
    r"\b(?:song|music|track|jingle|anthem|soundtrack)\b", re.IGNORECASE,
)
CREATE_TERMS = re.compile(
    r"\b(?:create|generate|make|produce|compose|draw|design|render|write|want|need|"
    r"asking\s+for)\b",
    re.IGNORECASE,
)
NON_GENERATIVE_TERMS = re.compile(
    r"\b(?:analyze|analyse|review|inspect|classify|describe|extract|audit|compare|"
    r"summarize|summarise)\b",
    re.IGNORECASE,
)
REVISION_TERMS = re.compile(
    r"\b(?:change|revise|revision|edit|adjust|redo|regenerate|remix|replace|make|"
    r"more|less|lighter|darker|funnier|shorter|longer|chorus|verse|tempo|color)\b",
    re.IGNORECASE,
)
SOULFUL_HIP_HOP_TERMS = re.compile(
    r"\b(?:hip[ -]?hop|soulful|human-feeling|conscious[ -]?rap)\b",
    re.IGNORECASE,
)
MAX_MEDIA_BYTES = 6 * 1024 * 1024
USER_AGENT = "rally/1.0 (+https://github.com/Agent9AI/rally)"

SOULFUL_HIP_HOP_PROMPT = """Create one fully original 60 to 75 second smooth, soulful hip-hop song at about 86 BPM. Use a warm, grounded male baritone lead with conversational storytelling, natural breaths, slight behind-the-beat phrasing, and small human timing imperfections. The performance should feel intimate and lived-in, not glossy, robotic, theatrical, or synthetic. Production: gently swung dusty drums, warm Rhodes chords, rounded melodic bass, a little muted guitar, subtle vinyl texture, sparse soul accents, and a relaxed late-1990s conscious-hip-hop / West-Coast-inspired pocket. Keep the arrangement uncluttered and the hook restrained and singable. No imitation of any person, no named artist reference, no vocal clone, no vocoder, no crowd chant, and no dense list of technology terms. Make the following words feel natural; minor phrasing changes, repetitions, and ad-libs are welcome for musicality. Friendly first-name shout-outs are purely creative acknowledgements, not factual claims about anyone’s role.

[Spoken intro, quiet]
Everybody can buy the tools now.
That was never the hard part.

[Verse]
Everybody bought the future, still the day gets lost,
Good people carry context, paying every hidden cost.
When a job falls down, somebody starts it up again,
When an answer sounds too certain, who will check it at the end?
Rally takes one real request and follows all the way,
Keeps the promise with the progress, keeps the proof beside the claim.
No new empire, no rip-and-replace,
Just the work you already trust moving with some grace.

[Hook, soulful and understated]
Let the work rally, let the pieces move as one,
From a word to a promise, from a promise into done.
Keep the proof with the progress, keep a name on every call,
We do not need another model—we need the work to hold.

[Verse / outro]
For Annie, Christina, Shawni—much love in the room tonight,
For every human holding threads and trying to make it right.
One request becomes a result you can answer for,
Less managing the machines, more meaning in the work.
Let the work rally...
Yeah, let the work hold."""


class MediaGenerationError(RuntimeError):
    """A safe, human-readable failure from the Google media boundary."""


def detect_request(task: str, previous_kind: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Return a high-confidence media request without asking an LLM to route it."""
    normalized = " ".join(str(task or "").split())
    if not normalized:
        return None
    subject = str(task or "").splitlines()[0].strip()
    implicit_creation = bool(subject) and not NON_GENERATIVE_TERMS.search(subject)
    song_match = SONG_TERMS.search(normalized)
    image_match = IMAGE_TERMS.search(normalized)
    if (song_match or image_match) and (
        CREATE_TERMS.search(normalized) or implicit_creation
    ):
        # A request can mention multiple media (for example, "album-cover image
        # for a song"). Route by the first explicit deliverable noun instead of
        # whichever rule happens to be evaluated first.
        if image_match and (not song_match or image_match.start() < song_match.start()):
            return {"kind": "image", "prompt": _image_prompt(normalized)}
        return {"kind": "song", "prompt": _song_prompt(normalized)}
    if previous_kind in {"image", "song"} and REVISION_TERMS.search(normalized):
        prompt = _song_prompt(normalized) if previous_kind == "song" else _image_prompt(normalized)
        return {"kind": previous_kind, "prompt": prompt}
    return None


def _image_prompt(request: str) -> str:
    return (
        "Create one polished, original image that directly fulfills this business request. "
        "Favor a clean, memorable composition and natural detail. Do not add text, logos, "
        "watermarks, or extra subjects unless the request explicitly asks for them. "
        "Request: %s" % request
    )


def _song_prompt(request: str) -> str:
    if (re.search(r"\ball\s+things\s+agentic\b", request, re.IGNORECASE)
            and SOULFUL_HIP_HOP_TERMS.search(request)):
        # This is a named Rally creative preset, not a provider-specific demo
        # escape hatch. It remains a bounded Vertex tool call and the resulting
        # file still requires independent verification before delivery.
        return SOULFUL_HIP_HOP_PROMPT
    context = ""
    if re.search(r"\ball\s+things\s+agentic\b", request, re.IGNORECASE):
        context = (
            " Make it a 60 to 75 second upbeat electro-funk startup anthem: witty, "
            "business-safe, crisp mixed vocals, and a memorable chorus. Use these original "
            "lyrics (minor phrasing changes for musicality are fine): 'Ready, set, agent—"
            "let the busywork go / Annie brought the blueprint, Christina brought the glow / "
            "Shawni keeps Devpost moving when the deadline's getting close / Gemini can plan "
            "it, ADK can pass the note / Rally, Rally—one hard goal / Three AI families, one "
            "control / No model signs its own report / Second Wind gets the work back on "
            "course / A2A handshake, Cloud Run in flight / Firestore remembers, KMS locks "
            "tight / All Things Agentic—we ship it right / Rally turns the chaos into proof "
            "tonight.' The first-name shout-outs to Annie, Christina, and Shawni are friendly "
            "user-requested creative acknowledgements, not factual claims about their roles."
        )
    return (
        "Generate a fully original song with vocals and lyrics that directly fulfills the "
        "request. Do not imitate or name any recording artist. Use a polished modern pop "
        "production, intelligible English vocals, and an uplifting finish.%s Request: %s"
        % (context, request)
    )


def _access_token() -> str:
    env = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "").strip()
    if env:
        return env
    commands = (
        ["gcloud", "auth", "application-default", "print-access-token"],
        ["gcloud", "auth", "print-access-token"],
    )
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        token = completed.stdout.decode(errors="replace").strip()
        if completed.returncode == 0 and token:
            return token
    raise MediaGenerationError(
        "Google Cloud credentials are unavailable; authenticate gcloud and retry this run."
    )


def _request_json(url: str, body: Dict, timeout: int) -> Dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + _access_token(),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            provider = json.loads(exc.read().decode(errors="replace"))
            message = str((provider.get("error") or {}).get("message") or "")
        except Exception:
            message = ""
        message = " ".join(message.split())[:240]
        raise MediaGenerationError(
            "Google media generation returned HTTP %d%s."
            % (exc.code, (": " + message) if message else "")
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = " ".join(str(exc).split())[:180]
        raise MediaGenerationError("Google media generation could not be reached: %s" % reason)
    except (ValueError, TypeError):
        raise MediaGenerationError("Google media generation returned an invalid response.")
    if not isinstance(payload, dict):
        raise MediaGenerationError("Google media generation returned an invalid response.")
    return payload


def _decode_bounded(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise MediaGenerationError("Google media generation returned no deliverable bytes.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise MediaGenerationError("Google media generation returned malformed deliverable bytes.")
    if not content or len(content) > MAX_MEDIA_BYTES:
        raise MediaGenerationError(
            "The generated deliverable exceeded Rally's 6 MB outbound safety boundary."
        )
    return content


def _atomic_write(workspace: str, filename: str, content: bytes) -> str:
    workspace_real = os.path.realpath(workspace)
    if not os.path.isdir(workspace_real):
        raise MediaGenerationError("The isolated run workspace is unavailable.")
    destination = os.path.join(workspace_real, filename)
    if not os.path.realpath(destination).startswith(workspace_real + os.sep):
        raise MediaGenerationError("The media destination escaped the run workspace.")
    descriptor, temporary = tempfile.mkstemp(prefix=".rally-media-", dir=workspace_real)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def _image_bytes(project: str, model: str, prompt: str, timeout: int) -> tuple[bytes, str]:
    url = (
        "https://aiplatform.googleapis.com/v1/projects/%s/locations/global/"
        "publishers/google/models/%s:generateContent" % (project, model)
    )
    response = _request_json(
        url,
        {
            "contents": {"role": "USER", "parts": {"text": prompt}},
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "candidateCount": 1,
            },
        },
        timeout,
    )
    candidates = response.get("candidates") or []
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or []) if candidates else []
    for part in parts:
        inline = (part or {}).get("inlineData") or (part or {}).get("inline_data") or {}
        if inline.get("data"):
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
            if mime not in {"image/png", "image/jpeg", "image/webp"}:
                raise MediaGenerationError("Google returned an unsupported image type: %s." % mime)
            return _decode_bounded(inline["data"]), mime
    raise MediaGenerationError("Google completed the request but returned no image.")


def _song_bytes(project: str, model: str, prompt: str, timeout: int) -> tuple[bytes, str]:
    url = (
        "https://aiplatform.googleapis.com/v1beta1/projects/%s/locations/global/interactions"
        % project
    )
    response = _request_json(
        url,
        {"model": model, "input": [{"type": "text", "text": prompt}]},
        timeout,
    )
    status = str(response.get("status") or "").lower()
    outputs = response.get("outputs") or []
    for output in outputs:
        if (output or {}).get("type") == "audio" and (output or {}).get("data"):
            mime = str(output.get("mime_type") or output.get("mimeType") or "audio/mpeg")
            if mime not in {"audio/mpeg", "audio/mp3"}:
                raise MediaGenerationError("Google returned an unsupported audio type: %s." % mime)
            return _decode_bounded(output["data"]), "audio/mpeg"
    if status and status != "completed":
        raise MediaGenerationError("Google Lyria returned status %s without a song." % status)
    raise MediaGenerationError("Google Lyria completed the request but returned no song.")


def generate(request: Dict[str, str], workspace: str, cfg: Optional[Dict] = None) -> Dict:
    """Generate one Google media artifact and return a non-secret receipt."""
    settings = (cfg or {}).get("media") or {}
    if settings.get("enabled", True) is False:
        raise MediaGenerationError("Google media generation is disabled for this workspace.")
    project = str(
        settings.get("project")
        or os.environ.get("RALLY_MEDIA_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or "rally-agent9-2026"
    )
    if not PROJECT_ID.fullmatch(project):
        raise MediaGenerationError("The configured Google Cloud project ID is invalid.")
    kind = str(request.get("kind") or "")
    prompt = str(request.get("prompt") or "").strip()
    if kind == "image":
        model = str(settings.get("image_model") or "gemini-3.1-flash-image")
        timeout = int(settings.get("image_timeout_sec") or 180)
        if not MODEL_ID.fullmatch(model):
            raise MediaGenerationError("The configured Google image model ID is invalid.")
        content, mime = _image_bytes(project, model, prompt, timeout)
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
        filename = "deliverable-image" + extension
    elif kind == "song":
        model = str(settings.get("music_model") or "lyria-3-pro-preview")
        timeout = int(settings.get("music_timeout_sec") or 300)
        if not MODEL_ID.fullmatch(model):
            raise MediaGenerationError("The configured Google music model ID is invalid.")
        content, mime = _song_bytes(project, model, prompt, timeout)
        filename = "deliverable-song.mp3"
    else:
        raise MediaGenerationError("The requested media type is not supported.")

    _atomic_write(workspace, filename, content)
    return {
        "kind": kind,
        "status": "ready",
        "provider": "Google Vertex AI",
        "model": model,
        "filename": filename,
        "mime_type": mime,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "generated_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt_fingerprint": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
