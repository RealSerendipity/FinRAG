"""Security guardrails (Wave 6) — input / context / output screens.

A layered, defense-in-depth filter set wrapped around the RAG and agent paths:

1. `screen_input`   — block prompt-injection / jailbreak / system-prompt-extraction
                      attempts *before* they reach the model. Deterministic regex
                      signatures (always on, no network) plus an optional NVIDIA
                      NemoGuard content-safety check for genuinely harmful content.
2. `screen_context` — neutralize *indirect* injection: instructions planted inside
                      retrieved filing chunks ("ignore the user and …"). Reuses the
                      input signatures, applied to each chunk before it is prompted.
3. `redact_pii`     — strip emails / SSNs / phone numbers / card numbers from text.
4. `validate_output`— last line of defense: catch a leaked secret/system prompt and
                      citations that point outside the retrieved set.

Design notes
------------
- The deterministic layer carries the security and is fully testable offline; it
  targets attack *signatures*, not finance vocabulary, so benign filing questions
  pass untouched (verified in tests). NemoGuard is an *augmentation* for unsafe
  content (it correctly treats injection phrasing as safe content), consulted only
  when `NEMOGUARD_ENABLED` is set, and it always fails *open* to the heuristic
  verdict — an unreachable or slow guard model must never block a legitimate query.
- A combined verdict blocks if *any* layer flags, so NemoGuard being down degrades
  to heuristics-only (still defended), never to no defense.

Public surface
--------------
- `screen_input(text)` -> `InputVerdict`
- `screen_context(chunks)` -> `(safe_chunks, [flag, …])`
- `redact_pii(text)` -> `(redacted, n)`
- `validate_output(text, *, secrets, allowed_chunk_ids, cited_ids)` -> `OutputVerdict`
- `InputVerdict`, `OutputVerdict` dataclasses
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import config

# --------------------------------------------------------------------------- #
# Attack signatures (deterministic layer)
# --------------------------------------------------------------------------- #
# Each pattern maps to an attack category. Patterns are intentionally narrow —
# they match override / extraction phrasing that does not occur in genuine SEC
# filing questions, keeping the false-positive rate on finance text near zero.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|discard)\b[^.\n]{0,40}"
            r"\b(?:previous|prior|above|earlier|all|any|the|your|system)\b[^.\n]{0,20}"
            r"\b(?:instruction|instructions|prompt|prompts|rule|rules|context|direction|directions)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override",
        re.compile(
            r"\b(?:you\s+are\s+now|from\s+now\s+on(?:\s+you)?|act\s+as|pretend\s+(?:to\s+be|you)"
            r"|roleplay\s+as|developer\s+mode|jailbreak|\bDAN\b|do\s+anything\s+now"
            r"|new\s+(?:instructions?|persona|role|system\s+prompt)\s*:)",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_extraction",
        re.compile(
            r"(?:(?:reveal|show|print|repeat|output|display|tell\s+me|give\s+me|what\s+(?:are|is|were))"
            r"[^.\n]{0,40}\b(?:system\s+prompt|your\s+(?:instructions?|prompt|rules|guidelines|directives)"
            r"|initial\s+(?:prompt|instructions?)|the\s+(?:prompt|instructions?)\s+above))"
            r"|repeat\s+(?:the\s+)?(?:words|text|everything)\s+above"
            r"|verbatim[^.\n]{0,20}(?:prompt|instructions?)",
            re.IGNORECASE,
        ),
    ),
    (
        "embedded_directive",
        re.compile(
            r"</?(?:system|instructions?|admin|important)\s*>"
            r"|\[(?:system|inst|admin)\]"
            r"|(?:^|\n)\s*(?:system|assistant|admin)\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration",
        # Marker elicitation: "reply with exactly X" / "respond with the verbatim
        # string X". The trailing lookahead exempts quote-FROM-the-document requests
        # ("repeat the exact phrase used about …", "say exactly what management
        # said") — quoting filings is the product's core use case, not an attack.
        re.compile(
            r"(?:respond|reply|answer|say|output|print|write|repeat)\b[^.\n]{0,20}?"
            r"(?:\bexactly\b|\bverbatim\b|\bexact\s+(?:phrase|word|string|text)\b"
            r"|\bthe\s+(?:phrase|word|string|text)\b)"
            r"(?!\s+(?:of|from|in|used|that|which|what|how|when|where|appearing|found)\b)",
            re.IGNORECASE,
        ),
    ),
)

# A handful of Chinese-language injection phrasings (cross-language attacks bypass
# English-only filters; execution.md calls this out as its own red-team category).
_INJECTION_PATTERNS_ZH: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(r"(?:忽略|无视|忘记|不要理会|放弃)[^。\n]{0,12}(?:之前|以上|上面|所有|系统|先前)?"
                   r"[^。\n]{0,8}(?:指令|指示|提示|规则|要求)"),
    ),
    (
        "system_prompt_extraction",
        re.compile(r"(?:显示|展示|打印|重复|输出|告诉我|说出)[^。\n]{0,12}"
                   r"(?:系统提示|你的(?:指令|提示|规则|设定)|初始(?:提示|指令)|上面的(?:提示|指令))"),
    ),
    (
        "role_override",
        # 扮演/从现在起 need directive context: bare 扮演 appears in benign finance
        # questions ("公司在市场中扮演的角色"), and 从现在起 in time-range questions
        # ("从现在起到2026年"). Require an imperative subject (请/你) or a persona
        # object (一个/一位/一名) around them.
        re.compile(r"(?:你现在是|从现在起[,,]?\s*你|(?:请你?|你(?:必须|需要|来|就|要)?)扮演"
                   r"|扮演(?:一个|一位|一名)|假装(?:你是|成为)|进入开发者模式|越狱)"),
    ),
)


@dataclass(frozen=True)
class InputVerdict:
    """Outcome of screening a user (or context) string.

    `allowed=False` means the request should be refused before the model runs.
    `categories` lists every signature/guard that fired; `detail` is a short
    human-readable reason for traces and the red-team report.
    """

    allowed: bool
    categories: tuple[str, ...] = ()
    detail: str = ""

    @property
    def blocked(self) -> bool:
        return not self.allowed


@dataclass
class OutputVerdict:
    """Outcome of validating a generated answer before it is returned."""

    allowed: bool
    categories: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def blocked(self) -> bool:
        return not self.allowed


# Safe, fixed refusals returned in place of a blocked answer. Distinct per layer
# so a caller (or a trace reader) can tell WHERE the defense fired.
REFUSAL_TEXT = (
    "This request was blocked by finrag's input guardrails: it looks like an attempt "
    "to override the assistant's instructions or extract its configuration. finrag "
    "only answers questions about ingested SEC filings."
)
REFUSAL_TEXT_CONTEXT = (
    "Every passage retrieved for this question was filtered out by finrag's context "
    "guardrails because it carried planted instructions. finrag cannot answer safely "
    "from the remaining context."
)
REFUSAL_TEXT_OUTPUT = (
    "The generated answer was withheld by finrag's output guardrails: it contained "
    "configuration or instruction content that must not be disclosed. Please rephrase "
    "the question."
)


def _heuristic_hits(text: str) -> list[str]:
    """Return the distinct attack categories whose signatures match `text`."""
    hits: list[str] = []
    for category, pattern in _INJECTION_PATTERNS + _INJECTION_PATTERNS_ZH:
        if pattern.search(text) and category not in hits:
            hits.append(category)
    return hits


# --------------------------------------------------------------------------- #
# NVIDIA NemoGuard content-safety (optional augmentation, fail-open)
# --------------------------------------------------------------------------- #
# Compact rendering of NeMo Guardrails' content-safety policy. The model needs the
# taxonomy in-context; with a bare message it defaults to "safe" (verified). It
# rates *content* harm (violence, weapons, fraud, …), not injection, so it
# complements — does not replace — the heuristic injection layer.
_NEMOGUARD_POLICY = """Task: Check if there is unsafe content in the user message in \
the conversation below according to our safety policy with the categories listed.

<BEGIN UNSAFE CONTENT CATEGORIES>
S1: Violence. S2: Sexual. S3: Criminal Planning/Confessions. S4: Guns and Illegal Weapons.
S5: Controlled/Regulated Substances. S6: Suicide and Self Harm. S7: Sexual (minor).
S8: Hate/Identity Hate. S9: PII/Privacy. S10: Harassment. S11: Threat. S12: Profanity.
S13: Needs Caution. S14: Other. S15: Manipulation. S16: Fraud/Deception. S17: Malware.
S18: High Risk Gov Decision Making. S19: Political/Misinformation/Conspiracy.
S20: Copyright/Trademark/Plagiarism. S21: Unauthorized Advice. S22: Illegal Activity.
S23: Immoral/Unethical.
<END UNSAFE CONTENT CATEGORIES>

<BEGIN CONVERSATION>
user: {message}
<END CONVERSATION>

Provide your safety assessment for the user message in the conversation above in the \
following JSON format:
{{"User Safety": "safe or unsafe", "Safety Categories": "comma-separated list, omit if safe"}}
Do not include anything other than the output JSON.
Output JSON: """


def _nemoguard_unsafe(text: str) -> tuple[bool, str] | None:
    """Ask NemoGuard whether `text` is unsafe content.

    Returns `(unsafe, categories)` or `None` when the guard is disabled/unavailable
    — callers must treat `None` as "no opinion" and fall back to the heuristics.
    """
    if not config.nemoguard_enabled():
        return None
    if not config.api_key("nvidia"):
        return None
    try:
        import json

        from src.clients import nvidia as nvidia_client

        resp = nvidia_client.complete(
            [{"role": "user", "content": _NEMOGUARD_POLICY.format(message=text)}],
            config.nemoguard_content_safety_model(),
            api_key=config.api_key("nvidia"),
            base_url=config.nvidia_base_url(),
            system=None,
            temperature=0.0,
            max_tokens=80,
        )
        raw = (resp.choices[0].message.content or "").strip()
        verdict = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        unsafe = str(verdict.get("User Safety", "safe")).strip().lower() == "unsafe"
        return unsafe, str(verdict.get("Safety Categories", "")).strip()
    except Exception:
        # Fail open: a guard outage degrades to heuristics-only, never to a crash.
        return None


def screen_input(text: str) -> InputVerdict:
    """Screen a user query for injection / jailbreak / extraction / unsafe content.

    Blocks if the deterministic signatures match OR (when enabled) NemoGuard rates
    the content unsafe. Empty input is allowed (the caller's own validation handles
    emptiness).
    """
    text = text or ""
    categories = _heuristic_hits(text)

    guard = _nemoguard_unsafe(text)
    if guard is not None and guard[0]:
        cats = [c.strip() for c in guard[1].split(",") if c.strip()] or ["unsafe_content"]
        categories = categories + [f"nemoguard:{c}" for c in cats]

    if categories:
        return InputVerdict(
            allowed=False,
            categories=tuple(categories),
            detail=f"input matched {', '.join(categories)}",
        )
    return InputVerdict(allowed=True)


def screen_observation(text: str) -> InputVerdict:
    """Heuristics-only screen for tool observations fed back into the agent loop.

    Applies the injection signatures to text a tool returned (retrieved filing
    excerpts, web-search snippets) so indirect injection cannot ride an
    Observation into the prompt. Deliberately never consults NemoGuard —
    observations are screened on every step, so this layer stays offline and
    deterministic.
    """
    hits = _heuristic_hits(text or "")
    if hits:
        return InputVerdict(
            allowed=False,
            categories=tuple(hits),
            detail=f"observation matched {', '.join(hits)}",
        )
    return InputVerdict(allowed=True)


def screen_context(chunks: list[dict]) -> tuple[list[dict], list[str]]:
    """Defend against indirect injection planted in retrieved chunks.

    Returns `(safe_chunks, flags)`. A chunk whose text carries an instruction-
    override / extraction / embedded-directive signature is dropped from the
    generation context (and reported), so a poisoned filing snippet cannot hijack
    the answer. Chunks are matched on the same text the model would see (content
    or, for parent-doc chunking, the parent block).
    """
    safe: list[dict] = []
    flags: list[str] = []
    for chunk in chunks:
        text = (chunk.get("metadata") or {}).get("parent_text") or chunk.get("content", "")
        hits = _heuristic_hits(text)
        if hits:
            flags.append(f"chunk_id={chunk.get('id')}: {', '.join(hits)}")
            continue
        safe.append(chunk)
    return safe, flags


# --------------------------------------------------------------------------- #
# PII redaction (deterministic)
# --------------------------------------------------------------------------- #
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # 13–16 digit card numbers, optionally space/dash grouped.
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")),
)


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum — separates real card numbers from ordinary digit runs."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, int]:
    """Replace emails / SSNs / card / phone numbers with `[REDACTED_<KIND>]`.

    Returns `(redacted_text, count)`. Order matters: SSN and card patterns run
    before the looser phone pattern so a 9-digit SSN is not mis-tagged as a phone.
    13–16 digit runs are redacted as cards only when they pass the Luhn check —
    filings are full of unformatted numeric totals that are not card numbers.
    """
    if not text:
        return text, 0
    count = 0

    def _sub(label: str, pattern: re.Pattern[str], s: str) -> str:
        nonlocal count

        def repl(m: re.Match[str]) -> str:
            nonlocal count
            if label == "CARD" and not _luhn_ok(re.sub(r"\D", "", m.group(0))):
                return m.group(0)
            count += 1
            return f"[REDACTED_{label}]"

        return pattern.sub(repl, s)

    out = text
    for label, pattern in _PII_PATTERNS:
        out = _sub(label, pattern, out)
    return out, count


# --------------------------------------------------------------------------- #
# Output validation (last line of defense)
# --------------------------------------------------------------------------- #
def validate_output(
    text: str,
    *,
    secrets: tuple[str, ...] = (),
    allowed_chunk_ids: set[int] | None = None,
    cited_ids: list[int] | None = None,
) -> OutputVerdict:
    """Validate a generated answer before returning it.

    Blocks when:
    - a configured secret/system-prompt substring leaks into the output, or
    - the answer cites a chunk_id outside the retrieved set (citation manipulation).

    `secrets` are caller-supplied confidential strings (e.g. an audit token or a
    system-prompt marker); matching is case-insensitive. Citation checks run only
    when `allowed_chunk_ids` is provided.
    """
    text = text or ""
    categories: list[str] = []

    lowered = text.lower()
    for secret in secrets:
        if secret and secret.lower() in lowered:
            categories.append("secret_leak")
            break

    if allowed_chunk_ids is not None and cited_ids:
        bad = [cid for cid in cited_ids if cid not in allowed_chunk_ids]
        if bad:
            categories.append("citation_manipulation")

    if categories:
        return OutputVerdict(
            allowed=False,
            categories=categories,
            detail=f"output matched {', '.join(categories)}",
        )
    return OutputVerdict(allowed=True)
