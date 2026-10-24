"""Secrets found in what a repository holds are hidden before an agent sees them (docs/reference/safety.md).

A value that looks like a secret — a provider's key or token, a private key, a password in a URL, a value given to a
`password` / `secret` / `token` / `api_key` setting, a password written in prose — is replaced by `[hidden: <what>]`
in every answer and every error. A private key's block is hidden whole where the whole file is at hand. The rules lean
towards hiding: a value hidden by mistake costs a reader a look at the host; a key shown costs a rotation.
"""

from __future__ import annotations

import re

MARK = "[hidden: {}]"
PREFIX = "[hidden: "

# A provider's own format: unmistakable, hidden wherever it appears.
TOKENS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern))
    for name, pattern in [
        ("AWS access key", r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
        ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
        ("GitHub token", r"\bgithub_pat_[A-Za-z0-9_]{60,255}\b"),
        ("GitLab token", r"\bglpat-[A-Za-z0-9_-]{20,}"),
        ("Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
        ("Slack webhook", r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
        ("Stripe key", r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
        ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
        ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
        ("OpenAI key", r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
        ("npm token", r"\bnpm_[A-Za-z0-9]{36}\b"),
        ("Telegram bot token", r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}"),
        ("JWT", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ]
]
# The password part of `scheme://user:password@host`.
URL_PASSWORD = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@'\"]+:([^\s/@'\"]+)@")
# A line of a private key's body (or of any base64 blob that long): 60–76 characters with upper and lower case and
# digits — a commit id or a hex digest has no upper case, a lock file's integrity hash is longer.
KEY_BODY = re.compile(r"(?<![A-Za-z0-9+/=])(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*\d)"
                      r"[A-Za-z0-9+/]{60,76}={0,2}(?![A-Za-z0-9+/=])")  # fmt: skip
# `password = "…"`, `API_KEY=…`, `client_secret: …`, `"token": "…"`.
SETTING = re.compile(
    r"(?i)(?<![a-z0-9])[a-z0-9_.-]*(?:password|passwd|passphrase|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|private[_-]?key)[a-z0-9_.-]*[\"']?\s*(?:=>|:=|[:=])\s*(?P<quote>[\"'`]?)"
    r"(?P<value>[^\s\"'`#,;]{6,})"
)
# "the password is hunter22", "пароль: …"
PROSE = re.compile(r"(?i)\b(?:password|passphrase|пароль)\s+(?:is|was|=|:|—|-)\s+[\"'`]?(?P<value>[^\s\"'`]{6,})")
PLACEHOLDERS = {
    "none", "null", "nil", "true", "false", "changeme", "change-me", "change_me", "example", "password", "secret",
    "token", "string", "bearer", "basic", "required", "optional", "redacted", "placeholder", "undefined", "default",
}  # fmt: skip
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
NOT_A_VALUE = set("()[]{}<>$%")

BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")


def _is_value(value: str, quoted: bool) -> bool:
    """Whether what a setting is given looks like a secret value, not a name, a reference or a placeholder."""
    bare = value.strip(".")
    if bare.lower() in PLACEHOLDERS or set(bare) <= set("*xX.-_") or NOT_A_VALUE & set(bare):
        return False
    if re.fullmatch(r"[\d.:+-]+", bare):  # a number, a date, a version
        return False
    if quoted:
        return True
    # Unquoted (`API_KEY=…`, `password: …`): a name or a dotted path (`settings.TOKEN`) is a reference, unless it is
    # long or mixes letters and digits as a password does.
    if IDENTIFIER.fullmatch(bare):
        return len(bare) >= 16 or (any(ch.isdigit() for ch in bare) and any(ch.isalpha() for ch in bare))
    return True


def hide(line: str) -> str:
    """A line with every value that looks like a secret replaced by `[hidden: …]`."""
    for name, rule in TOKENS:
        line = rule.sub(MARK.format(name), line)
    line = URL_PASSWORD.sub(lambda m: m[0].replace(m[1], MARK.format("password"), 1), line)
    line = KEY_BODY.sub(MARK.format("key material"), line)

    def setting(match: re.Match[str]) -> str:
        if not _is_value(match["value"], bool(match["quote"])):
            return match[0]
        return match[0][: match.start("value") - match.start()] + MARK.format("secret value")

    line = SETTING.sub(setting, line)
    return PROSE.sub(
        lambda m: (
            m[0][: m.start("value") - m.start()] + MARK.format("password") if _is_value(m["value"], True) else m[0]
        ),
        line,
    )


def key_lines(lines: list[str]) -> set[int]:
    """The indexes of the lines inside a private key's block (its markers kept, its body hidden whole) — to the end
    when the block never ends."""
    inside, found = False, set()
    for i, line in enumerate(lines):
        if not inside and BEGIN.search(line):
            inside = True
            continue
        if inside and END.search(line):
            inside = False
            continue
        if inside:
            found.add(i)
    return found


def hide_lines(lines: list[str]) -> list[str]:
    """A whole file's lines with its private keys' bodies and every value that looks like a secret hidden."""
    blocks = key_lines(lines)
    return [MARK.format("private key") if i in blocks else hide(line) for i, line in enumerate(lines)]


def hidden_count(text: str) -> int:
    return text.count(PREFIX)
