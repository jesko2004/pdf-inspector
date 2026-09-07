#!/usr/bin/env python3
"""Check extracted UTF-8 text for script and decoding regressions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


SCRIPT_RANGES = {
    "arabic": ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
               (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
    "cyrillic": ((0x0400, 0x052F),),
    "devanagari": ((0x0900, 0x097F),),
    "han": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)),
    "hebrew": ((0x0590, 0x05FF),),
    "latin": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F),
              (0x1E00, 0x1EFF)),
}

MOJIBAKE_MARKERS = ("锟", "Ãƒ", "Â ", "â€", "ï¿½")


def script_for_char(char: str) -> str | None:
    codepoint = ord(char)
    for script, ranges in SCRIPT_RANGES.items():
        if any(start <= codepoint <= end for start, end in ranges):
            return script
    return None


def analyze_text(text: str) -> dict[str, object]:
    scripts: Counter[str] = Counter()
    for char in text:
        script = script_for_char(char)
        if script is not None and char.isalpha():
            scripts[script] += 1
    return {
        "characters": len(text),
        "scripts": dict(sorted(scripts.items())),
        "replacement_characters": text.count("\N{REPLACEMENT CHARACTER}"),
        "c1_controls": sum("\x80" <= char <= "\x9f" for char in text),
        "private_use_characters": sum(
            0xE000 <= ord(char) <= 0xF8FF
            or 0xF0000 <= ord(char) <= 0xFFFFD
            or 0x100000 <= ord(char) <= 0x10FFFD
            for char in text
        ),
        "mojibake_markers": {
            marker: text.count(marker) for marker in MOJIBAKE_MARKERS if marker in text
        },
    }


def evaluate(
    report: dict[str, object],
    *,
    expected_scripts: list[str],
    forbidden_scripts: list[str],
    min_script_characters: int,
    max_replacement_characters: int | None,
    max_c1_controls: int = 0,
    max_private_use_characters: int = 0,
) -> list[str]:
    scripts = report["scripts"]
    assert isinstance(scripts, dict)
    failures = []
    for script in expected_scripts:
        count = int(scripts.get(script, 0))
        if count < min_script_characters:
            failures.append(
                f"expected at least {min_script_characters} {script} letters, found {count}"
            )
    for script in forbidden_scripts:
        count = int(scripts.get(script, 0))
        if count:
            failures.append(f"forbidden script {script} has {count} letters")
    if (
        max_replacement_characters is not None
        and int(report["replacement_characters"]) > max_replacement_characters
    ):
        failures.append(
            "replacement character count "
            f"{report['replacement_characters']} exceeds {max_replacement_characters}"
        )
    if int(report["c1_controls"]) > max_c1_controls:
        failures.append(
            f"C1 control count {report['c1_controls']} exceeds {max_c1_controls}"
        )
    if int(report["private_use_characters"]) > max_private_use_characters:
        failures.append(
            "private-use character count "
            f"{report['private_use_characters']} exceeds {max_private_use_characters}"
        )
    markers = report["mojibake_markers"]
    assert isinstance(markers, dict)
    if markers:
        failures.append(f"found mojibake markers: {markers}")
    return failures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_file", type=Path, help="UTF-8 text or Markdown output")
    parser.add_argument(
        "--expect-script", action="append", default=[], choices=sorted(SCRIPT_RANGES)
    )
    parser.add_argument(
        "--forbid-script", action="append", default=[], choices=sorted(SCRIPT_RANGES)
    )
    parser.add_argument("--min-script-characters", type=int, default=1)
    parser.add_argument("--max-replacement-characters", type=int)
    parser.add_argument("--max-c1-controls", type=int, default=0)
    parser.add_argument("--max-private-use-characters", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.min_script_characters < 0:
        raise SystemExit("--min-script-characters must be non-negative")
    text = args.text_file.read_text(encoding="utf-8")
    report = analyze_text(text)
    failures = evaluate(
        report,
        expected_scripts=args.expect_script,
        forbidden_scripts=args.forbid_script,
        min_script_characters=args.min_script_characters,
        max_replacement_characters=args.max_replacement_characters,
        max_c1_controls=args.max_c1_controls,
        max_private_use_characters=args.max_private_use_characters,
    )
    report["file"] = str(args.text_file)
    report["status"] = "fail" if failures else "pass"
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
