"""
Миграция JSON материалов к схеме property_groups.
Старые physical_properties / mechanical_properties / chemical_properties
конвертируются через Material.normalize_schema().
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.models.material import Material  # noqa: E402
from src.core.schema_keys import Schema  # noqa: E402


def migrate_file(path: Path, dry_run: bool = False) -> bool:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return False
    if Schema.METADATA not in data and "material_id" not in data:
        return False

    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    mat = Material(data=data)
    mat.normalize_schema()
    after = json.dumps(mat.data, ensure_ascii=False, sort_keys=True)
    if before == after:
        return False
    if not dry_run:
        with path.open("w", encoding="utf-8") as f:
            json.dump(mat.data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=[str(ROOT / "data")])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.glob("*.json")))
        elif p.is_file():
            files.append(p)

    changed = skipped = 0
    for path in files:
        if path.name.lower() == "source.json":
            skipped += 1
            continue
        try:
            if migrate_file(path, dry_run=args.dry_run):
                print(f"{'[dry] ' if args.dry_run else ''}migrated: {path}")
                changed += 1
            else:
                skipped += 1
        except Exception as exc:
            print(f"ERROR {path}: {exc}")
    print(f"Done. changed={changed}, skipped={skipped}")


if __name__ == "__main__":
    main()
