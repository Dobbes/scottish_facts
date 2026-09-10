"""Read-only credential audit. Reports locations and rule names, never values.

Scans reachable Git history and tracked/unignored working files. If a local .env
exists, also searches for its sensitive values and common encoded variants.
This is a focused supplement to GitHub secret scanning, not a completeness proof.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, quote_plus, unquote, urlsplit

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "openai-key": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "aws-access-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential-url": re.compile(rb"(?:postgres(?:ql)?|https?)://[^\s/:]+:[^\s/@]+@[^\s]+"),
    "twilio-identifier": re.compile(rb"\b(?:AC|SK)[0-9a-fA-F]{32}\b"),
    "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}"),
    "phone-number": re.compile(rb"(?<![\w])\+\d{11,15}(?!\d)"),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def local_values() -> set[bytes]:
    values: set[bytes] = set()
    for name, value in dotenv_values(ROOT / ".env").items():
        if not value or not any(part in name for part in ("KEY", "SECRET", "TOKEN", "PASSWORD", "NUMBER", "SID", "DB_URL")):
            continue
        candidates = {value}
        if "DB_URL" in name:
            password = urlsplit(value).password
            if password:
                candidates.add(unquote(password))
        for candidate in candidates:
            if len(candidate) >= 8:
                values.update(v.encode() for v in (candidate, quote(candidate, safe=""), quote_plus(candidate)))
                values.add(base64.b64encode(candidate.encode()))
    return values


def scan(data: bytes, location: str, known: set[bytes]) -> int:
    findings = set()
    for rule, pattern in RULES.items():
        for match in pattern.finditer(data):
            findings.add((data.count(b"\n", 0, match.start()) + 1, rule))
    for value in known:
        start = data.find(value)
        if start >= 0:
            findings.add((data.count(b"\n", 0, start) + 1, "local-secret-value"))
    for line, rule in sorted(findings):
        print(f"{location}:{line}: {rule} [value withheld]")
    return len(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also scan every reachable Git blob")
    args = parser.parse_args()
    known = local_values()
    findings = 0
    files = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
    count = 0
    for raw in sorted(set(files) - {b""}):
        path = ROOT / raw.decode("utf-8")
        if path.is_file():
            findings += scan(path.read_bytes(), f"worktree:{raw.decode('utf-8')}", known)
            count += 1
    blobs = 0
    if args.history:
        objects = git("rev-list", "--objects", "--all").splitlines()
        for entry in objects:
            oid, _, name = entry.partition(b" ")
            if git("cat-file", "-t", oid.decode()).strip() != b"blob":
                continue
            data = git("cat-file", "blob", oid.decode())
            findings += scan(data, f"history:{oid.decode()[:12]}:{name.decode('utf-8')}", known)
            blobs += 1
    print(f"Scanned {count} working files and {blobs} historical blobs; {findings} findings.")
    print("Findings may include synthetic test fixtures; review locations without publishing values.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
