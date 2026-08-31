"""Outbound mail via Resend, with the ceiling enforced before the call.

The sending quota is shared with unrelated projects, so a runaway loop here is
someone else's outage. Every ceiling therefore fails closed: if the ledger
cannot be read, nothing sends.
"""
from __future__ import annotations

import base64
import json
import html
import os
import re
import stat
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Dict, List, Optional

API = "https://api.resend.com/emails"
USER_AGENT = "rally/1.0 (+https://github.com/Agent9AI/rally)"
DEFAULT_REPLY_TO = "Rally <rally@updates.agent9.dev>"
RALLY_SUBJECT = re.compile(r"^\[rally\s+#r-[0-9a-z-]+\]\s*(.*)$", re.IGNORECASE)
RUN_ID = re.compile(r"^r-[0-9a-z-]{3,77}$")
RUNS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runs"))
MAX_ATTACHMENT_FILE_BYTES = 6 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS = 5
ATTACHMENT_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".md": "text/markdown",
    ".txt": "text/plain",
}
ATTACHMENT_EXTENSION_ORDER = {
    extension: index for index, extension in enumerate(
        (".pdf", ".pptx", ".docx", ".html", ".htm", ".png", ".jpg",
         ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".md", ".txt")
    )
}
SECRET_FILENAME = re.compile(
    r"(?:^|[\\/._-])(?:secret|secrets|credential|credentials|token|tokens|password|"
    r"private[-_]?key|api[-_]?key)(?:[\\/._-]|$)", re.IGNORECASE,
)
SECRET_CONTENT = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)authorization\s*:\s*bearer\s+[a-z0-9._~+/=-]{12,}"),
    re.compile(rb"(?i)(?:api[_-]?key|client_secret|access_token|refresh_token|password)"
               rb"\s*[\"']?\s*[:=]\s*[\"'][a-z0-9._~+/=-]{12,}"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(rb"\b(?:sk|ghp|github_pat|re)_[0-9A-Za-z_-]{20,}\b"),
    re.compile(rb"(?i)(?:file://|/Users/|/home/[A-Za-z0-9._-]+/|[A-Z]:\\\\Users\\\\)"),
)


def _safe_attachment_name(name: str) -> str:
    """Return a short ASCII filename that cannot escape an email attachment."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(".-_")
    if not normalized:
        normalized = "rally-deliverable"
    stem, extension = os.path.splitext(normalized)
    extension = extension.lower()[:10]
    stem = (stem or "rally-deliverable")[:80].rstrip(".-_")
    return (stem + extension)[:96]


def _looks_secret(filename: str, content: bytes) -> bool:
    if SECRET_FILENAME.search(filename):
        return True
    return any(pattern.search(content) for pattern in SECRET_CONTENT)


def _candidate_order(relative_path: str) -> tuple:
    """Prefer named final deliverables, then shallow paths and stable types."""
    parts = relative_path.split(os.sep)
    basename = parts[-1]
    stem, extension = os.path.splitext(basename.casefold())
    preferred = 0 if any(
        word in stem for word in
        ("final", "deliverable", "brief", "report", "presentation", "output")
    ) else 1
    return (
        preferred,
        len(parts) - 1,
        ATTACHMENT_EXTENSION_ORDER.get(extension, 99),
        relative_path.casefold(),
    )


def _read_regular_file(path: str, limit: int) -> Optional[bytes]:
    """Read one bounded file descriptor without following a final symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        chunks: List[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        return content if len(content) <= limit else None
    finally:
        os.close(descriptor)


def final_artifact_attachments(run_id: str) -> tuple:
    """Select bounded, safe artifacts from one run's isolated workspace.

    Returns ``(resend_attachments, human_note)`` and never raises. A failure to
    attach a convenience copy must not suppress the already-verified report.
    """
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        return [], "No file was attached because the run reference was invalid."
    workspace = os.path.join(RUNS_ROOT, run_id, "workspace")
    if os.path.islink(workspace) or not os.path.isdir(workspace):
        return [], "No file attachment was produced; the verified result is included above."
    workspace_real = os.path.realpath(workspace)
    expected_parent = os.path.realpath(os.path.join(RUNS_ROOT, run_id)) + os.sep
    if not workspace_real.startswith(expected_parent):
        return [], "Rally withheld the attachment because it was outside the run boundary."

    candidates = []
    saw_file = False
    saw_unsupported = False
    saw_unsafe = False
    saw_oversized = False
    try:
        for current, directories, files in os.walk(workspace, followlinks=False):
            directories[:] = sorted(
                directory for directory in directories
                if not os.path.islink(os.path.join(current, directory))
                and not directory.startswith(".")
            )
            for filename in sorted(files):
                path = os.path.join(current, filename)
                if filename.startswith(".") or os.path.islink(path):
                    saw_unsafe = True
                    continue
                saw_file = True
                relative = os.path.relpath(path, workspace)
                if relative.startswith(".." + os.sep) or relative == "..":
                    saw_unsafe = True
                    continue
                extension = os.path.splitext(filename)[1].lower()
                if extension not in ATTACHMENT_TYPES:
                    saw_unsupported = True
                    continue
                if extension in {".md", ".txt"} and not any(
                    word in os.path.splitext(filename)[0].casefold()
                    for word in
                    ("final", "deliverable", "brief", "report", "presentation", "output")
                ):
                    # Markdown and text are often internal notes. Only an
                    # explicitly deliverable-shaped name crosses the boundary.
                    saw_unsupported = True
                    continue
                try:
                    size = os.lstat(path).st_size
                except OSError:
                    saw_unsafe = True
                    continue
                if size > MAX_ATTACHMENT_FILE_BYTES:
                    saw_oversized = True
                    continue
                candidates.append((relative, path, size, extension))
    except OSError:
        return [], "Rally could not safely read the deliverable; the verified result is included above."

    candidates.sort(key=lambda candidate: _candidate_order(candidate[0]))
    attachments = []
    names = set()
    total = 0
    omitted_for_limit = False
    for relative, path, expected_size, extension in candidates:
        if len(attachments) >= MAX_ATTACHMENTS:
            omitted_for_limit = True
            break
        if total + expected_size > MAX_ATTACHMENT_TOTAL_BYTES:
            omitted_for_limit = True
            continue
        real_path = os.path.realpath(path)
        if not real_path.startswith(workspace_real + os.sep):
            saw_unsafe = True
            continue
        content = _read_regular_file(path, MAX_ATTACHMENT_FILE_BYTES)
        if content is None:
            saw_unsafe = True
            continue
        if total + len(content) > MAX_ATTACHMENT_TOTAL_BYTES:
            omitted_for_limit = True
            continue
        if _looks_secret(relative, content):
            saw_unsafe = True
            continue
        filename = _safe_attachment_name(os.path.basename(relative))
        stem, suffix = os.path.splitext(filename)
        counter = 2
        while filename.casefold() in names:
            filename = "%s-%d%s" % (stem[:72], counter, suffix)
            counter += 1
        names.add(filename.casefold())
        attachments.append({
            "filename": filename,
            "content": base64.b64encode(content).decode("ascii"),
            "content_type": ATTACHMENT_TYPES[extension],
        })
        total += len(content)

    # Resend's CID contract makes a generated image visible in the executive
    # email while retaining it as the same downloadable attachment. Clients
    # that suppress inline media still receive the plain-text attachment note.
    for attachment in attachments:
        if (attachment.get("content_type", "").startswith("image/")
                and "deliverable-image" in attachment.get("filename", "").casefold()):
            attachment["content_id"] = "rally-deliverable-image"
            break

    if attachments:
        names_text = ", ".join(item["filename"] for item in attachments)
        note = "Attached %s: %s." % (
            "deliverable" if len(attachments) == 1 else "%d deliverables" % len(attachments),
            names_text,
        )
        if omitted_for_limit or saw_oversized:
            note += " Additional eligible files were omitted to stay within the 8 MB safety limit."
        if saw_unsafe:
            note += " A candidate that failed the outbound safety check was withheld."
        return attachments, note
    if saw_oversized or omitted_for_limit:
        return [], "No artifact was attached because eligible files exceeded the 8 MB safety limit."
    if saw_unsafe:
        return [], "Rally withheld the candidate attachment because it failed the outbound safety check."
    if saw_file or saw_unsupported:
        return [], "No supported final artifact was found; the verified result is included above."
    return [], "No file attachment was produced; the verified result is included above."


def _reply_address() -> str:
    """The human reply route, configurable without changing a saved run."""
    return os.environ.get("RALLY_REPLY_TO", DEFAULT_REPLY_TO).strip() or DEFAULT_REPLY_TO


def _clean_markdown(value: str) -> str:
    """Remove the few Markdown decorations that look broken in email clients."""
    value = re.sub(r"^#{1,4}\s+", "", value.strip())
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"__([^_]+)__", r"\1", value)
    return value.strip()


def _rally_sections(text: str, report_message: bool) -> tuple:
    """Separate the executive body from the machine/audit record.

    The runner and dashboard retain the complete state. Human mail clients
    receive the same outcome in a calm body; only routing identifiers and a
    compact evidence revision belong in the mail receipt.
    """
    if report_message:
        _, separator, remainder = text.partition("\n\n")
        if not separator:
            return text.strip(), ""
        marker = remainder.rfind("\n\nRALLY WATERMARK")
        if marker < 0:
            return remainder.strip(), ""
        prose = remainder[:marker].strip()
        technical = remainder[marker + 2:].strip()
    else:
        before, separator, technical = text.partition("\n\nTECHNICAL RECORD\n")
        if not separator:
            return text.strip(), ""
        _, header_break, prose = before.partition("\n\n")
        prose = prose if header_break else before
    # Local paths are useful to the runner, not to the person reading mail.
    technical = re.sub(r"(?m)^Workdir:\s*.*$", "", technical).strip()
    return prose.strip(), technical


def _prose_html(prose: str) -> str:
    """Render restrained, email-safe executive prose without a Markdown engine."""
    output: List[str] = []
    in_list = False
    known_headings = {
        "outcome", "what changed", "independent proof", "next step",
        "your request", "what rally needs from you", "still open",
    }
    for raw in prose.splitlines():
        line = _clean_markdown(raw)
        if not line:
            if in_list:
                output.append("</ul>")
                in_list = False
            continue
        if line.startswith("- ") or line.startswith("• "):
            if not in_list:
                output.append('<ul style="margin:8px 0 18px;padding-left:22px">')
                in_list = True
            output.append(
                '<li style="margin:0 0 8px;color:#243652;font-size:15px;'
                'line-height:1.6">%s</li>' % html.escape(line[2:].strip())
            )
            continue
        if in_list:
            output.append("</ul>")
            in_list = False
        heading = line.rstrip(":").casefold()
        if heading in known_headings or raw.lstrip().startswith("#"):
            output.append(
                '<h2 style="margin:22px 0 8px;color:#10233f;font-size:15px;'
                'line-height:1.35;font-weight:700">%s</h2>' % html.escape(line.rstrip(":"))
            )
        else:
            output.append(
                '<p style="margin:0 0 14px;color:#33445f;font-size:15px;'
                'line-height:1.65">%s</p>' % html.escape(line)
            )
    if in_list:
        output.append("</ul>")
    return "".join(output)


def _rally_lifecycle_message(subject: str, text: str, headers: Dict[str, str],
                             attachment_note: str = "",
                             inline_image_cid: str = "") -> Dict[str, str]:
    """Build one universally compatible executive-first lifecycle message."""
    run_id = str(headers.get("X-Rally-Run") or "").strip()
    report_status = str(headers.get("X-Rally-Report") or "").strip().upper()
    turn = str(headers.get("X-Rally-Turn") or "").strip()
    is_report = bool(report_status)
    prose, technical = _rally_sections(text, is_report)
    task_match = RALLY_SUBJECT.match(subject)
    task = (task_match.group(1).strip() if task_match else subject.strip())

    if report_status == "COMPLETE":
        label, headline, subject_state = "Complete", "Your work is ready.", "Complete"
        next_step = ("No action is required. Reply in this thread if you want Rally "
                     "to extend or revise the result.")
        accent, badge_bg = "#188038", "#e6f4ea"
    elif is_report:
        label, headline, subject_state = "Action needed", "Rally needs your input.", "Action needed"
        next_step = ("Reply in this thread with the missing decision, access, or material. "
                     "Rally will resume this same run under the existing approval and "
                     "independent-verification rules.")
        accent, badge_bg = "#b06000", "#fef7e0"
    elif turn == "0":
        label, headline, subject_state = "In progress", "Your request is underway.", "Request accepted"
        next_step = ("No action is required. To redirect the work, reply in this thread. "
                     "Start your reply with STOP to stop the run safely.")
        accent, badge_bg = "#0b57d0", "#e8f0fe"
    else:
        label, headline, subject_state = "In progress", "Rally is moving the work forward.", "Progress update"
        next_step = ("No action is required. To add direction, reply in this thread. "
                     "Start your reply with STOP to stop the run safely.")
        accent, badge_bg = "#0b57d0", "#e8f0fe"

    polished_subject = "[rally #%s] %s — %s" % (run_id, subject_state, task)
    phase = "Final report" if is_report else ("Turn %s" % (turn or "—"))
    audit_lines = [
        "Run: %s" % run_id,
        "Stage: %s" % phase,
        "Status: %s" % label,
        "Reply route: %s" % _reply_address(),
    ]
    commit_match = re.search(r"(?m)^commit:\s*([^\s]+)", technical)
    if commit_match and commit_match.group(1).casefold() != "none":
        audit_lines.append("Evidence revision: %s" % commit_match.group(1))
    plain_sections = [
        "RALLY — %s" % label.upper(),
        headline,
        "",
        prose.strip(),
        "",
        "NEXT STEP",
        next_step,
    ]
    if attachment_note:
        plain_sections += ["", "DELIVERABLE", attachment_note]
    plain_sections += [
        "",
        "----------------------------------------",
        "AUDIT RECEIPT",
        *audit_lines,
        "Policy: no model approves its own work.",
    ]
    plain = "\n".join(plain_sections)
    plain += "\n"

    safe_label = html.escape(label)
    safe_headline = html.escape(headline)
    safe_next = html.escape(next_step)
    safe_run = html.escape(run_id)
    safe_phase = html.escape(phase)
    safe_task = html.escape(task)
    safe_attachment_note = html.escape(attachment_note)
    preheader = html.escape("%s %s" % (headline, task))
    body = _prose_html(prose)
    attachment_html = ""
    if attachment_note:
        attachment_html = """<tr><td class="rally-pad" style="padding:4px 32px 12px">
<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" border="0" style="width:100%%;background:#f7f9fc;border:1px solid #e3e9f1;border-radius:10px">
<tr><td style="padding:14px 16px"><p style="margin:0 0 4px;color:#66758c;font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:.04em">DELIVERABLE</p>
<p class="rally-copy" style="margin:0;color:#34445d;font-family:Arial,sans-serif;font-size:13px;line-height:1.5">%s</p></td></tr></table>
</td></tr>""" % safe_attachment_note
    inline_image_html = ""
    if inline_image_cid:
        safe_cid = html.escape(inline_image_cid, quote=True)
        inline_image_html = """<tr><td class="rally-pad" style="padding:4px 32px 18px">
<img src="cid:%s" alt="Generated image deliverable" width="556" style="display:block;width:100%%;max-width:556px;height:auto;border:1px solid #dce4ef;border-radius:14px">
</td></tr>""" % safe_cid
    # Layout tables and inline styles are intentional: Outlook desktop, Gmail,
    # Apple Mail and Proton all handle this subset consistently. The tiny media
    # rule only improves narrow screens and dark-mode clients; content remains
    # complete when it is ignored.
    html_message = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>%s</title><style>
@media only screen and (max-width:640px){.rally-shell{width:100%%!important}.rally-pad{padding-left:22px!important;padding-right:22px!important}}
@media (prefers-color-scheme:dark){.rally-page{background:#0f1724!important}.rally-card{background:#172235!important;border-color:#34435a!important}.rally-copy{color:#dbe5f5!important}.rally-muted{color:#aebbd0!important}.rally-audit{background:#111c2d!important;border-color:#34435a!important}}
</style></head>
<body class="rally-page" style="margin:0;padding:0;background:#f3f6fb;color:#10233f;-webkit-text-size-adjust:100%%;text-size-adjust:100%%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">%s</div>
<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" border="0" style="width:100%%;background:#f3f6fb">
<tr><td align="center" style="padding:28px 12px">
<table class="rally-shell rally-card" role="article" aria-label="Rally %s" width="620" cellspacing="0" cellpadding="0" border="0" style="width:620px;max-width:620px;background:#ffffff;border:1px solid #dce4ef;border-radius:18px">
<tr><td class="rally-pad" style="padding:24px 32px;border-bottom:1px solid #e3e9f1">
<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
<td aria-hidden="true" width="42" height="42" align="center" valign="middle" style="width:42px;height:42px;border-radius:12px;background:#0b57d0;color:#ffffff;font-family:Arial,sans-serif;font-size:21px;font-weight:700">R</td>
<td style="padding-left:12px;color:#10233f;font-family:Arial,sans-serif;font-size:20px;font-weight:700">Rally</td>
</tr></table></td></tr>
<tr><td class="rally-pad" style="padding:30px 32px 12px">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:%s;color:%s;font-family:Arial,sans-serif;font-size:12px;line-height:1;font-weight:700">%s</span>
<h1 class="rally-copy" style="margin:16px 0 8px;color:#10233f;font-family:Arial,sans-serif;font-size:28px;line-height:1.25;font-weight:700">%s</h1>
<p class="rally-muted" style="margin:0;color:#66758c;font-family:Arial,sans-serif;font-size:14px;line-height:1.5">%s</p>
</td></tr>
<tr><td class="rally-pad rally-copy" style="padding:12px 32px 8px;font-family:Arial,sans-serif">%s</td></tr>
%s
%s
<tr><td class="rally-pad" style="padding:12px 32px 28px">
<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" border="0" style="width:100%%;background:#edf4ff;border-left:4px solid #0b57d0;border-radius:10px">
<tr><td style="padding:16px 18px"><p style="margin:0 0 5px;color:#0b57d0;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:.04em">NEXT STEP</p>
<p class="rally-copy" style="margin:0;color:#243652;font-family:Arial,sans-serif;font-size:14px;line-height:1.55">%s</p></td></tr></table>
</td></tr>
<tr><td class="rally-pad rally-audit" style="padding:18px 32px;background:#f7f9fc;border-top:1px solid #e3e9f1;border-radius:0 0 18px 18px">
<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" border="0"><tr>
<td class="rally-muted" style="color:#66758c;font-family:Arial,sans-serif;font-size:11px;line-height:1.55">AUDIT RECEIPT<br><span style="color:#34445d">Run %s · %s · %s</span><br>No model approves its own work.</td>
</tr></table></td></tr>
</table></td></tr></table></body></html>""" % (
        safe_task, preheader, safe_label, badge_bg, accent, safe_label,
        safe_headline, safe_task, body, inline_image_html, attachment_html, safe_next, safe_run,
        safe_phase, safe_label,
    )
    return {
        "subject": polished_subject,
        "text": plain,
        "html": html_message,
        "reply_to": _reply_address(),
    }


class SendBlocked(RuntimeError):
    """Raised instead of sending. Never caught into a retry."""


def get_key(service: str = "rally-resend") -> str:
    """Read one credential without letting one env var impersonate another.

    The runner uses this helper for both Resend and the ingress bearer.  A
    process-level Resend override must never become the Worker bearer merely
    because both credentials share the same Keychain helper.
    """
    env_name = {
        "rally-resend": "RESEND_API_KEY",
        "rally-poll-token": "RALLY_POLL_TOKEN",
    }.get(service)
    env = os.environ.get(env_name) if env_name else None
    if env:
        return env
    try:
        p = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
        if p.returncode == 0:
            key = p.stdout.decode().strip()
            if key:
                return key
    except Exception:
        pass
    hint = "set %s or " % env_name if env_name else ""
    raise SendBlocked(
        "no credential: %sstore it in the keychain as %r" % (hint, service)
    )


class Ledger:
    """Send counters. Fails closed on any read problem."""

    def __init__(self, path: str):
        self.path = path

    def _read(self) -> Dict:
        if not os.path.exists(self.path):
            return {"sends": []}
        with open(self.path) as fh:
            return json.load(fh)

    def check_and_reserve(self, run_id: str, per_run: int,
                          per_hour: int = 30, per_day: int = 200,
                          reservation_key: Optional[str] = None) -> None:
        try:
            data = self._read()
        except Exception as exc:
            raise SendBlocked("send ledger unreadable, failing closed: %s" % exc)
        now = time.time()
        sends: List[Dict] = data.get("sends", [])
        sends = [s for s in sends if now - s.get("at", 0) < 86400]
        # A final report retry is the same logical provider request, identified
        # by its stable Resend idempotency key. Its first attempt already owns a
        # quota reservation; retries must not consume the ceiling repeatedly.
        if reservation_key and any(
            s.get("run") == run_id
            and s.get("reservation_key") == reservation_key
            for s in sends
        ):
            return
        run_count = sum(1 for s in sends if s.get("run") == run_id)
        hour_count = sum(1 for s in sends if now - s.get("at", 0) < 3600)
        if run_count >= per_run:
            raise SendBlocked("run %s hit its %d send ceiling" % (run_id, per_run))
        if hour_count >= per_hour:
            raise SendBlocked("global hourly ceiling of %d reached" % per_hour)
        if len(sends) >= per_day:
            raise SendBlocked("global daily ceiling of %d reached" % per_day)
        entry = {"run": run_id, "at": now}
        if reservation_key:
            entry["reservation_key"] = reservation_key
        sends.append(entry)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"sends": sends}, fh)
        os.replace(tmp, self.path)


def send(key: str, sender: str, to: str, subject: str, text: str,
         cc: Optional[str] = None, headers: Optional[Dict[str, str]] = None,
         reply_to: Optional[str] = None, html: Optional[str] = None,
         idempotency_key: Optional[str] = None) -> str:
    # Lifecycle mail is rendered here, at the last shared boundary, so every
    # acknowledgement, progress note and final report has the same executive
    # voice. The run tag remains first in the subject and in X-Rally-Run,
    # preserving reply routing and replay semantics without exposing checklist
    # JSON or workstation paths to the human recipient.
    attachments = []
    attachment_note = ""
    if headers and str(headers.get("X-Rally-Report") or "").upper() == "COMPLETE":
        try:
            attachments, attachment_note = final_artifact_attachments(
                str(headers.get("X-Rally-Run") or "")
            )
        except Exception:
            # Delivery of the verified report is more important than its
            # convenience copy. Never let a filesystem race suppress the mail.
            attachments = []
            attachment_note = (
                "Rally could not safely attach the deliverable; the verified "
                "result is included above."
            )
    if headers and headers.get("X-Rally-Run"):
        inline_image_cid = next(
            (str(item.get("content_id")) for item in attachments
             if item.get("content_id")),
            "",
        )
        rendered = _rally_lifecycle_message(
            subject, text, headers, attachment_note=attachment_note,
            inline_image_cid=inline_image_cid,
        )
        subject = rendered["subject"]
        text = rendered["text"]
        html = rendered["html"]
        reply_to = reply_to or rendered["reply_to"]
    payload: Dict = {"from": sender, "to": [to], "subject": subject, "text": text}
    if html:
        payload["html"] = html
    if cc:
        payload["cc"] = [cc]
    if headers:
        payload["headers"] = headers
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = attachments
    request_headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    if idempotency_key:
        # Resend's idempotency contract is an HTTP request header. It must not
        # be placed in payload["headers"], which only controls message headers.
        request_headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(), headers=request_headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("id", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise SendBlocked("resend %d: %s" % (exc.code, body))
