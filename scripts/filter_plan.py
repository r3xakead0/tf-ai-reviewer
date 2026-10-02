#!/usr/bin/env python3
"""Shrink a Terraform JSON plan down to just the fields Claude needs to review.

`terraform show -json` output includes prior state, full resource
configuration, and provider schemas -- often megabytes of data that has
nothing to do with what's actually changing. This script keeps only the
resource_changes that represent real changes (dropping no-ops) and, within
those, only the fields useful for a code review: address, type, name, the
actions being taken, and the before/after values.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def filter_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a slimmed-down list of resource changes, dropping no-ops."""
    filtered = []

    for resource_change in plan.get("resource_changes", []):
        change = resource_change.get("change", {})
        actions = change.get("actions", [])

        if actions == ["no-op"]:
            continue

        filtered.append(
            {
                "address": resource_change.get("address"),
                "type": resource_change.get("type"),
                "name": resource_change.get("name"),
                "change": {
                    "actions": actions,
                    "before": change.get("before"),
                    "after": change.get("after"),
                },
            }
        )

    return filtered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plan_path", nargs="?", default="plan.json", help="Path to terraform show -json output"
    )
    parser.add_argument(
        "output_path", nargs="?", default="filtered.json", help="Where to write the filtered plan"
    )
    args = parser.parse_args()

    plan_path = Path(args.plan_path)
    output_path = Path(args.output_path)

    before_bytes = plan_path.stat().st_size
    plan = json.loads(plan_path.read_text())

    filtered = filter_plan(plan)
    output_path.write_text(json.dumps(filtered, indent=2))

    after_bytes = output_path.stat().st_size
    reduction_pct = 100 * (1 - after_bytes / before_bytes) if before_bytes else 0.0

    print(f"Plan size before filtering: {before_bytes:,} bytes")
    print(f"Plan size after filtering:  {after_bytes:,} bytes")
    print(f"Reduction: {reduction_pct:.1f}%")
    print(f"{len(filtered)} resource change(s) written to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())