"""Backfill legacy student class assignments and sync downstream analytics data."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlmodel import Session

from app.application.analytics.facade import backfill_student_class_ids
from app.db import get_engine, init_db


def _load_mapping_file(path: str | None) -> dict[int, str]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"mapping file not found: {file_path}")

    if file_path.suffix.lower() == ".json":
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {int(k): str(v) for k, v in raw.items()}
        if isinstance(raw, list):
            mapping: dict[int, str] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                user_id = item.get("user_id")
                class_id = item.get("class_id")
                if user_id is None or class_id in (None, ""):
                    continue
                mapping[int(user_id)] = str(class_id)
            return mapping
        raise ValueError("JSON mapping must be an object or a list of {user_id, class_id}")

    if file_path.suffix.lower() == ".csv":
        mapping = {}
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                user_id = row.get("user_id")
                class_id = row.get("class_id")
                if not user_id or not class_id:
                    continue
                mapping[int(user_id)] = class_id
        return mapping

    raise ValueError("mapping file must be .json or .csv")


def _parse_user_ids(raw_values: list[str] | None) -> list[int]:
    if not raw_values:
        return []
    values: list[int] = []
    for item in raw_values:
        parts = [part.strip() for part in str(item).split(",")]
        for part in parts:
            if not part:
                continue
            values.append(int(part))
    return values


async def _main_async(args: argparse.Namespace) -> int:
    init_db()
    explicit_mapping = _load_mapping_file(args.mapping_file)
    target_user_ids = _parse_user_ids(args.user_ids)

    with Session(get_engine()) as session:
        result = await backfill_student_class_ids(
            session,
            explicit_mapping=explicit_mapping,
            only_missing=not args.include_existing,
            dry_run=not args.write,
            default_class_id=args.default_class_id,
            target_user_ids=target_user_ids or None,
        )
        if args.write:
            session.commit()
        else:
            session.rollback()

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill student class assignments and sync analytics records.")
    parser.add_argument("--mapping-file", help="Optional JSON/CSV file with user_id,class_id mappings.")
    parser.add_argument("--default-class-id", help="Fallback class_id when no evidence can be inferred.")
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Also resync students that already have class_id in StudentProfile.",
    )
    parser.add_argument(
        "--user-ids",
        nargs="*",
        help="Optional target user IDs. Supports repeated values or comma-separated values.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply the backfill. Without this flag the script runs in dry-run mode.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
