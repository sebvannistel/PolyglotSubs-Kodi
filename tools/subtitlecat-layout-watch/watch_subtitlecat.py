#!/usr/bin/env python3
"""Run the vendored subtitlecat layout watcher and surface actionable failures."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

WATCH_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WATCH_ROOT / "subtitle-find"
REPO_ROOT = WATCH_ROOT.parents[1]
DEFAULT_CONFIG = WATCH_ROOT / "watch_targets.json"
DEFAULT_JAR = (
    PROJECT_ROOT / "target" / "subtitlecat-layout-watch-jar-with-dependencies.jar"
)
WATCH_SNAPSHOT_DIR = WATCH_ROOT / "snapshots"
TEST_SNAPSHOT_SEARCH_DIR = (
    WATCH_ROOT.parents[2]
    / "tests"
    / "services"
    / "subtitlecat"
    / "watch_snapshots"
    / "search"
)
TEST_SNAPSHOT_DETAIL_DIR = (
    WATCH_ROOT.parents[2]
    / "tests"
    / "services"
    / "subtitlecat"
    / "watch_snapshots"
    / "detail"
)


class WatchError(Exception):
    """Raised when the layout watcher detects a failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to the JSON configuration describing watch targets.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Assume the watcher jar is already built.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh Maven build before running the watcher.",
    )
    parser.add_argument(
        "--java-bin",
        default="java",
        help="Java executable to use when launching the watcher (default: java in PATH).",
    )
    return parser.parse_args()


def ensure_directories() -> None:
    WATCH_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    TEST_SNAPSHOT_SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    TEST_SNAPSHOT_DETAIL_DIR.mkdir(parents=True, exist_ok=True)


def ensure_built(skip_build: bool, rebuild: bool) -> Path:
    if skip_build and rebuild:
        raise ValueError("--skip-build and --rebuild are mutually exclusive")

    if rebuild or (not skip_build and not DEFAULT_JAR.exists()):
        cmd = [
            "mvn",
            "-q",
            "-DskipTests",
            "package",
        ]
        completed = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            check=False,
        )
        if completed.returncode != 0:
            raise WatchError(
                "Maven build failed. Run with --skip-build once the project is packaged successfully."
            )
    if not DEFAULT_JAR.exists():
        raise WatchError(
            "Watcher jar missing. Run without --skip-build or pass --rebuild to force a fresh build."
        )
    return DEFAULT_JAR


def load_config(config_path: Path) -> List[Dict[str, object]]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WatchError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise WatchError(
            f"Invalid JSON in configuration file {config_path}: {exc}"
        ) from exc

    if not isinstance(raw, list):
        raise WatchError(
            "Configuration file must contain a JSON list of target definitions."
        )
    return raw


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    slug = slug.strip("-")
    return slug or "snapshot"


def decode_snapshot(data: str | None) -> str | None:
    if not data:
        return None
    try:
        return base64.b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return None


def write_snapshot(html: str, target_label: str, kind: str) -> Tuple[Path, Path]:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    slug = slugify(target_label)
    filename = f"{slug}-{kind}-{timestamp}.html"

    watch_path = WATCH_SNAPSHOT_DIR / filename
    watch_path.write_text(html, encoding="utf-8")

    if kind == "search":
        test_dir = TEST_SNAPSHOT_SEARCH_DIR
    else:
        test_dir = TEST_SNAPSHOT_DETAIL_DIR

    test_path = test_dir / filename
    test_path.write_text(html, encoding="utf-8")
    return watch_path, test_path


def run_cli(
    jar_path: Path, java_bin: str, query: str, check_download: bool, max_results: int
) -> Dict[str, object]:
    cmd = [java_bin, "-jar", str(jar_path), "--query", query]
    if check_download:
        cmd.append("--check-download")
    if max_results:
        cmd.extend(["--max-results", str(max_results)])

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WatchError(
            f"Watcher CLI failed for query '{query}'.\nSTDOUT: {completed.stdout}\nSTDERR: {completed.stderr}"
        )
    stdout = completed.stdout.strip()
    if not stdout:
        raise WatchError(f"Watcher CLI returned no output for query '{query}'.")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WatchError(
            f"Watcher CLI produced invalid JSON for query '{query}': {exc}\nRaw output: {stdout}"
        ) from exc


def evaluate_target(
    target: Dict[str, object], result: Dict[str, object]
) -> Tuple[bool, List[str], List[Tuple[str, Path, Path]]]:
    issues: List[str] = []
    snapshots: List[Tuple[str, Path, Path]] = []

    label = str(target.get("label") or target.get("query"))
    expected_selector = target.get("expected_selector")
    expected_min_results = target.get("expected_min_results")
    expected_download_selector = target.get("expected_download_selector")
    expected_download_url_fragment = target.get("expected_download_url_fragment")

    search_status = result.get("status")
    result_count = result.get("result_count", 0)
    matched_selector = result.get("matched_selector")
    errors = result.get("errors", []) or []

    if search_status != "ok":
        issues.append(f"search status is '{search_status}'")
    if expected_selector and matched_selector != expected_selector:
        issues.append(
            f"matched selector '{matched_selector}' does not equal expected '{expected_selector}'"
        )
    if isinstance(expected_min_results, int) and result_count < expected_min_results:
        issues.append(
            f"expected at least {expected_min_results} results but received {result_count}"
        )
    if errors:
        issues.append(f"search errors reported: {', '.join(errors)}")

    search_html = decode_snapshot(result.get("search_html_base64"))
    if issues and search_html:
        watch_path, test_path = write_snapshot(search_html, label, "search")
        snapshots.append(("search", watch_path, test_path))

    download_expectations = target.get("check_download", True)
    download_info = (
        result.get("download") if isinstance(result.get("download"), dict) else None
    )

    if download_expectations and download_info:
        download_status = download_info.get("status")
        download_selector = download_info.get("matched_selector")
        download_errors = download_info.get("errors", []) or []
        download_url = download_info.get("download_url")

        if download_status != "ok":
            issues.append(f"download status is '{download_status}'")
        if (
            expected_download_selector
            and download_selector != expected_download_selector
        ):
            issues.append(
                f"download selector '{download_selector}' does not equal expected '{expected_download_selector}'"
            )
        if (
            expected_download_url_fragment
            and download_url
            and expected_download_url_fragment not in download_url
        ):
            issues.append(
                f"download URL '{download_url}' does not contain '{expected_download_url_fragment}'"
            )
        if download_errors:
            issues.append(f"download errors reported: {', '.join(download_errors)}")

        detail_html = decode_snapshot(download_info.get("detail_html_base64"))
        if detail_html and any("download" in issues_text for issues_text in issues):
            watch_path, test_path = write_snapshot(detail_html, label, "detail")
            snapshots.append(("detail", watch_path, test_path))
    elif download_expectations and not download_info:
        issues.append(
            "download checks were requested but no download metadata was returned"
        )
        if search_html:
            watch_path, test_path = write_snapshot(search_html, label, "search")
            snapshots.append(("search", watch_path, test_path))

    return not issues, issues, snapshots


def main() -> int:
    args = parse_args()
    ensure_directories()

    try:
        jar_path = ensure_built(args.skip_build, args.rebuild)
        config = load_config(args.config)
    except WatchError as exc:
        print(f"subtitlecat layout watch failed: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    all_failures: List[Tuple[str, List[str], List[Tuple[str, Path, Path]]]] = []
    successes: List[str] = []

    for raw_target in config:
        if not isinstance(raw_target, dict):
            print("Skipping invalid target entry (expected object)", file=sys.stderr)
            continue
        query = str(raw_target.get("query"))
        label = str(raw_target.get("label") or query)
        check_download = bool(raw_target.get("check_download", True))
        max_results = int(raw_target.get("max_results", 5))

        try:
            result = run_cli(
                jar_path, args.java_bin, query, check_download, max_results
            )
        except WatchError as exc:
            all_failures.append((label, [str(exc)], []))
            continue

        ok, issues, snapshots = evaluate_target(raw_target, result)
        if ok:
            successes.append(label)
        else:
            all_failures.append((label, issues, snapshots))

    if all_failures:
        print("Subtitlecat layout watcher detected issues:", file=sys.stderr)
        for label, issues, snapshots in all_failures:
            print(f"- {label}", file=sys.stderr)
            for issue in issues:
                print(f"    * {issue}", file=sys.stderr)
            for kind, watch_path, test_path in snapshots:
                print(
                    f"    * Saved {kind} snapshot to {watch_path} and mirrored it to {test_path}",
                    file=sys.stderr,
                )
        print(
            "Run pytest after updating the parser to ensure the new snapshots under tests/services/subtitlecat/watch_snapshots/ are handled correctly.",
            file=sys.stderr,
        )
        return 1

    for label in successes:
        print(f"✓ {label} selectors resolved as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
