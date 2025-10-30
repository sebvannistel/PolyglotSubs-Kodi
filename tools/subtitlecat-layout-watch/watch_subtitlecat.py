#!/usr/bin/env python3
"""Wrapper around the vendored subtitlecat layout watcher.

The script compiles a minimal set of diagnostics so CI can fail when subtitlecat
changes its DOM structure. Locally, developers can use the ``--update-test-fixtures``
flag to copy fresh HTML snapshots into the parser test suite.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JAR = (
    REPO_ROOT
    / "tools"
    / "subtitlecat-layout-watch"
    / "target"
    / "subtitlecat-layout-watch-jar-with-dependencies.jar"
)
DEFAULT_SNAPSHOT_DIR = (
    REPO_ROOT / "tools" / "subtitlecat-layout-watch" / "snapshots"
)
TEST_FIXTURE_DIR = REPO_ROOT / "tests" / "data" / "subtitlecat_watch"
REPRESENTATIVE_QUERIES = [
    "The Matrix 1999",
    "Game of Thrones S01E01",
    "Interstellar 2014",
]


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the subtitlecat layout watcher against known queries.",
    )
    parser.add_argument(
        "queries",
        nargs="*",
        help="Queries to run. Defaults to a baked-in selection when omitted.",
    )
    parser.add_argument(
        "--jar",
        default=str(DEFAULT_JAR),
        help="Path to the jar produced by mvn package.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=str(DEFAULT_SNAPSHOT_DIR),
        help="Where HTML snapshots should be written (default: %(default)s).",
    )
    parser.add_argument(
        "--update-test-fixtures",
        action="store_true",
        help="Copy the captured snapshots into tests/data/subtitlecat_watch/ for parser regression tests.",
    )
    return parser.parse_args(argv)


def ensure_paths(jar_path: Path, snapshot_dir: Path) -> None:
    if not jar_path.exists():
        raise SystemExit(
            f"Watcher jar not found at {jar_path}. Build it with 'mvn -f tools/subtitlecat-layout-watch/pom.xml package'."
        )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if not TEST_FIXTURE_DIR.exists():
        TEST_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)


def run_watcher(jar_path: Path, snapshot_dir: Path, queries: List[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["java", "-jar", str(jar_path), "--snapshot-dir", str(snapshot_dir), *queries]
    return subprocess.run(cmd, capture_output=True, text=True)


def load_payload(proc: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive branch
        snippet = proc.stdout.strip()
        raise SystemExit(
            "Watcher output was not valid JSON. Stdout snippet:\n"
            f"{snippet}\nStderr:\n{proc.stderr}"
        ) from exc


def summarise_failures(entries: List[dict]) -> Tuple[List[str], bool]:
    failures = []
    has_warning = False
    for entry in entries:
        reason = None
        if not entry.get("request_successful", False):
            reason = f"HTTP status {entry.get('http_status')}"
        elif entry.get("failure_reason"):
            reason = entry["failure_reason"]
        elif entry.get("row_count", 0) == 0:
            reason = "no rows matched"
        elif not entry.get("results"):
            reason = "no parsed results"

        if reason:
            message = [f"Query '{entry.get('keyword')}' failed: {reason}"]
            selectors = entry.get("attempted_selectors") or []
            if selectors:
                message.append(
                    "  Attempted selectors: " + ", ".join(selectors)
                )
            matched = entry.get("matched_selector")
            if matched:
                message.append(f"  Matched selector: {matched}")
            snapshot_path = entry.get("snapshot_path")
            if snapshot_path:
                message.append(f"  Snapshot: {snapshot_path}")
            snippet = entry.get("response_snippet") or ""
            if snippet:
                message.append(
                    "  Response snippet:\n"
                    + textwrap.indent(snippet[:800], "    ")
                )
            failures.append("\n".join(message))
        else:
            if entry.get("http_status") != 200:
                has_warning = True
    return failures, has_warning


def copy_snapshots(entries: List[dict]) -> List[Path]:
    copied = []
    for entry in entries:
        source = entry.get("snapshot_path")
        if not source:
            continue
        src_path = Path(source)
        if not src_path.exists():
            continue
        slug = SubtitleFindCliSlug.slugify(entry.get("keyword", "query"))
        dest = TEST_FIXTURE_DIR / f"{slug}.html"
        shutil.copy2(src_path, dest)
        copied.append(dest)
    return copied


class SubtitleFindCliSlug:
    @staticmethod
    def slugify(keyword: str) -> str:
        lowered = keyword.lower()
        cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return cleaned or "query"


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    queries = args.queries or REPRESENTATIVE_QUERIES
    jar_path = Path(args.jar)
    snapshot_dir = Path(args.snapshot_dir)

    ensure_paths(jar_path, snapshot_dir)

    proc = run_watcher(jar_path, snapshot_dir, queries)
    if proc.returncode not in (0,):
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode or 1

    payload = load_payload(proc)
    entries = payload.get("queries", [])
    failures, has_warning = summarise_failures(entries)

    if args.update_test_fixtures:
        copied = copy_snapshots(entries)
        if copied:
            print("Copied snapshots to parser fixtures:")
            for dest in copied:
                print(f"  - {dest}")
        else:
            print("No snapshots copied (missing --snapshot-dir output or watcher failed early).")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    if has_warning:
        print("Watcher completed but observed non-200 HTTP responses.", file=sys.stderr)
        return 2

    print("Subtitlecat layout watch passed for queries: " + ", ".join(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
