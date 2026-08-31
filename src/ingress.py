"""Inbound: collect mail from the ingress Worker and turn it into runs.

The Worker holds messages durably because this process runs on a machine that
sleeps. Nothing here trusts the message: authority to commission a run comes from
the verified sender address, never from anything the body asks for.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email import policy
from email.errors import MultipartInvariantViolationDefect
from email.message import Message
from email.parser import BytesHeaderParser
from email.utils import getaddresses
from typing import Dict, List, Optional, Tuple

import transport

RESEND_INBOUND = "https://api.resend.com/emails/inbound/%s"
# Cloudflare answers urllib's default User-Agent with a 403. Every request Rally
# makes therefore identifies itself. Found the hard way: curl worked, the poller
# did not, and the failure looked like a credential problem.
USER_AGENT = "rally/1.0 (+https://github.com/Agent9AI/rally)"
RUN_TAG = re.compile(r"\[rally\s+#(r-[0-9a-z-]+)", re.IGNORECASE)
RUN_ID = re.compile(r"^r-[0-9a-z-]{3,77}$")
WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
USER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{1,253}$"
)
DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
MAX_EMAIL_BODY_CHARS = 6000
MAX_EMAIL_TASK_CHARS = 6000
MAX_RAW_HEADER_BYTES = 64 * 1024
MAX_RAW_HEADER_LINES = 512
MAX_RAW_HEADER_FIELDS = 256
MAX_RAW_HEADER_LINE_BYTES = 998
RAW_READ_CHUNK_BYTES = 4096
TRUSTED_AUTH_SERVICE = "amazonses.com"
RAW_DOWNLOAD_HOST_SUFFIXES = (".resend.com", ".resend.app")
AUTH_RESULT = re.compile(
    r"^([a-z][a-z0-9_-]*)(?:/[0-9]+)?\s*=\s*([a-z][a-z0-9_-]*)\b(.*)$",
    re.IGNORECASE,
)
REPLY_WROTE = re.compile(
    r"^\s*(?:-{2,}\s*)?On .+\bwrote(?::|\s*-{2,})\s*$",
    re.IGNORECASE,
)
ORIGINAL_MESSAGE = re.compile(
    r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE
)
FORWARDED_MESSAGE = re.compile(
    r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.IGNORECASE
)
MESSAGE_ID = re.compile(r"^<[^<>\s\x00-\x1f\x7f]{1,996}>$")
MOBILE_FOOTER = re.compile(
    r"^Sent from my (?:iPhone|iPad|Android)$", re.IGNORECASE
)
OUTLOOK_FOOTER = re.compile(
    r"^Get Outlook for (?:iOS|Android|Windows|Mac)"
    r"(?:\s*(?:<https?://[^>\s]+>|\[https?://[^\]\s]+\]|https?://\S+))?$",
    re.IGNORECASE,
)
SIGNATURE_NAME = re.compile(
    r"^[A-Z][A-Za-z0-9.'’-]+(?:\s+[A-Z][A-Za-z0-9.'’-]+){1,3}$"
)
SIGNATURE_EMAIL = re.compile(
    r"(?:mailto:)?[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    re.IGNORECASE,
)
SIGNATURE_PHONE = re.compile(
    r"(?:\+?\d[\d .()-]{7,}\d)"
)
SIGNATURE_URL = re.compile(
    r"^(?:https?://|www\.)\S+$", re.IGNORECASE
)


class RawMessageError(Exception):
    """A raw-message failure, annotated with whether another poll may fix it."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Signed raw URLs must resolve directly; never follow an unchecked redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url: str, token: str, timeout: int = 25) -> Dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                               "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(url: str, token: str, body: Dict, timeout: int = 25) -> Dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def find_email_id(payload: Dict) -> Optional[str]:
    """Resend nests the id differently across webhook versions. Accept both."""
    if not isinstance(payload, dict):
        return None
    if payload.get("email_id"):
        return payload["email_id"]
    data = payload.get("data")
    if isinstance(data, dict) and data.get("email_id"):
        return data["email_id"]
    if isinstance(data, dict) and data.get("id"):
        return data["id"]
    return payload.get("id")


def find_message_id(msg: Dict) -> Optional[str]:
    """Return the RFC message id when Resend includes it in the received mail."""
    if not isinstance(msg, dict):
        return None
    if isinstance(msg.get("message_id"), str):
        candidate = msg["message_id"].strip()
        if MESSAGE_ID.fullmatch(candidate):
            return candidate
    headers = msg.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if (isinstance(key, str) and key.lower() == "message-id"
                    and isinstance(value, str)):
                candidate = value.strip()
                if MESSAGE_ID.fullmatch(candidate):
                    return candidate
    return None


def fetch_message(email_id: str, resend_key: str) -> Dict:
    return _get(RESEND_INBOUND % email_id, resend_key)


def _validated_raw_url(msg: Dict) -> str:
    raw = msg.get("raw") if isinstance(msg, dict) else None
    url = raw.get("download_url") if isinstance(raw, dict) else None
    if not isinstance(url, str) or not url:
        # Resend can announce a message before its raw object is available.
        raise RawMessageError("Resend raw email is not available yet", retryable=True)
    if any(ord(character) < 33 or ord(character) == 127 for character in url):
        raise RawMessageError("Resend raw download URL contains unsafe characters")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        hostname = (parsed.hostname or "").lower()
    except ValueError:
        raise RawMessageError("Resend raw download URL is malformed")
    provider_host = (
        hostname == "resend.com"
        or hostname == "resend.app"
        or any(hostname.endswith(suffix) for suffix in RAW_DOWNLOAD_HOST_SUFFIXES)
    )
    if (parsed.scheme.lower() != "https" or not hostname or not provider_host
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 443) or parsed.fragment or not parsed.path):
        raise RawMessageError("Resend raw download URL failed safety validation")
    return url


def _open_raw(request: urllib.request.Request, timeout: int):
    """Open a signed URL without forwarding API credentials or following redirects."""
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _raw_header_block(response) -> bytes:
    """Read only the bounded RFC5322 header section from a raw-message stream."""
    data = bytearray()
    while len(data) <= MAX_RAW_HEADER_BYTES + 4:
        remaining = MAX_RAW_HEADER_BYTES + 5 - len(data)
        chunk = response.read(min(RAW_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise RawMessageError("Resend raw email returned non-byte content")
        data.extend(chunk)
        endings = [
            position for position in (
                data.find(b"\r\n\r\n"),
                data.find(b"\n\n"),
            ) if position >= 0
        ]
        if endings:
            end = min(endings)
            if end > MAX_RAW_HEADER_BYTES:
                break
            return bytes(data[:end])
    raise RawMessageError(
        "raw email header block is missing or exceeds %d bytes"
        % MAX_RAW_HEADER_BYTES
    )


def parse_raw_headers(header_block: bytes) -> Message:
    """Strictly parse a bounded RFC5322 header block while retaining duplicates."""
    if not isinstance(header_block, bytes) or len(header_block) > MAX_RAW_HEADER_BYTES:
        raise RawMessageError("raw email header block exceeds the allowed size")
    normalized = header_block.replace(b"\r\n", b"\n")
    if b"\r" in normalized or b"\x00" in normalized:
        raise RawMessageError("raw email headers contain invalid line endings or NUL")
    lines = normalized.split(b"\n") if normalized else []
    if len(lines) > MAX_RAW_HEADER_LINES:
        raise RawMessageError(
            "raw email headers exceed the %d-line limit" % MAX_RAW_HEADER_LINES
        )

    fields = 0
    for line in lines:
        if len(line) > MAX_RAW_HEADER_LINE_BYTES:
            raise RawMessageError(
                "raw email header line exceeds %d bytes" % MAX_RAW_HEADER_LINE_BYTES
            )
        if any(byte < 32 and byte != 9 or byte == 127 for byte in line):
            raise RawMessageError("raw email headers contain control characters")
        if line.startswith((b" ", b"\t")):
            if fields == 0:
                raise RawMessageError("raw email begins with an orphan folded header")
            continue
        name, separator, _ = line.partition(b":")
        if not separator or not re.fullmatch(rb"[A-Za-z0-9-]+", name):
            raise RawMessageError("raw email contains a malformed header field")
        fields += 1
        if fields > MAX_RAW_HEADER_FIELDS:
            raise RawMessageError(
                "raw email headers exceed the %d-field limit" % MAX_RAW_HEADER_FIELDS
            )

    try:
        parser = BytesHeaderParser(policy=policy.default.clone(raise_on_defect=False))
        headers = parser.parsebytes(normalized + b"\n\n", headersonly=True)

        # Structured header defects are populated lazily, so materialize every
        # physical value before deciding that the block is sound.
        checked = set()
        for name, _ in headers.raw_items():
            normalized_name = name.lower()
            if normalized_name in checked:
                continue
            checked.add(normalized_name)
            for value in headers.get_all(name, []):
                if getattr(value, "defects", ()):
                    raise RawMessageError("raw email contains a defective header field")

        message_defects = list(headers.defects)
        allowed_header_only_multipart = (
            len(message_defects) == 1
            and type(message_defects[0]) is MultipartInvariantViolationDefect
            and headers.get_content_maintype() == "multipart"
            and bool(headers.get_boundary())
        )
        if message_defects and not allowed_header_only_multipart:
            raise RawMessageError("raw email headers contain parser defects")
    except RawMessageError:
        raise
    except Exception as exc:
        raise RawMessageError("raw email headers could not be parsed: %s" % exc)
    return headers


def download_raw_headers(msg: Dict, timeout: int = 20) -> Message:
    """Download and parse only the original message's bounded header block."""
    url = _validated_raw_url(msg)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Range": "bytes=0-%d" % (MAX_RAW_HEADER_BYTES + 4),
        },
    )
    try:
        with _open_raw(request, timeout) as response:
            status = response.getcode() if hasattr(response, "getcode") else None
            if status is not None and status not in (200, 206):
                raise RawMessageError(
                    "Resend raw email download returned HTTP %d" % status,
                    retryable=status in (401, 403, 404, 408, 409, 425, 429)
                              or 500 <= status < 600,
                )
            block = _raw_header_block(response)
    except urllib.error.HTTPError as exc:
        retryable = exc.code in (401, 403, 404, 408, 409, 425, 429) or 500 <= exc.code < 600
        raise RawMessageError(
            "Resend raw email download returned HTTP %d" % exc.code,
            retryable=retryable,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RawMessageError(
            "Resend raw email download failed: %s" % exc,
            retryable=True,
        )
    return parse_raw_headers(block)


def addresses(value) -> List[str]:
    """Normalise Resend's to/from, which may be a string or a list."""
    out: List[str] = []
    items = value if isinstance(value, list) else [value]
    for v in items:
        if not v:
            continue
        s = v if isinstance(v, str) else (v.get("email") or "")
        m = re.search(r"[\w.+-]+@[\w.-]+", s)
        if m:
            out.append(m.group(0).lower())
    return out


def _footer_is_terminal(lines: List[str], index: int) -> bool:
    """A known client footer is safe to remove only at the message tail."""
    for line in lines[index + 1:]:
        stripped = line.strip()
        if not stripped or line.lstrip().startswith(">"):
            continue
        return bool(
            REPLY_WROTE.match(line)
            or ORIGINAL_MESSAGE.match(line)
            or FORWARDED_MESSAGE.match(line)
        )
    return True


def _rich_signature_start(lines: List[str]) -> Optional[int]:
    """Find a high-confidence rich-client signature without guessing at prose.

    Outlook and similar clients often omit the RFC ``-- `` separator and emit
    several blank lines before a contact card.  Rally removes only a compact,
    terminal card that starts with a plausible full name and contains at least
    two independent contact signals.  A normal sign-off such as
    ``Thanks,\nTerry\nCEO`` intentionally does not meet this threshold.
    """
    for index in range(2, len(lines)):
        if lines[index].strip() == "":
            continue
        blank_run = 0
        cursor = index - 1
        while cursor >= 0 and not lines[cursor].strip():
            blank_run += 1
            cursor -= 1
        if blank_run < 2:
            continue

        tail = [line.strip() for line in lines[index:] if line.strip()]
        if not 3 <= len(tail) <= 12 or not SIGNATURE_NAME.fullmatch(tail[0]):
            continue
        signals = 0
        if any(SIGNATURE_EMAIL.search(line) for line in tail):
            signals += 1
        if any(SIGNATURE_PHONE.search(line) for line in tail):
            signals += 1
        if any(SIGNATURE_URL.fullmatch(line) for line in tail):
            signals += 1
        if signals >= 2:
            return index
    return None


def strip_quoted(text: str) -> str:
    """Remove exact signature/footer markers and quoted reply tails."""
    source = (text or "").splitlines()
    rich_signature_start = _rich_signature_start(source)
    kept: List[str] = []
    for index, line in enumerate(source):
        if rich_signature_start is not None and index >= rich_signature_start:
            break
        stripped = line.strip()
        if line in ("-- ", "--"):
            break
        if (REPLY_WROTE.match(line) or ORIGINAL_MESSAGE.match(line)
                or FORWARDED_MESSAGE.match(line)):
            break
        if line.lstrip().startswith(">"):
            continue
        if (any(previous.strip() for previous in kept)
                and (MOBILE_FOOTER.fullmatch(stripped)
                     or OUTLOOK_FOOTER.fullmatch(stripped))
                and _footer_is_terminal(source, index)):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _visible_sender(value) -> Optional[str]:
    """Return one unambiguous RFC5322 From mailbox, or fail closed."""
    values = value if isinstance(value, list) else [value]
    field_values: List[str] = []
    for item in values:
        if isinstance(item, str):
            field_values.append(item)
        elif isinstance(item, dict) and isinstance(item.get("email"), str):
            field_values.append(item["email"])
        elif item is not None:
            return None
    try:
        parsed = [valid_email(address) for _, address in getaddresses(field_values)]
    except (TypeError, ValueError):
        return None
    if len(parsed) != 1 or parsed[0] is None:
        return None
    return parsed[0]


def _header_values(headers: Optional[Message], name: str) -> List[str]:
    """Return every physical field value retained by the RFC5322 parser."""
    if not isinstance(headers, Message):
        return []
    values = headers.get_all(name, [])
    return [str(value) for value in values]


def original_message_id(msg: Dict, raw_headers: Optional[Message]) -> Optional[str]:
    """Prefer the original RFC5322 Message-ID over a provider projection.

    Rally already downloads the bounded raw header block for authentication.
    Reusing its single, validated Message-ID keeps replies in the user's real
    thread even when the Receiving API projection omits that optional field.
    """
    values = _header_values(raw_headers, "Message-ID")
    if len(values) == 1:
        candidate = values[0].strip()
        if MESSAGE_ID.fullmatch(candidate):
            return candidate
    return find_message_id(msg)


def _authentication_results(headers: Optional[Message]) -> Optional[str]:
    """Return exactly one Authentication-Results field from the original MIME."""
    matches = _header_values(headers, "Authentication-Results")
    if len(matches) != 1:
        return None
    value = matches[0]
    if not value or "\x00" in value:
        return None
    # RFC header folding is safe to unfold. Any remaining newline could smuggle a
    # second field and is therefore rejected.
    value = re.sub(r"\r?\n[ \t]+", " ", value)
    if "\r" in value or "\n" in value:
        return None
    return value.strip()


def _without_comments(value: str) -> Optional[str]:
    """Remove RFC-style comments without treating their text as auth evidence."""
    out: List[str] = []
    depth = 0
    quoted = False
    escaped = False
    for character in value:
        if escaped:
            if depth == 0:
                out.append(character)
            escaped = False
            continue
        if character == "\\" and (depth > 0 or quoted):
            if depth == 0:
                out.append(character)
            escaped = True
            continue
        if depth > 0:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            continue
        if quoted:
            out.append(character)
            if character == '"':
                quoted = False
            continue
        if character == "(":
            depth = 1
        elif character == ")":
            return None
        else:
            out.append(character)
            if character == '"':
                quoted = True
    if depth or quoted or escaped:
        return None
    return "".join(out)


def _auth_segments(value: str) -> Optional[List[str]]:
    """Split Authentication-Results on semicolons outside quoted values."""
    value = _without_comments(value)
    if value is None:
        return None
    segments: List[str] = []
    current: List[str] = []
    quoted = False
    escaped = False
    for character in value:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\" and quoted:
            current.append(character)
            escaped = True
            continue
        if character == '"':
            current.append(character)
            quoted = not quoted
        elif character == ";" and not quoted:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if quoted or escaped:
        return None
    segments.append("".join(current).strip())
    return segments


def _auth_property(segment: str, name: str) -> Optional[str]:
    pattern = re.compile(
        r"(?<![a-z0-9_.-])"
        + re.escape(name).replace(r"\.", r"\s*\.\s*")
        + r"\s*=\s*(\"(?:\\.|[^\"\\])*\"|[^\s;]+)",
        re.IGNORECASE,
    )
    values = pattern.findall(segment)
    if len(values) != 1:
        return None
    value = values[0]
    if value.startswith('"'):
        value = re.sub(r"\\(.)", r"\1", value[1:-1])
    if not value or any(ord(character) < 33 or ord(character) == 127 for character in value):
        return None
    return value


def _auth_domain(value: str, identity: bool = False) -> Optional[str]:
    """Extract and validate a domain from header.from or DKIM header.i."""
    candidate = value.strip().lower()
    if "@" in candidate:
        if candidate.count("@") != 1:
            return None
        local_part, candidate = candidate.rsplit("@", 1)
        # DKIM permits an empty AUID local part ("@example.com"). DMARC's
        # header.from is normally a domain, but SES also emits full mailboxes.
        if not identity and not local_part:
            return None
    labels = candidate.split(".")
    if (len(candidate) > 253 or len(labels) < 2
            or not all(DOMAIN_LABEL.fullmatch(label) for label in labels)):
        return None
    return candidate


def _aligned_domain(authenticated: str, visible: str) -> bool:
    """Accept an exact domain or a direct DNS ancestor/descendant alignment."""
    return (authenticated == visible
            or authenticated.endswith("." + visible)
            or visible.endswith("." + authenticated))


def _email_authenticates(headers: Optional[Message], sender: str) -> bool:
    """Require an SES-authored DMARC pass and an aligned DKIM pass."""
    header = _authentication_results(headers)
    segments = _auth_segments(header) if header is not None else None
    if not segments or not re.fullmatch(
        re.escape(TRUSTED_AUTH_SERVICE) + r"(?:\s+[0-9]+)?",
        segments[0],
        re.IGNORECASE,
    ):
        return False

    results = {"dkim": [], "dmarc": []}
    for segment in segments[1:]:
        if not segment:
            continue
        match = AUTH_RESULT.fullmatch(segment)
        if match is None:
            return False
        method, result = match.group(1).lower(), match.group(2).lower()
        if method in results:
            results[method].append((result, match.group(3)))

    # Selecting one verdict from duplicates would make ordering security-sensitive.
    if len(results["dkim"]) != 1 or len(results["dmarc"]) != 1:
        return False
    dkim_result, dkim_details = results["dkim"][0]
    dmarc_result, dmarc_details = results["dmarc"][0]
    if dkim_result != "pass" or dmarc_result != "pass":
        return False

    dkim_identity = _auth_property(dkim_details, "header.i")
    dmarc_from = _auth_property(dmarc_details, "header.from")
    dkim_domain = _auth_domain(dkim_identity, identity=True) if dkim_identity else None
    dmarc_domain = _auth_domain(dmarc_from) if dmarc_from else None
    visible_domain = sender.rsplit("@", 1)[1]
    return (dmarc_domain == visible_domain
            and dkim_domain is not None
            and _aligned_domain(dkim_domain, visible_domain))


def classify(msg: Dict, cfg: Dict, raw_headers: Optional[Message] = None) -> Tuple[str, Dict]:
    """Decide what an inbound message is. Returns (kind, details).

    kind is one of: commission, note, ignored.
    """
    ing = cfg["ingress"]
    owners = {a.lower() for a in ing.get("owners", [])}
    projected_sender = _visible_sender(msg.get("from"))
    raw_from = _header_values(raw_headers, "From")
    sender = _visible_sender(raw_from[0]) if len(raw_from) == 1 else None
    to = set(addresses(msg.get("to")) + addresses(msg.get("cc")))
    subject = msg.get("subject") if isinstance(msg.get("subject"), str) else ""
    # A mail subject is often the actual request ("Create a beagle image") and
    # the body merely supplies preferences or context. Collapse whitespace so
    # an RFC-folded subject stays readable, then put it first in the commission.
    request_title = " ".join(subject.split())
    body = strip_quoted(msg.get("text") if isinstance(msg.get("text"), str) else "")
    message_id = original_message_id(msg, raw_headers)

    if sender is None or projected_sender is None or sender != projected_sender:
        return "ignored", {
            "why": "original email From must contain exactly one address matching Resend"
        }
    if sender not in owners:
        # Authority comes from the verified sender, never from the body.
        return "ignored", {"why": "sender %s is not an owner" % sender}

    tagged = RUN_TAG.search(subject)
    is_commission = ing["commission_address"].lower() in to
    if tagged or is_commission:
        if not _email_authenticates(raw_headers, sender):
            return "ignored", {
                "why": "email authentication failed: require one amazonses.com "
                       "Authentication-Results header with aligned DKIM and DMARC passes"
            }
        if len(body) > MAX_EMAIL_BODY_CHARS:
            return "ignored", {
                "why": "normalized email body is %d characters; maximum is %d; "
                       "shorten it and resend"
                       % (len(body), MAX_EMAIL_BODY_CHARS)
            }
        if tagged:
            return "note", {
                "run_id": tagged.group(1), "text": body, "sender": sender,
                "message_id": message_id,
            }
        if request_title and body and request_title.casefold() != body.casefold():
            task = "%s\n\n%s" % (request_title, body)
        else:
            task = request_title or body
        if not task:
            return "ignored", {"why": "empty commission subject and body"}
        if len(task) > MAX_EMAIL_TASK_CHARS:
            return "ignored", {
                "why": "normalized email subject and body are %d characters; "
                       "maximum is %d; shorten them and resend"
                       % (len(task), MAX_EMAIL_TASK_CHARS)
            }
        return "commission", {
            "task": task, "subject": subject, "sender": sender,
            "message_id": message_id,
        }

    return "ignored", {"why": "not addressed to the commission address"}


def valid_email(value) -> Optional[str]:
    """Return the same normalized address accepted by the control plane."""
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if not EMAIL.fullmatch(email):
        return None
    local_part, domain = email.rsplit("@", 1)
    labels = domain.split(".")
    if (local_part.startswith(".") or local_part.endswith(".")
            or ".." in local_part or len(labels) < 2
            or not all(DOMAIN_LABEL.fullmatch(label) for label in labels)):
        return None
    return email


def classify_dashboard(payload: Dict) -> Tuple[str, Dict]:
    """Validate one server-authored dashboard envelope as a commission only."""
    invalid = ("ignored", {"why": "invalid dashboard commission envelope"})
    if not isinstance(payload, dict) or set(payload) != {
        "source", "schema_version", "run_id", "accepted_at",
        "request_fingerprint", "job", "authority",
    }:
        return invalid
    if (payload.get("source") != "dashboard"
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != 1):
        return invalid
    run_id = payload.get("run_id")
    accepted_at = payload.get("accepted_at")
    fingerprint = payload.get("request_fingerprint")
    if (not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id)
            or not isinstance(accepted_at, str) or not TIMESTAMP.fullmatch(accepted_at)
            or not isinstance(fingerprint, str) or not SHA256_HEX.fullmatch(fingerprint)):
        return invalid

    job = payload.get("job")
    authority = payload.get("authority")
    if not isinstance(job, dict) or set(job) != {
        "title", "goal", "source_run_id", "second_wind",
    }:
        return invalid
    if not isinstance(authority, dict) or set(authority) != {
        "user_id", "email", "workspace_id",
    }:
        return invalid
    title = job.get("title")
    goal = job.get("goal")
    source_run_id = job.get("source_run_id")
    second_wind = job.get("second_wind")
    if (not isinstance(title, str) or not title or title != title.strip()
            or len(title) > 160
            or "\n" in title or "\r" in title
            or any(ord(character) < 32 or ord(character) == 127 for character in title)
            or not isinstance(goal, str) or not goal or goal != goal.strip()
            or len(goal) > 6000
            or any(
                ord(character) < 32 and character not in "\n\t" or ord(character) == 127
                for character in goal
            )
            or (source_run_id is not None and (
                not isinstance(source_run_id, str) or not RUN_ID.fullmatch(source_run_id)
            ))
            or (second_wind is not None and not isinstance(second_wind, bool))):
        return invalid
    user_id = authority.get("user_id")
    workspace_id = authority.get("workspace_id")
    sender = valid_email(authority.get("email"))
    if (not isinstance(user_id, str) or not USER_ID.fullmatch(user_id)
            or not isinstance(workspace_id, str) or not WORKSPACE_ID.fullmatch(workspace_id)
            or sender is None):
        return invalid

    task = "%s\n\nGoal:\n%s" % (title, goal)
    if source_run_id:
        task += "\n\nContinue from Rally run %s." % source_run_id
    return "commission", {
        "task": task,
        "subject": title,
        "sender": sender,
        "message_id": None,
        "run_id": run_id,
        "request_key": run_id,
        "source_run_id": source_run_id,
        "second_wind": second_wind,
        "workspace_id": workspace_id,
    }


def collect(cfg: Dict) -> List[Dict]:
    """Pull pending messages from the Worker and hydrate them from Resend."""
    ing = cfg["ingress"]
    base = (ing.get("worker_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("ingress.worker_url is not configured")
    poll_token = transport.get_key(ing.get("poll_token_keychain", "rally-poll-token"))

    pending = _get(base + "/pending", poll_token).get("messages", [])
    out: List[Dict] = []
    resend_key: Optional[str] = None
    for rec in pending:
        payload = rec.get("payload") or {}
        if isinstance(payload, dict) and "type" in payload:
            if payload.get("type") != "email.received":
                out.append({
                    "id": rec["id"], "kind": "ignored",
                    "detail": {"why": "unsupported Resend event %s"
                               % str(payload.get("type") or "unknown")[:80]},
                })
                continue
        elif isinstance(payload, dict) and payload.get("source") == "dashboard":
            kind, detail = classify_dashboard(payload)
            out.append({
                "id": rec["id"], "kind": kind, "detail": detail,
                "subject": detail.get("subject"), "from": detail.get("sender"),
            })
            continue
        else:
            out.append({
                "id": rec["id"], "kind": "ignored",
                "detail": {"why": "unsupported ingress envelope"},
            })
            continue

        eid = find_email_id(payload)
        if not eid:
            out.append({"id": rec["id"], "error": "no email_id in payload"})
            continue
        try:
            if resend_key is None:
                resend_key = transport.get_key(
                    cfg["mail"].get("keychain_service", "rally-resend")
                )
            msg = fetch_message(eid, resend_key)
        except urllib.error.HTTPError as exc:
            out.append({
                "id": rec["id"],
                "error": "resend %d" % exc.code,
                # The webhook commonly wins a short race with Receiving API
                # materialization, so a first 404 must remain queued.
                "retryable": exc.code in (404, 408, 409, 425, 429)
                             or 500 <= exc.code < 600,
            })
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            out.append({
                "id": rec["id"],
                "error": "resend hydration failed: %s" % exc,
                "retryable": True,
            })
            continue
        try:
            raw_headers = download_raw_headers(msg)
        except RawMessageError as exc:
            if exc.retryable:
                out.append({
                    "id": rec["id"],
                    "error": str(exc),
                    "retryable": True,
                })
            else:
                out.append({
                    "id": rec["id"],
                    "kind": "ignored",
                    "detail": {"why": "raw email rejected: %s" % exc},
                    "subject": msg.get("subject"),
                    "from": msg.get("from"),
                })
            continue
        kind, detail = classify(msg, cfg, raw_headers)
        out.append({"id": rec["id"], "kind": kind, "detail": detail,
                    "subject": msg.get("subject"), "from": msg.get("from")})
    return out


def ack(cfg: Dict, ids: List[str]) -> None:
    if not ids:
        return
    ing = cfg["ingress"]
    base = ing["worker_url"].rstrip("/")
    poll_token = transport.get_key(ing.get("poll_token_keychain", "rally-poll-token"))
    _post(base + "/ack", poll_token, {"ids": ids})
