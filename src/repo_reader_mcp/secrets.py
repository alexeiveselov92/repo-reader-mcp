"""Secrets found in what a repository holds are hidden before an agent sees them (docs/reference/safety.md).

A value that looks like a secret — a provider's key or token, key material, a password in a URL, a value given to a
setting named for a secret, a password written in prose — is replaced by `[hidden: <what>]` in every answer and every
error. A private key's block is hidden whole where the whole file is at hand. The rules lean towards hiding: a value
hidden by mistake costs a reader a look at the host; a key shown costs a rotation.

`spans` finds where the values are in the line as written, so a search can tell whether what it matched lies outside
them — never by matching again on the hidden text.
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
        ("private key", r"LS0tLS1CRUdJTi[A-Za-z0-9+/=]*"),  # `-----BEGIN` in base64: a key written on one line
    ]
]
# The password of `scheme://user:password@host` — the user may be empty (`redis://:password@…`), the password may hold
# an `@` (it runs to the last one before the host).
URL_PASSWORD = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@'\"]*:(?P<value>[^\s/'\"]+)@[^\s/@'\"]+")
# Key material, or any base64 blob that long: 60 characters or more, mixing upper and lower case and digits (a commit
# id or a hex digest has no upper case), not a subresource integrity hash (`sha512-…`), not a path (few `/`).
BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{60,}={0,2}(?![A-Za-z0-9+/=])")
INTEGRITY = re.compile(r"sha\d{3}-$")
# A setting whose name ends with a secret's word — `password = "…"`, `API_KEY=…`, `"client_secret": "…"` — and the
# value given: quoted (to its closing quote) or bare (to a space).
SETTING = re.compile(
    r"(?i)(?<![a-z0-9])[a-z0-9_.-]*?(?:password|passwd|passphrase|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|private[_-]?key|secret[_-]?key|key[_-]?data|tls\.key)s?[\"']?\s*(?:=>|:=|[:=])\s*"
    r"(?:(?P<quote>[\"'`])(?P<quoted>[^\"'`\n]{6,})(?P=quote)|(?P<value>[^\s\"'`#,;]{6,}))"
)
# "the password is Qwerty!2026", "пароль: …" — a value with something other than letters in it.
PROSE = re.compile(r"(?i)\b(?:password|passphrase|пароль)\s+(?:is|was|=|:|—|-)\s+[\"'`]?(?P<value>[^\s\"'`]{6,})")
PLACEHOLDERS = {
    "none", "null", "nil", "true", "false", "changeme", "change-me", "change_me", "example", "password", "secret",
    "token", "string", "bearer", "basic", "required", "optional", "redacted", "placeholder", "undefined", "default",
}  # fmt: skip
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
NOT_A_VALUE = set("()[]{}<>$%")

# A private key's block: its markers on lines of their own (a marker inside code, `PEM = '-----BEGIN …'`, is not one);
# its body base64, empty lines, or an encrypted key's headers.
BEGIN = re.compile(r"^\s*[\"']?-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----[\"',;]?\s*$")
END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
BODY = re.compile(r"^\s*(?:[A-Za-z0-9+/=]*|[A-Za-z-]+: .*)\s*$")


def _is_value(value: str, quoted: bool) -> bool:
    """Whether what a setting is given looks like a secret value, not prose, a name, a reference or a placeholder."""
    bare = value.strip(".")
    if " " in bare or "://" in bare or bare.startswith("/"):
        return False  # a sentence, an address, a path
    if bare.lower() in PLACEHOLDERS or set(bare) <= set("*xX.-_") or NOT_A_VALUE & set(bare):
        return False
    if re.fullmatch(r"[\d.:+-]+", bare):  # a number, a date, a version
        return False
    if quoted:
        return True
    # Bare (`API_KEY=…`, `password: …`): a name or a dotted path (`settings.TOKEN`) is a reference, unless it is long
    # or mixes letters and digits as a password does.
    if IDENTIFIER.fullmatch(bare):
        return len(bare) >= 16 or (any(ch.isdigit() for ch in bare) and any(ch.isalpha() for ch in bare))
    return True


def _key_material(match: re.Match[str], line: str) -> bool:
    run = match[0].rstrip("=")
    if not (any(c.isupper() for c in run) and any(c.islower() for c in run) and any(c.isdigit() for c in run)):
        return False
    if INTEGRITY.search(line[max(0, match.start() - 8) : match.start()]):
        return False
    return run.count("/") <= max(3, len(run) // 20)


def spans(line: str) -> list[tuple[int, int, str]]:
    """Where the values that look like secrets are in a line as written: (start, end, what), in order, not
    overlapping."""
    found: list[tuple[int, int, str]] = []
    for name, rule in TOKENS:
        found += [(m.start(), m.end(), name) for m in rule.finditer(line)]
    found += [(m.start("value"), m.end("value"), "password") for m in URL_PASSWORD.finditer(line)]
    found += [(m.start(), m.end(), "key material") for m in BASE64.finditer(line) if _key_material(m, line)]
    for m in SETTING.finditer(line):
        group = "quoted" if m["quoted"] is not None else "value"
        if _is_value(m[group], group == "quoted"):
            found.append((m.start(group), m.end(group), "secret value"))
    for m in PROSE.finditer(line):
        if _is_value(m["value"], True) and not m["value"].isalpha():
            found.append((m.start("value"), m.end("value"), "password"))
    merged: list[tuple[int, int, str]] = []
    for start, end, name in sorted(found):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]), merged[-1][2])
        else:
            merged.append((start, end, name))
    return merged


def hide(line: str) -> str:
    """A line with every value that looks like a secret replaced by `[hidden: …]`."""
    out, at = [], 0
    for start, end, name in spans(line):
        out += [line[at:start], MARK.format(name)]
        at = end
    return "".join(out) + line[at:]


def outside(line: str, needle: str, *, ignore_case: bool = False) -> bool:
    """Whether some occurrence of a text in a line lies wholly outside the values hidden in it."""
    hidden = spans(line)
    hay, find = (line.lower(), needle.lower()) if ignore_case else (line, needle)
    at = hay.find(find)
    while at != -1:
        if not any(at < end and start < at + len(find) for start, end, _ in hidden):
            return True
        at = hay.find(find, at + 1)
    return False


def key_lines(lines: list[str]) -> set[int]:
    """The indexes of the lines inside private keys' blocks — the body, not the markers. A block that never ends
    stops at the first line that is not a key's."""
    inside, found = False, set()
    for i, line in enumerate(lines):
        if not inside:
            inside = bool(BEGIN.match(line))
        elif END.search(line) or not BODY.match(line):
            inside = False
        else:
            found.add(i)
    return found


def hide_lines(lines: list[str]) -> list[str]:
    """A whole file's lines with its private keys' bodies and every value that looks like a secret hidden."""
    blocks = key_lines(lines)
    return [MARK.format("private key") if i in blocks else hide(line) for i, line in enumerate(lines)]


def hide_patch(lines: list[str]) -> list[str]:
    """A diff's lines with secrets hidden in what each line holds (its `+`, `-` or ` ` kept), and private keys' bodies
    hidden whole — a hunk that starts inside a block is hidden back to its start when the block's end comes."""
    out: list[str] = []
    inside, hunk = False, 0
    for line in lines:
        if line.startswith(("diff --git", "@@")):
            inside = inside and not line.startswith("diff --git")
            hunk = len(out) + 1
            out.append(line)
            continue
        if line[:1] not in ("+", "-", " ") or line.startswith(("+++ ", "--- ")):
            out.append(line)
            continue
        sign, body = line[0], line[1:]
        if inside and (END.search(body) or not BODY.match(body)):
            inside = False
        elif inside:
            out.append(sign + MARK.format("private key"))
            continue
        elif END.search(body):  # the block began before this hunk: hide its lines back to the hunk's start
            for i in range(hunk, len(out)):
                if out[i][:1] in ("+", "-", " ") and BODY.match(out[i][1:]) and out[i][1:].strip():
                    out[i] = out[i][0] + MARK.format("private key")
        elif BEGIN.match(body):
            inside = True
        out.append(sign + hide(body))
    return out


def hidden_count(text: str) -> int:
    return text.count(PREFIX)
