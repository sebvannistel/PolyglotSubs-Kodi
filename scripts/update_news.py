#!/usr/bin/env python3
"""Synchronize the addon.xml <news> section with the generated changelog."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
ADDON_XML = ROOT / "addon.xml"
CHANGELOG = ROOT / "CHANGELOG.md"


def _current_version() -> str:
    tree = ElementTree.parse(ADDON_XML)
    addon = tree.getroot()
    return addon.attrib["version"]


def _changelog_section(version: str) -> str:
    changelog_text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"^##\s+{re.escape(version)}\b.*?(?=^##\s|\Z)", re.M | re.S)
    match = pattern.search(changelog_text)
    if not match:
        raise SystemExit(f"Unable to find changelog section for {version!r}.")
    return match.group(0)


def _build_news_entry(version: str, section: str) -> str:
    lines: list[str] = [f"[v{version}]:"]
    current_header: str | None = None

    for raw_line in section.splitlines()[1:]:  # Skip the section heading itself
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            current_header = line[4:].strip()
            continue
        if line.startswith("- "):
            entry = line[2:].strip()
        else:
            entry = line
        if current_header:
            lines.append(f"  * [{current_header}] {entry}")
        else:
            lines.append(f"  * {entry}")

    if len(lines) == 1:
        lines.append("  * No notable changes recorded.")

    return "\n".join(lines)


def _rewrite_news(entry: str) -> None:
    addon_text = ADDON_XML.read_text(encoding="utf-8")
    pattern = re.compile(r"(\s*<news>\s*)(.*?)(\s*</news>)", re.S)
    match = pattern.search(addon_text)
    if not match:
        raise SystemExit("Unable to locate <news> section in addon.xml.")

    existing_block = match.group(2).strip()
    entries: list[str] = []
    if existing_block:
        for block in re.split(r"\n\s*\n", existing_block):
            stripped = block.strip()
            if stripped and not stripped.startswith(entry.splitlines()[0]):
                entries.append(stripped)
    new_entries = [entry] + entries
    new_block = "\n\n".join(new_entries)

    replacement = f"{match.group(1)}{new_block}\n{match.group(3)}"
    updated = addon_text[: match.start()] + replacement + addon_text[match.end() :]
    ADDON_XML.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also emit the generated news entry to stdout.",
    )
    args = parser.parse_args()

    version = _current_version()
    section = _changelog_section(version)
    entry = _build_news_entry(version, section)
    _rewrite_news(entry)

    if args.stdout:
        print(entry)


if __name__ == "__main__":
    main()
