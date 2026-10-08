"""Fail on unnecessary code: dead code, tiny modules and comment-heavy files."""

import io
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

import vulture

ROOTS = ("src", "scripts", "evals", "tests")
EXEMPT_NAMES = {"__init__.py", "conftest.py"}
EXEMPT_PARTS = {"migrations"}
MIN_CODE_LINES = 8
MAX_COMMENT_RATIO = 0.05
PRAGMAS = ("noqa", "type:", "pragma", "fmt:", "nosec")
FRAMEWORK_DECORATORS = ["@router.*", "@app.*", "@*_app.*", "@*_validator"]
DEAD_CODE_TYPES = {"function", "method", "class", "import", "property", "unreachable_code"}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def count_lines(source: str) -> tuple[int, int]:
    """Return (code lines, comment tokens). Pragma comments do not count."""
    code_rows: set[int] = set()
    comments = 0
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments += not any(p in token.string for p in PRAGMAS)
        elif token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER):
            code_rows.update(range(token.start[0], token.end[0] + 1))
    return len(code_rows), comments


def check_file(path: Path) -> list[Finding]:
    if path.name in EXEMPT_NAMES or EXEMPT_PARTS.intersection(path.parts):
        return []
    code, comments = count_lines(path.read_text(encoding="utf-8"))
    findings = []
    if code < MIN_CODE_LINES:
        findings.append(Finding(path, 1, f"tiny module ({code} code lines); merge it"))
    if comments > 1 + code * MAX_COMMENT_RATIO:
        findings.append(Finding(path, 1, f"{comments} comments for {code} code lines; cut them"))
    return findings


def dead_code(paths: list[Path]) -> list[Finding]:
    scanner = vulture.Vulture(ignore_decorators=FRAMEWORK_DECORATORS)
    scanner.scavenge([str(p) for p in paths])
    return [
        Finding(Path(item.filename).relative_to(Path.cwd()), item.first_lineno, item.message)
        for item in scanner.get_unused_code(min_confidence=60)
        if item.typ in DEAD_CODE_TYPES
    ]


def main() -> int:
    files = sorted(f for root in ROOTS for f in Path(root).rglob("*.py"))
    findings = [f for path in files for f in check_file(path)] + dead_code(files)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
