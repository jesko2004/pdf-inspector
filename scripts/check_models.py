"""Usage: python -m scripts.check_models [--output report.json]."""

import argparse
import json
from pathlib import Path

from backend.config import Settings
from backend.model_readiness import check_models


def main():
    parser = argparse.ArgumentParser(description="Probe configured embedding, grounded JSON generation and stream contracts")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check_models(Settings.from_env())
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()
