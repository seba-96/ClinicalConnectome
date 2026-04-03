from __future__ import annotations

import csv
import fnmatch
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

BUNDLED_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
BUNDLED_REFERENCE_BIDS_ROOT = BUNDLED_RESOURCES_DIR / "reference_bids"
BUNDLED_MISSING_JSON_FIELDS_FILE = BUNDLED_RESOURCES_DIR / "missing_json_fields.py"

# Example rewrite: fMRI_rest_run-01 -> task-rest_run-01_bold
DEFAULT_FILENAME_SUBSTITUTIONS: list[tuple[str, str]] = [
    (r"fMRI_rest_(run-[0-9]+)", r"task-rest_\1_bold"),
    (r"Flair", "FLAIR"),
    (r"lesion", "lesion_roi"),
]

DEFAULT_TOPLEVEL_COPY = [
    "dataset_description.json",
    "participants.tsv",
    "participants.json",
    "README",
    "CHANGES",
    ".bidsignore",
]

DEFAULT_BIDSIGNORE_PATTERNS = [
    "*lesion_roi.nii.gz",
    "*lesion_roi.json",
    "acquisitions.tsv",
    "participant_id_map.tsv",
]

DEFAULT_JSON_FIELDS_CONVERSION = {
    "manufacturer": "Manufacturer",
    "machine": "ManufacturersModelName",
    "model": "Model",
    "time_repetition": "RepetitionTime",
    "tesla_field": "MagneticFieldStrength",
    "echo_time": "EchoTime",
    "flip_angle": "FlipAngle",
}

SOURCE_TOPLEVEL_ALLOWLIST = {
    "acquisitions.tsv",
}

SUBJECT_ID_WITH_PREFIX_PATTERN = re.compile(
    r"^(?P<prefix>sub-)?(?P<sid>[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*_[0-9]+)(?P<rest>(?:_.*)?)$"
)


def load_missing_json_fields(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON fields file not found: {path}")

    spec = importlib.util.spec_from_file_location("missing_json_fields_module", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fields = getattr(module, "file_to_json_fields", None)
    if not isinstance(fields, dict):
        raise TypeError(f"Expected dict file_to_json_fields in {path}")
    return fields


def get_bundled_reference_bids_root() -> Path:
    if not BUNDLED_REFERENCE_BIDS_ROOT.is_dir():
        raise NotADirectoryError(f"Bundled reference BIDS root does not exist: {BUNDLED_REFERENCE_BIDS_ROOT}")
    return BUNDLED_REFERENCE_BIDS_ROOT


def get_bundled_missing_json_fields_file() -> Path:
    if not BUNDLED_MISSING_JSON_FIELDS_FILE.is_file():
        raise FileNotFoundError(f"Bundled missing JSON fields file not found: {BUNDLED_MISSING_JSON_FIELDS_FILE}")
    return BUNDLED_MISSING_JSON_FIELDS_FILE


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _rename_json_keys(payload: dict[str, Any], rename_map: dict[str, str], src_path: Path) -> dict[str, Any]:
    renamed: dict[str, Any] = {}
    for key, value in payload.items():
        new_key = rename_map.get(key, key)
        if new_key in renamed and key != new_key:
            raise ValueError(f"Key collision while renaming {src_path}: {key!r} -> {new_key!r}")
        renamed[new_key] = value
    return renamed


def _matching_missing_fields(relative_path: str, missing_rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for pattern, fields in missing_rules.items():
        if fnmatch.fnmatch(relative_path, pattern):
            merged.update(fields)
    return merged


def normalize_subject_token(token: str, add_sub_prefix: bool, collapse_subject_id: bool) -> str:
    match = SUBJECT_ID_WITH_PREFIX_PATTERN.fullmatch(token)
    if not match:
        return token

    sid = match.group("sid")
    rest = match.group("rest") or ""
    prefix = match.group("prefix") or ""

    if collapse_subject_id:
        sid = sid.replace("_", "")

    if add_sub_prefix:
        prefix = "sub-"

    return f"{prefix}{sid}{rest}"


def _apply_name_substitutions(name: str, substitutions: list[tuple[str, str]]) -> str:
    out = name
    for pattern, replacement in substitutions:
        out = re.sub(pattern, replacement, out)
    return out


def _transform_component_name(
    name: str,
    substitutions: list[tuple[str, str]],
    add_sub_prefix: bool,
    collapse_subject_id: bool,
) -> str:
    updated = _apply_name_substitutions(name, substitutions)
    return normalize_subject_token(
        updated,
        add_sub_prefix=add_sub_prefix,
        collapse_subject_id=collapse_subject_id,
    )


def _build_transformed_relative_path(
    rel_path: Path,
    substitutions: list[tuple[str, str]],
    add_sub_prefix: bool,
    collapse_subject_id: bool,
) -> Path:
    transformed_parts = [
        _transform_component_name(part, substitutions, add_sub_prefix, collapse_subject_id)
        for part in rel_path.parts
    ]
    return Path(*transformed_parts)


def _normalize_tsv_participant_id(
    path: Path,
    collapse_subject_id: bool = False,
    mapping: dict[str, str] | None = None,
) -> bool:
    if not path.exists() or path.suffix.lower() != ".tsv":
        return False

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        fields = reader.fieldnames or []

    if "participant_id" not in fields:
        return False

    changed = False
    for row in rows:
        participant_id = (row.get("participant_id") or "").strip()
        if not participant_id:
            continue

        normalized = normalize_subject_token(
            participant_id,
            add_sub_prefix=True,
            collapse_subject_id=collapse_subject_id,
        )
        if normalized != participant_id:
            row["participant_id"] = normalized
            if mapping is not None:
                mapping[participant_id] = normalized
            changed = True

    if changed:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    return changed


def _copy_top_level_bids_files(
    reference_root: Path,
    target_root: Path,
    files_to_copy: list[str],
    overwrite: bool,
) -> dict[str, int]:
    stats = {"copied": 0, "missing_in_reference": 0}

    if not reference_root.is_dir():
        raise NotADirectoryError(f"Reference BIDS root does not exist: {reference_root}")

    for filename in files_to_copy:
        src = reference_root / filename
        dst = target_root / filename

        if not src.exists():
            stats["missing_in_reference"] += 1
            continue

        force_from_reference = filename == "dataset_description.json"
        if dst.exists() or dst.is_symlink():
            if not overwrite and not force_from_reference:
                continue
            _remove_path(dst)

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        stats["copied"] += 1

    return stats


def _sync_participants_json_with_tsv(target_root: Path) -> bool:
    participants_tsv = target_root / "participants.tsv"
    participants_json = target_root / "participants.json"

    if not participants_tsv.exists():
        return False

    with participants_tsv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fields = reader.fieldnames or []

    if not fields:
        return False

    payload: dict[str, Any] = {}
    if participants_json.exists():
        loaded = json.loads(participants_json.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded

    changed = False
    for field in fields:
        entry = payload.get(field)
        if not isinstance(entry, dict):
            payload[field] = {"Description": "(TODO: add description)"}
            changed = True
            continue
        if "Description" not in entry:
            entry["Description"] = "(TODO: add description)"
            payload[field] = entry
            changed = True

    if changed or not participants_json.exists():
        participants_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return True

    return False


def _ensure_bidsignore(target_root: Path, patterns: list[str]) -> bool:
    bidsignore_path = target_root / ".bidsignore"
    existing_lines: list[str] = []

    if bidsignore_path.exists():
        existing_lines = [
            line.strip() for line in bidsignore_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    changed = False
    for pattern in patterns:
        if pattern not in existing_lines:
            existing_lines.append(pattern)
            changed = True

    if not bidsignore_path.exists() or changed:
        bidsignore_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
        return True

    return False


def _should_skip_source_file(rel_path: Path, skip_patterns: list[str]) -> bool:
    rel_posix = rel_path.as_posix()
    rel_name = rel_path.name
    for pattern in skip_patterns:
        if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(rel_name, pattern):
            return True
    return False


def _write_participant_id_map_tsv(target_dir: Path, mapping: dict[str, str], filename: str) -> bool:
    if not mapping:
        return False

    output_path = target_dir / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["original_participant_id", "bids_participant_id"])
        for original in sorted(mapping):
            writer.writerow([original, mapping[original]])

    return True


def create_bids_ready_tree(
    source_dir: Path,
    target_dir: Path,
    missing_json_fields: dict[str, dict[str, Any]] | None = None,
    json_fields_conv: dict[str, str] | None = None,
    overwrite: bool = False,
    substitutions: list[tuple[str, str]] | None = None,
    add_sub_prefix: bool = True,
    reference_bids_root: Path | None = None,
    copy_top_level_files: list[str] | None = None,
    copy_source_files: bool = True,
    collapse_subject_id: bool = True,
    skip_source_patterns: list[str] | None = None,
    write_participant_id_map: bool = True,
    participant_id_map_filename: str = "participant_id_map.tsv",
) -> dict[str, int]:
    source_dir = source_dir.expanduser().resolve()
    target_dir = target_dir.expanduser().resolve()

    missing_json_fields = missing_json_fields or {}
    json_fields_conv = json_fields_conv or DEFAULT_JSON_FIELDS_CONVERSION
    substitutions = substitutions or []
    skip_source_patterns = skip_source_patterns or []

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source directory does not exist: {source_dir}")

    if target_dir.exists() and any(target_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Target directory is not empty: {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)

    allowed_top_level_files: set[str] | None = None
    resolved_reference_root: Path | None = None
    if reference_bids_root is not None:
        resolved_reference_root = reference_bids_root.expanduser().resolve()
        if not resolved_reference_root.is_dir():
            raise NotADirectoryError(f"Reference BIDS root does not exist: {resolved_reference_root}")
        allowed_top_level_files = {p.name for p in resolved_reference_root.iterdir() if p.is_file()}

    stats = {
        "dirs": 0,
        "json_files": 0,
        "symlink_files": 0,
        "copied_source_files": 0,
        "renamed_paths": 0,
        "participants_normalized": 0,
        "acquisitions_normalized": 0,
        "copied_toplevel_files": 0,
        "missing_toplevel_in_reference": 0,
        "skipped_non_bids_top_level_files": 0,
        "bidsignore_updated": 0,
        "participants_json_updated": 0,
        "skipped_source_files": 0,
        "participant_id_map_written": 0,
    }

    emitted_paths: set[Path] = set()
    participant_id_mapping: dict[str, str] = {}

    for src_path in sorted(source_dir.rglob("*")):
        rel_path = src_path.relative_to(source_dir)

        if (
            allowed_top_level_files is not None
            and len(rel_path.parts) == 1
            and src_path.is_file()
            and rel_path.name not in SOURCE_TOPLEVEL_ALLOWLIST
            and rel_path.name not in allowed_top_level_files
        ):
            stats["skipped_non_bids_top_level_files"] += 1
            continue

        transformed_rel_path = _build_transformed_relative_path(
            rel_path,
            substitutions,
            add_sub_prefix,
            collapse_subject_id,
        )
        dst_path = target_dir / transformed_rel_path

        if transformed_rel_path != rel_path:
            stats["renamed_paths"] += 1

        if dst_path in emitted_paths:
            raise FileExistsError(f"Multiple source files map to the same target path: {dst_path}")

        emitted_paths.add(dst_path)

        if src_path.is_dir():
            dst_path.mkdir(parents=True, exist_ok=True)
            stats["dirs"] += 1
            continue

        if _should_skip_source_file(rel_path, skip_source_patterns):
            stats["skipped_source_files"] += 1
            continue

        if dst_path.exists() or dst_path.is_symlink():
            if not overwrite:
                raise FileExistsError(f"Path already exists in target: {dst_path}")
            _remove_path(dst_path)

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.suffix.lower() == ".json":
            payload = json.loads(src_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                renamed_payload = _rename_json_keys(payload, json_fields_conv, src_path)
                defaults = _matching_missing_fields(rel_path.as_posix(), missing_json_fields)
                defaults.update(_matching_missing_fields(transformed_rel_path.as_posix(), missing_json_fields))
                for key, value in defaults.items():
                    renamed_payload.setdefault(key, value)
            else:
                renamed_payload = payload

            dst_path.write_text(
                json.dumps(renamed_payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            stats["json_files"] += 1
        else:
            if copy_source_files:
                shutil.copy2(src_path, dst_path)
                stats["copied_source_files"] += 1
            else:
                link_target = os.path.relpath(src_path, start=dst_path.parent)
                dst_path.symlink_to(link_target)
                stats["symlink_files"] += 1

    participants_target = target_dir / "participants.tsv"
    if participants_target.exists() and _normalize_tsv_participant_id(
        participants_target,
        collapse_subject_id=collapse_subject_id,
        mapping=participant_id_mapping,
    ):
        stats["participants_normalized"] += 1

    acquisitions_target = target_dir / "acquisitions.tsv"
    if acquisitions_target.exists() and _normalize_tsv_participant_id(
        acquisitions_target,
        collapse_subject_id=collapse_subject_id,
        mapping=participant_id_mapping,
    ):
        stats["acquisitions_normalized"] += 1

    if reference_bids_root is not None:
        copied_stats = _copy_top_level_bids_files(
            reference_root=resolved_reference_root,
            target_root=target_dir,
            files_to_copy=copy_top_level_files or DEFAULT_TOPLEVEL_COPY,
            overwrite=overwrite,
        )
        stats["copied_toplevel_files"] += copied_stats["copied"]
        stats["missing_toplevel_in_reference"] += copied_stats["missing_in_reference"]

        if participants_target.exists() and _normalize_tsv_participant_id(
            participants_target,
            collapse_subject_id=collapse_subject_id,
            mapping=participant_id_mapping,
        ):
            stats["participants_normalized"] += 1
        if acquisitions_target.exists() and _normalize_tsv_participant_id(
            acquisitions_target,
            collapse_subject_id=collapse_subject_id,
            mapping=participant_id_mapping,
        ):
            stats["acquisitions_normalized"] += 1

    if _ensure_bidsignore(target_dir, DEFAULT_BIDSIGNORE_PATTERNS):
        stats["bidsignore_updated"] += 1

    if _sync_participants_json_with_tsv(target_dir):
        stats["participants_json_updated"] += 1

    if collapse_subject_id and write_participant_id_map and _write_participant_id_map_tsv(
        target_dir,
        participant_id_mapping,
        participant_id_map_filename,
    ):
        stats["participant_id_map_written"] += 1

    return stats

