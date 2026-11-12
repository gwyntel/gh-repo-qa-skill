#!/usr/bin/env python3
"""Validate every skill in this repository before it ships.

Checks are deliberately cheap and structural — they catch the failures that
actually break an installed skill (unparseable frontmatter, a name that does
not match its directory, a dangling reference to a supporting file) rather
than grading prose.

Exit code 1 on any failure; every failure is reported, not just the first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - CI installs PyYAML
    sys.exit("PyYAML is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

REQUIRED_KEYS = ("name", "description", "author")
OPTIONAL_KEYS = ("version", "license", "metadata", "prerequisites")

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DESCRIPTION_LIMIT = 60
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEADING_RE = re.compile(r"^## (\d+)\. ")
FENCE_RE = re.compile(r"^```")
# Backticked paths that must exist next to SKILL.md.
LOCAL_REF_RE = re.compile(r"`((?:references|scripts|templates|assets|examples)/[A-Za-z0-9._/-]+)`")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body). Raises ValueError when unparseable."""
    if not text.startswith("---\n"):
        raise ValueError("file does not start with a '---' frontmatter block")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter block is not closed with '---'")
    raw = text[4:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data, text[end + 5 :]


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        return [f"{skill_dir.name}: missing SKILL.md"]

    raw_bytes = skill_md.read_bytes()
    if b"\r\n" in raw_bytes:
        errors.append(f"{skill_md}: CRLF line endings (use LF)")
    text = raw_bytes.decode("utf-8")
    if not text.endswith("\n"):
        errors.append(f"{skill_md}: file does not end with a newline")

    try:
        fm, body = split_frontmatter(text)
    except ValueError as exc:
        return errors + [f"{skill_md}: {exc}"]

    for key in REQUIRED_KEYS:
        value = fm.get(key)
        if not value or not isinstance(value, str):
            errors.append(f"{skill_md}: frontmatter missing required string '{key}'")

    name = fm.get("name")
    if isinstance(name, str):
        if not NAME_RE.match(name):
            errors.append(f"{skill_md}: name '{name}' is not lowercase-hyphenated")
        if name != skill_dir.name:
            errors.append(
                f"{skill_md}: name '{name}' does not match directory '{skill_dir.name}'"
            )

    description = fm.get("description")
    if isinstance(description, str) and len(description) > DESCRIPTION_LIMIT:
        errors.append(
            f"{skill_md}: description is {len(description)} chars "
            f"(limit {DESCRIPTION_LIMIT})"
        )

    version = fm.get("version")
    if version is not None:
        if not isinstance(version, str) or not SEMVER_RE.match(version):
            errors.append(f"{skill_md}: version '{version}' is not MAJOR.MINOR.PATCH")

    unknown = sorted(set(fm) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if unknown:
        errors.append(f"{skill_md}: unexpected frontmatter keys: {', '.join(unknown)}")

    # Fences: an odd count means an unterminated code block swallowed the rest.
    fences = sum(1 for line in body.splitlines() if FENCE_RE.match(line))
    if fences % 2:
        errors.append(f"{skill_md}: unbalanced code fences ({fences})")

    # Section numbering: contiguous from 0, no duplicates.
    numbers = [int(m.group(1)) for m in map(HEADING_RE.match, body.splitlines()) if m]
    if numbers and numbers != list(range(len(numbers))):
        errors.append(f"{skill_md}: section headings are not contiguous from 0: {numbers}")

    for ref in sorted(set(LOCAL_REF_RE.findall(body))):
        if not (skill_dir / ref).exists():
            errors.append(f"{skill_md}: references missing file '{ref}'")

    return errors


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print(f"error: no skills/ directory at {SKILLS_DIR}", file=sys.stderr)
        return 1

    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
    if not skill_dirs:
        print("error: skills/ contains no skill directories", file=sys.stderr)
        return 1

    failures: list[str] = []
    for skill_dir in skill_dirs:
        errors = validate_skill(skill_dir)
        status = "FAIL" if errors else "ok"
        print(f"{status:4}  {skill_dir.name}")
        failures.extend(errors)

    print(f"\n{len(skill_dirs)} skill(s) checked, {len(failures)} problem(s)")
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
