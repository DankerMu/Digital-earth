#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def iter_yaml_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.exists():
        raise FileNotFoundError(str(root))
    return sorted([p for p in root.rglob("*") if p.suffix in {".yml", ".yaml"}])


def validate_yaml_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8-sig")

    try:
        docs = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:  # pragma: no cover
        return [f"{path}: YAML parse error: {exc}"]

    non_empty_docs = [d for d in docs if d is not None]
    if not non_empty_docs:
        errors.append(f"{path}: empty YAML document")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate YAML syntax for repo configs.")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["infra"],
        help="Files/directories to validate (default: infra)",
    )
    args = parser.parse_args()

    files: list[Path] = []
    for raw in args.paths:
        files.extend(iter_yaml_files(Path(raw)))

    if not files:
        raise SystemExit("No YAML files found.")

    all_errors: list[str] = []
    for file_path in files:
        all_errors.extend(validate_yaml_file(file_path))

    if all_errors:
        for err in all_errors:
            print(err)
        return 1

    print(f"YAML OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
