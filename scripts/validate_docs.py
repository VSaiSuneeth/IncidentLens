"""Validate repository Markdown links and Mermaid fence structure."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
WINDOWS_PATH = re.compile(r"(?:^|\s)[A-Za-z]:[\\/]", re.MULTILINE)


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    if WINDOWS_PATH.search(text):
        errors.append(f"{path.relative_to(ROOT)}: contains a Windows absolute path")

    fence_count = text.count("```mermaid")
    if fence_count != text.count("```mermaid\n"):
        errors.append(f"{path.relative_to(ROOT)}: malformed Mermaid fence")
    if fence_count:
        parts = text.split("```mermaid\n")[1:]
        for part in parts:
            diagram, separator, _rest = part.partition("```")
            if not separator or not diagram.lstrip().startswith(("flowchart", "graph")):
                errors.append(f"{path.relative_to(ROOT)}: Mermaid block is incomplete or lacks a graph declaration")

    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(1).strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        file_part = unquote(target.split("#", 1)[0])
        if not file_part:
            continue
        resolved = (path.parent / file_part).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link leaves the repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing relative link target: {target}")

    return errors


def main() -> int:
    errors: list[str] = []
    for path in sorted([ROOT / "README.md", *ROOT.joinpath("docs").rglob("*.md")]):
        if path.exists():
            errors.extend(validate_file(path))

    if errors:
        print("Documentation validation failed:", *errors, sep="\n")
        return 1
    print("Validated Markdown links and Mermaid fence structure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
