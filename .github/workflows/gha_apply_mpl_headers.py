#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Apply and verify MPL 2.0 notices across tracked repository files.

The tool is deliberately conservative: it only edits formats where a comment
can be embedded without changing runtime semantics. Files that are binary,
symlinks, pure JSON, cryptographic material or otherwise ambiguous are recorded
in ``docs/license-header-exceptions.md`` for explicit manual review instead of
being modified speculatively.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never write __pycache__ into the worktree

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "license-header-exceptions.md"
NOTICE_LINES = (
    "This Source Code Form is subject to the terms of the Mozilla Public",
    "License, v. 2.0. If a copy of the MPL was not distributed with this",
    "file, You can obtain one at https://mozilla.org/MPL/2.0/.",
)
NOTICE_MARKER = NOTICE_LINES[0]

HASH_SUFFIXES = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    ".feature",
    ".tf",
    ".hcl",
}
HTML_SUFFIXES = {".md", ".markdown", ".html", ".htm"}
C_BLOCK_SUFFIXES = {".css", ".c", ".h", ".cc", ".cpp", ".hpp", ".java"}
SLASH_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".jsonc"}
DASH_SUFFIXES = {".sql", ".lua"}
XML_SUFFIXES = {".xml", ".svg"}
JINJA_SUFFIXES = {".j2", ".jinja", ".jinja2"}
KNOWN_HASH_NAMES = {
    "Dockerfile",
    "Caddyfile",
    "Makefile",
    "Procfile",
    "requirements.txt",
    "constraints.txt",
    "Pipfile",
    "tox.ini",
    "pytest.ini",
    ".flake8",
    ".coveragerc",
    ".gitignore",
    ".dockerignore",
    ".gitattributes",
    ".editorconfig",
}
PURE_JSON_SUFFIXES = {".json"}
CRYPTO_SUFFIXES = {".pem", ".crt", ".cer", ".key", ".p12", ".pfx", ".der"}
BINARY_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".tar",
    ".7z",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".sqlite",
    ".db",
}


@dataclass(frozen=True)
class Decision:
    """Whether a tracked text format supports a safe header, or why it does not."""

    style: str | None
    reason: str | None = None


def git_files() -> list[Path]:
    """List tracked paths, including worktree-missing files, without invoking a shell."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [ROOT / part.decode("utf-8") for part in result.stdout.split(b"\0") if part]


def rel(path: Path) -> str:
    """Render a repository-relative POSIX path for stable reports."""
    return path.relative_to(ROOT).as_posix()


def is_binary_bytes(data: bytes) -> bool:
    """Reject NUL-containing or non-UTF-8 content before attempting text edits."""
    if b"\0" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def classify(path: Path, text: str) -> Decision:
    """Select a comment syntax, conservatively excluding semantic or opaque formats."""
    name = path.name
    suffix = path.suffix.lower()
    relative = rel(path)

    if relative == "LICENSE":
        return Decision(None, "canonical MPL-2.0 license text; header would alter the license document")
    if suffix in BINARY_SUFFIXES:
        return Decision(None, f"binary format ({suffix or 'no suffix'})")
    if suffix in CRYPTO_SUFFIXES:
        return Decision(None, f"cryptographic/certificate material ({suffix}); prefix text may break parsers")
    if suffix in PURE_JSON_SUFFIXES:
        return Decision(None, "pure JSON has no comment syntax and an SPDX property would change document semantics")
    if name.startswith(".env"):
        return Decision("hash")
    if suffix in HASH_SUFFIXES or name in KNOWN_HASH_NAMES:
        return Decision("hash")
    if suffix in HTML_SUFFIXES:
        return Decision("html")
    if suffix in C_BLOCK_SUFFIXES:
        return Decision("cblock")
    if suffix in SLASH_SUFFIXES:
        return Decision("slash")
    if suffix in DASH_SUFFIXES:
        return Decision("dash")
    if suffix in XML_SUFFIXES:
        return Decision("xml")
    if suffix in JINJA_SUFFIXES:
        return Decision("jinja")
    if text.startswith("#!"):
        return Decision("hash")
    if suffix in {".txt", ".csv", ".tsv", ".lock"}:
        return Decision(None, f"no safe repository-wide invisible comment convention for {suffix}")
    if not suffix:
        return Decision(None, "extensionless non-shebang text file with unknown grammar")
    return Decision(None, f"unclassified text format ({suffix})")


def hash_header() -> str:
    """Render the MPL notice using hash-line comments."""
    return "\n".join(f"# {line}" for line in NOTICE_LINES) + "\n\n"


def html_header() -> str:
    """Render the MPL notice as an HTML-compatible comment."""
    return "<!--\n" + "\n".join(NOTICE_LINES) + "\n-->\n\n"


def cblock_header() -> str:
    """Render the MPL notice as a C-style block comment."""
    return "/*\n * " + "\n * ".join(NOTICE_LINES) + "\n */\n\n"


def slash_header() -> str:
    """Render the MPL notice using slash-line comments."""
    return "\n".join(f"// {line}" for line in NOTICE_LINES) + "\n\n"


def dash_header() -> str:
    """Render the MPL notice using SQL-style line comments."""
    return "\n".join(f"-- {line}" for line in NOTICE_LINES) + "\n\n"


def jinja_header() -> str:
    """Render the MPL notice using Jinja comment delimiters."""
    return "{#\n" + "\n".join(NOTICE_LINES) + "\n#}\n\n"


def insert_after_prefix(text: str, header: str, style: str) -> str:
    """Keep shebangs, encoding declarations, and XML prologs before a new notice."""
    if style == "hash":
        lines = text.splitlines(keepends=True)
        index = 0
        if lines and lines[0].startswith("#!"):
            index = 1
        coding = re.compile(r"^[ \t]*#.*coding[:=][ \t]*[-\w.]+")
        if index < len(lines) and coding.match(lines[index]):
            index += 1
        return "".join(lines[:index]) + header + "".join(lines[index:])
    if style == "xml":
        if text.startswith("<?xml"):
            end = text.find("?>")
            if end != -1:
                end += 2
                tail = text[end:]
                prefix = text[:end]
                if tail.startswith("\r\n"):
                    return prefix + "\r\n" + html_header() + tail[2:]
                if tail.startswith("\n"):
                    return prefix + "\n" + html_header() + tail[1:]
                return prefix + "\n" + html_header() + tail
        return html_header() + text
    return header + text


def apply_header(path: Path, text: str, style: str) -> str:
    """Insert one notice for a classified file, leaving existing notices untouched."""
    del path
    if NOTICE_MARKER in text[:4096]:
        return text
    if style == "hash":
        return insert_after_prefix(text, hash_header(), style)
    if style == "html":
        return html_header() + text
    if style == "cblock":
        return cblock_header() + text
    if style == "slash":
        return slash_header() + text
    if style == "dash":
        return dash_header() + text
    if style == "xml":
        return insert_after_prefix(text, html_header(), style)
    if style == "jinja":
        return jinja_header() + text
    raise ValueError(f"unsupported style: {style}")


def render_report(exceptions: list[tuple[str, str]]) -> str:
    """Build the deterministic Markdown report of files that need manual review."""
    rendered_rows: list[str] = []
    for path, reason in exceptions:
        safe_reason = reason.replace("|", "\\|")
        rendered_rows.append(f"| `{path}` | {safe_reason} |")
    rows = "\n".join(rendered_rows)
    if not rows:
        rows = "| _None_ | All tracked files were safely headered. |"
    return (
        html_header()
        + "# MPL 2.0 header exceptions\n\n"
        + "This file is generated by `.github/workflows/gha_apply_mpl_headers.py`. It records tracked files where adding the full MPL notice, or a safe embedded SPDX line, cannot be done without changing format semantics, replacing a symlink, modifying cryptographic material, or altering binary content. These files require explicit manual review rather than speculative mutation.\n\n"
        + "| File | Reason |\n| --- | --- |\n"
        + rows
        + "\n"
    )


def scan(check_only: bool) -> int:
    """Audit tracked files and either check or safely update notices and exceptions."""
    missing: list[str] = []
    exceptions: list[tuple[str, str]] = []
    changed: list[str] = []

    if REPORT.is_symlink():
        print(f"Refusing symlinked exception report: {rel(REPORT)}")
        return 1

    for path in git_files():
        relative = rel(path)
        if relative == REPORT.relative_to(ROOT).as_posix():
            continue
        if not path.exists() and not path.is_symlink():
            missing.append(relative)
            continue
        if path.is_symlink():
            exceptions.append(
                (relative, "symbolic link; modifying content would replace or alter the link target contract")
            )
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            exceptions.append((relative, f"cannot read safely: {exc}"))
            continue
        if is_binary_bytes(data):
            exceptions.append((relative, "binary or non-UTF-8 content"))
            continue

        text = data.decode("utf-8")
        decision = classify(path, text)
        if decision.style is None:
            exceptions.append((relative, decision.reason or "unsupported format"))
            continue

        if NOTICE_MARKER in text[:4096]:
            continue

        if check_only:
            missing.append(relative)
            continue

        updated = apply_header(path, text, decision.style)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
            changed.append(relative)

    if missing and not check_only:
        print("Tracked files missing from the worktree:")
        for item in sorted(missing):
            print(f"  - {item}")
        return 1

    report = render_report(sorted(exceptions))
    if check_only:
        try:
            report_matches = REPORT.is_file() and REPORT.read_text(encoding="utf-8") == report
        except (OSError, UnicodeError):
            report_matches = False
        if not report_matches:
            missing.append(rel(REPORT))
        if missing:
            print("Files missing MPL headers or with a stale exception report:")
            for item in sorted(missing):
                print(f"  - {item}")
            return 1
        print(f"MPL header check passed; {len(exceptions)} explicit exceptions remain for manual review.")
        return 0

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8", newline="")
    print(f"Added/updated MPL headers in {len(changed)} tracked files.")
    print(f"Recorded {len(exceptions)} exceptions in {rel(REPORT)}.")
    return 0


def main() -> int:
    """Parse the check-only switch and return the audit status."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify instead of modifying files")
    args = parser.parse_args()
    return scan(args.check)


if __name__ == "__main__":
    sys.exit(main())
