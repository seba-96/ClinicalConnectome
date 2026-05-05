from __future__ import annotations

import csv
from dataclasses import dataclass
import fnmatch
import gzip
import importlib.util
import json
import math
import os
import re
import shutil
import struct
import warnings
import zlib
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to

BUNDLED_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
BUNDLED_REFERENCE_BIDS_ROOT = BUNDLED_RESOURCES_DIR / "reference_bids"
BUNDLED_MISSING_JSON_FIELDS_FILE = BUNDLED_RESOURCES_DIR / "missing_json_fields.json"

# Example rewrite: fMRI_rest_run-01 -> task-rest_run-01_bold
DEFAULT_FILENAME_SUBSTITUTIONS: list[tuple[str, str]] = [
    (r"fMRI_PA", r"dir-PA_epi"),
    (r"fMRI_AP", r"dir-AP_epi"),
    (r"fMRI_rest_pa", r"dir-PA_epi"), # fmri fmap
    (r"fMRI_rest_PA", r"dir-PA_epi"),  # fmri fmap
    (r"fMRI_rest_ap", r"dir-AP_epi"),  # fmri fmap
    (r"fMRI_rest_AP", r"dir-AP_epi"),  # fmri fmap
    (r"fMRI_rest_(run-[0-9]+)", r"task-rest_\1_bold"),
    (r"fMRI_rest_run([0-9]+)", r"task-rest_run-\1_bold"),
    (r"fMRI_rest", r"task-rest_bold"),
    (r"Flair", "FLAIR"),
    (r"lesion", "lesion_roi"),
    (r'T1w_pre', 'T1w'),
    (r'SWI', 'swi'),
    (r'T1w_wca', 'ce-gadolinium_T1w'),
    (r"dMRI_pa", "dir-PA_epi"),  # dwi fmap
    (r"dMRI_PA", "dir-PA_epi"),  # dwi fmap
    (r"dMRI_ap", "dir-AP_epi"),  # dwi fmap
    (r"dMRI_AP", "dir-AP_epi"),
    (r"dMRI", "dwi"),
    (r"dir-AP_epi", "acq-dwi_dir-AP_epi"), # FIXME not ideal: it assumes that the fmap if for dwi
    (r"dir-PA_epi", "acq-dwi_dir-PA_epi"), # FIXME not ideal: it assumes that the fmap if for dwi
    (r"magnitude1", "acq-fmri_magnitude1"),
    (r"magnitude2", "acq-fmri_magnitude2"),
    (r"phasediff", "acq-fmri_phasediff"),
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
    "acquisitions_dmp.tsv",
    "**/perf/*_dsc.nii.gz",
    "**/perf/*_dsc.json"
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
    "README",
    "README.md",
}

SUBJECT_ID_WITH_PREFIX_PATTERN = re.compile(
    r"^(?P<prefix>sub-)?(?P<sid>(?:[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*[_-][0-9]+|[0-9]+))(?P<rest>(?:_.*)?)$"
)
SUBJECT_ID_RANGE_PATTERN = re.compile(r"^(?P<start>\d+)\s*-\s*(?P<end>\d+)$")
INTENDEDFOR_SUFFIXES = ("_bold.nii.gz", "_dwi.nii.gz")
IMAGING_MODALITY_PARTS = {"anat", "func", "dwi", "fmap", "perf", "pet"}
ILLEGAL_SUBJECT_SUBFOLDERS = {"features"}
NON_SUBJECT_ENTITY_PREFIXES = (
    "ses-",
    "task-",
    "acq-",
    "ce-",
    "rec-",
    "run-",
    "echo-",
    "part-",
    "chunk-",
    "space-",
    "desc-",
    "dir-",
    "mod-",
)
GLOB_WILDCARD_CHARS = "*?[]"


@dataclass(frozen=True)
class LesionConfig:
    space: str
    source_subdir: str | None = None
    pattern: str | None = None
    resample: bool = False
    split: bool = False
    split_labels: list[tuple[tuple[int, ...], str]] | None = None
    combined_desc: str | None = None
    primary_desc: str | None = None


def get_bundled_missing_json_fields_file() -> Path:
    return Path(__file__).parent / "resources" / "missing_json_fields.json"


def load_missing_json_fields(source: str | Path | dict) -> dict[str, dict[str, Any]]:
    if isinstance(source, dict):
        return source.get("file_to_json_fields", source)
    
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON fields file not found: {path}")

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        if "file_to_json_fields" in content:
            fields = content["file_to_json_fields"]
        else:
            fields = content
        if not isinstance(fields, dict):
            raise TypeError(f"Expected dict file_to_json_fields in {path}")
        return fields
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse JSON from {path}: {exc}") from exc


def get_bundled_reference_bids_root() -> Path:
    if not BUNDLED_REFERENCE_BIDS_ROOT.is_dir():
        raise NotADirectoryError(f"Bundled reference BIDS root does not exist: {BUNDLED_REFERENCE_BIDS_ROOT}")
    return BUNDLED_REFERENCE_BIDS_ROOT




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


def _parse_subject_id_range(rule_key: str) -> tuple[int, int] | None:
    match = SUBJECT_ID_RANGE_PATTERN.fullmatch(rule_key.strip())
    if not match:
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    if start > end:
        return None
    return (start, end)


def _extract_subject_numeric_id(relative_paths: list[str]) -> int | None:
    for relative_path in relative_paths:
        for token in Path(relative_path).parts:
            if token.startswith("sub-"):
                match = re.search(r"(\d+)(?!.*\d)", token[4:])
                if match:
                    return int(match.group(1))
            normalized_match = SUBJECT_ID_WITH_PREFIX_PATTERN.fullmatch(token)
            if normalized_match:
                sid = normalized_match.group("sid")
                match = re.search(r"(\d+)(?!.*\d)", sid)
                if match:
                    return int(match.group(1))
    return None


def _matches_modality_rule(relative_path: str, rule_pattern: str) -> bool:
    rel_lower = relative_path.lower()
    name_lower = Path(relative_path).name.lower()
    pattern_lower = rule_pattern.lower()

    if any(char in rule_pattern for char in "*?[]"):
        return fnmatch.fnmatch(rel_lower, pattern_lower) or fnmatch.fnmatch(name_lower, pattern_lower)

    return pattern_lower in rel_lower or pattern_lower in name_lower


def _matching_range_missing_fields(relative_paths: list[str], missing_rules: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    subject_id = _extract_subject_numeric_id(relative_paths)
    if subject_id is None:
        return merged

    for rule_key, modality_rules in missing_rules.items():
        parsed_range = _parse_subject_id_range(rule_key)
        if parsed_range is None or not isinstance(modality_rules, dict):
            continue
        start, end = parsed_range
        if not (start <= subject_id <= end):
            continue

        for modality_pattern, fields in modality_rules.items():
            if not isinstance(fields, dict):
                continue
            modality_pattern_str = str(modality_pattern)
            if any(_matches_modality_rule(relative_path, modality_pattern_str) for relative_path in relative_paths):
                merged.update(fields)

    return merged


def inject_missing_json_in_place(target_dir: Path, missing_json_fields: dict[str, dict[str, Any]]) -> dict[str, int]:
    target_dir = target_dir.expanduser().resolve()
    if not target_dir.is_dir():
        raise NotADirectoryError(f"Target directory does not exist: {target_dir}")

    stats = {"json_files_updated": 0, "keys_added": 0}
    for json_path in sorted(target_dir.rglob("*.json")):
        rel_path = json_path.relative_to(target_dir)
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(payload, dict):
            continue

        defaults = _matching_missing_fields(rel_path.as_posix(), missing_json_fields)
        defaults.update(_matching_range_missing_fields([rel_path.as_posix()], missing_json_fields))

        added = 0
        for key, value in defaults.items():
            if key not in payload:
                payload[key] = value
                added += 1

        if added > 0:
            json_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            stats["json_files_updated"] += 1
            stats["keys_added"] += added

    return stats


def normalize_subject_token(token: str, add_sub_prefix: bool, collapse_subject_id: bool) -> str:
    # Normalize only the leading subject-like token and keep BIDS entities untouched.
    if any(token.startswith(prefix) for prefix in NON_SUBJECT_ENTITY_PREFIXES):
        return token

    core = token
    suffix = ""
    for known_suffix in (".nii.gz", ".nii", ".json", ".bval", ".bvec", ".tsv"):
        if core.endswith(known_suffix):
            core = core[: -len(known_suffix)]
            suffix = known_suffix
            break

    # Fixed rule: subject starts at token beginning and ends at first 4 consecutive digits.
    first_four_digits = re.search(r"\d{4}", core)
    if first_four_digits is None:
        return token

    head = core[: first_four_digits.end()]
    tail = core[first_four_digits.end() :]

    prefix = ""
    sid = head
    if head.startswith("sub-"):
        prefix = "sub-"
        sid = head[len(prefix) :]

    if collapse_subject_id:
        sid = re.sub(r"[_-]", "", sid)

    if add_sub_prefix:
        prefix = "sub-"

    return f"{prefix}{sid}{tail}{suffix}"


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
    dmp_column_name: str = "participant_id_dmp",
    normalize_numeric_columns: bool = False,
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
    if dmp_column_name not in fields:
        fields = [*fields, dmp_column_name]
        changed = True

    for row in rows:
        participant_id = (row.get("participant_id") or "").strip()
        if not participant_id:
            continue

        original_participant_id = (row.get(dmp_column_name) or "").strip()
        if not original_participant_id:
            row[dmp_column_name] = participant_id
            changed = True

        normalized = normalize_subject_token(
            participant_id,
            add_sub_prefix=True,
            collapse_subject_id=collapse_subject_id,
        )
        if normalized != participant_id:
            row["participant_id"] = normalized
            changed = True

        if normalize_numeric_columns:
            for field in fields:
                if field in {"participant_id", dmp_column_name}:
                    continue
                value = row.get(field)
                if not isinstance(value, str):
                    continue
                normalized_numeric = _normalize_participants_numeric_value(value)
                if normalized_numeric != value:
                    row[field] = normalized_numeric
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
        
        if Path(filename).stem == "README":
            existing_readmes = [p for p in target_root.iterdir() if p.name.startswith("README")]
            if existing_readmes:
                if not overwrite and not force_from_reference:
                    continue
                for existing in existing_readmes:
                    _remove_path(existing)
        else:
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


def _has_lesion_files(
    source_dir: Path,
    lesion_source_subdir: str | None = None,
    lesion_pattern: str | None = None,
) -> bool:
    return bool(
        _find_lesion_files(
            source_dir,
            lesion_source_subdir=lesion_source_subdir,
            lesion_pattern=lesion_pattern,
        )
    )


def _is_lesion_related_file(
    rel_path: Path,
    lesion_source_subdir: str | None = None,
    lesion_pattern: str | None = None,
) -> bool:
    rel_posix = rel_path.as_posix().lower()
    if lesion_source_subdir:
        normalized_subdir = lesion_source_subdir.strip().strip("/").lower()
        if normalized_subdir:
            parts = [part.lower() for part in rel_path.parts[:-1]]
            if normalized_subdir not in parts and f"/{normalized_subdir}/" not in f"/{rel_posix}/":
                return False

    name = rel_path.name.lower()
    if lesion_pattern:
        if not fnmatch.fnmatch(rel_posix, lesion_pattern.lower()) and lesion_pattern.lower() not in rel_posix:
            return False
    elif "lesion" not in name:
        return False

    return name.endswith(".nii.gz") or name.endswith(".nii") or name.endswith(".json")


def _find_lesion_files(
    source_dir: Path,
    lesion_source_subdir: str | None = None,
    lesion_pattern: str | None = None,
) -> list[Path]:
    found: list[Path] = []
    for src_path in sorted(source_dir.rglob("*")):
        if not src_path.is_file():
            continue
        rel_path = src_path.relative_to(source_dir)
        if _is_lesion_related_file(
            rel_path,
            lesion_source_subdir=lesion_source_subdir,
            lesion_pattern=lesion_pattern,
        ):
            found.append(rel_path)
    return found


def _subjects_with_multiple_lesions(lesion_relative_paths: list[Path]) -> set[str]:
    counts: dict[str, int] = {}
    for rel_path in lesion_relative_paths:
        subject = _extract_subject_label(rel_path)
        if subject is None:
            continue
        counts[subject] = counts.get(subject, 0) + 1
    return {subject for subject, count in counts.items() if count > 1}


def _extract_subject_label(rel_path: Path) -> str | None:
    subject = _extract_bids_entity(rel_path, "sub-")
    if subject is not None:
        return subject
    match = re.search(r"(sub-[A-Za-z0-9]+)", rel_path.name)
    if match:
        return match.group(1)
    return None


def _path_suffix(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return ".nii.gz"
    return path.suffix


def _safe_descriptor_token(filename: str) -> str:
    stem = filename
    for suffix in (".nii.gz", ".nii", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()
    return stem or "lesion"


def _coerce_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise TypeError(f"{name} must be a boolean")


def _parse_split_label_tokens(raw_key: Any) -> tuple[int, ...]:
    if isinstance(raw_key, (list, tuple, set)):
        key_tokens = [str(token).strip() for token in raw_key if str(token).strip()]
    else:
        key_tokens = [token for token in re.split(r"[,\-|\s]+", str(raw_key).strip()) if token]
    if not key_tokens:
        raise TypeError(f"Invalid split label key {raw_key!r}; expected one or more integers")
    labels: list[int] = []
    for token in key_tokens:
        try:
            label = int(token)
        except ValueError as exc:
            raise TypeError(f"Invalid split label key token {token!r}; expected an integer") from exc
        if label <= 0:
            raise ValueError(f"Split label keys must be > 0, got {label}")
        labels.append(label)
    return tuple(sorted(set(labels)))


def _normalize_split_label_map(
    raw: dict[Any, Any] | list[tuple[list[int], str]] | list[tuple[tuple[int, ...], str]] | None,
) -> list[tuple[tuple[int, ...], str]]:
    if not raw:
        return []

    normalized: list[tuple[tuple[int, ...], str]] = []
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = list(raw)
    else:
        raise TypeError("split_labels must be a dict or list of (labels, desc) tuples")

    for key, value in items:
        labels = _parse_split_label_tokens(key)
        desc = _safe_descriptor_token(str(value))
        normalized.append((labels, desc))
    return normalized


def _resolve_lesion_configs(
    lesion_configs: list[dict[str, Any]] | None,
    lesion_space: str | None,
    lesion_source_subdir: str | None,
    lesion_pattern: str | None,
    lesion_resample: bool,
    lesion_split: bool,
    lesion_split_labels: dict[Any, Any] | list[tuple[list[int], str]] | list[tuple[tuple[int, ...], str]] | None,
    lesion_split_combined_desc: str | None,
    lesion_split_primary_desc: str | None,
) -> list[LesionConfig]:
    if lesion_configs:
        resolved: list[LesionConfig] = []
        for index, payload in enumerate(lesion_configs):
            if not isinstance(payload, dict):
                raise TypeError(f"lesion_configs[{index}] must be a dict")
            space = str(payload.get("space", "")).strip()
            if not space:
                raise ValueError(f"lesion_configs[{index}] requires non-empty 'space'")

            source_subdir = payload.get("source_subdir")
            pattern = payload.get("pattern")
            if source_subdir is not None:
                source_subdir = str(source_subdir)
            if pattern is not None:
                pattern = str(pattern)

            resample = _coerce_bool(payload.get("resample", False), f"lesion_configs[{index}].resample")
            split = _coerce_bool(payload.get("split", False), f"lesion_configs[{index}].split")
            split_labels = _normalize_split_label_map(payload.get("split_labels"))
            combined_desc = payload.get("combined_desc")
            if combined_desc is not None:
                combined_desc = _safe_descriptor_token(str(combined_desc))
            primary_desc = payload.get("primary_desc")
            if primary_desc is not None:
                primary_desc = _safe_descriptor_token(str(primary_desc))

            resolved.append(
                LesionConfig(
                    space=space,
                    source_subdir=source_subdir,
                    pattern=pattern,
                    resample=resample,
                    split=split,
                    split_labels=split_labels,
                    combined_desc=combined_desc,
                    primary_desc=primary_desc,
                )
            )
        return resolved

    if lesion_space is None:
        return []

    return [
        LesionConfig(
            space=lesion_space,
            source_subdir=lesion_source_subdir,
            pattern=lesion_pattern,
            resample=lesion_resample,
            split=lesion_split,
            split_labels=_normalize_split_label_map(lesion_split_labels),
            combined_desc=_safe_descriptor_token(lesion_split_combined_desc) if lesion_split_combined_desc else None,
            primary_desc=_safe_descriptor_token(lesion_split_primary_desc) if lesion_split_primary_desc else None,
        )
    ]


def _lesion_destination_relative_path(
    source_rel_path: Path,
    transformed_rel_path: Path,
    lesion_space: str,
    multiple_for_subject: bool = False,
    desc_label: str | None = None,
    force_derivatives: bool = False,
) -> Path:
    subject = _extract_subject_label(transformed_rel_path) or _extract_subject_label(source_rel_path)
    if subject is None:
        raise ValueError(f"Could not infer subject ID for lesion file: {source_rel_path}")

    suffix = _path_suffix(transformed_rel_path)
    normalized_space = lesion_space.strip()
    if not normalized_space:
        raise ValueError("lesion_space cannot be empty when lesion files are present")

    desc_entity = ""
    if desc_label:
        desc_entity = f"_desc-{_safe_descriptor_token(desc_label)}"
    elif multiple_for_subject:
        desc_entity = f"_desc-{_safe_descriptor_token(source_rel_path.name)}"

    if "mni" not in normalized_space.lower() and not force_derivatives:
        filename = f"{subject}_space-{normalized_space}{desc_entity}_lesion_roi{suffix}"
        return Path(subject) / "anat" / filename

    filename = f"{subject}_space-{normalized_space}{desc_entity}_label-lesion_mask{suffix}"
    return Path("derivatives") / "manual_masks" / subject / "anat" / filename


def _is_nifti_path(path: Path) -> bool:
    return path.name.endswith(".nii.gz") or path.suffix.lower() == ".nii"


def _save_binary_mask_like(source_image: nib.spatialimages.SpatialImage, mask_data: np.ndarray, output_path: Path) -> None:
    mask_uint8 = (mask_data > 0).astype(np.uint8)
    header = source_image.header.copy()
    header.set_data_shape(mask_uint8.shape)
    output = nib.Nifti1Image(mask_uint8, source_image.affine, header=header)
    output.set_qform(source_image.affine, code=1)
    output.set_sform(source_image.affine, code=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(output, str(output_path))


def _split_integer_lesion_mask(
    source_path: Path,
    source_rel_path: Path,
    transformed_rel_path: Path,
    lesion_space: str,
    split_labels: list[tuple[tuple[int, ...], str]],
    combined_desc: str | None,
    multiple_for_subject: bool,
) -> list[tuple[str, np.ndarray, nib.spatialimages.SpatialImage]]:
    image = nib.load(str(source_path))
    data = np.asarray(image.dataobj)
    if data.ndim != 3:
        raise ValueError(f"Split lesion mask must be 3D: {source_rel_path}")

    rounded = np.rint(data)
    labels = sorted({int(value) for value in np.unique(rounded[np.isfinite(rounded)]) if value > 0})
    if not labels:
        raise ValueError(f"No label > 0 found for split lesion mask: {source_rel_path}")

    recipe_entries: list[tuple[str, set[int]]] = []
    if split_labels:
        labels_by_desc: dict[str, set[int]] = {}
        for recipe_labels, desc in split_labels:
            matched = {label for label in recipe_labels if label in labels}
            if matched:
                labels_by_desc.setdefault(desc, set()).update(matched)
        recipe_entries = [(desc, desc_labels) for desc, desc_labels in labels_by_desc.items()]
    else:
        for label in labels:
            recipe_entries.append((f"label{label}", {label}))

    outputs: list[tuple[str, np.ndarray, nib.spatialimages.SpatialImage]] = []
    for desc, desc_labels in recipe_entries:
        if not desc_labels:
            continue
        mask = np.isin(rounded, list(desc_labels))
        if not np.any(mask):
            continue
        outputs.append((desc, mask, image))

    if combined_desc:
        if split_labels:
            included_labels = {label for recipe_labels, _desc in split_labels for label in recipe_labels}
            combined_mask = np.isin(rounded, list(included_labels))
        else:
            combined_mask = rounded > 0
        outputs.append((combined_desc, combined_mask, image))

    if not outputs:
        raise ValueError(
            f"No split outputs produced for lesion mask: {source_rel_path}. "
            "If using split_labels, ensure labels match values in the mask."
        )

    return outputs


def _is_adc_dwi_file(rel_path: Path) -> bool:
    if "dwi" not in rel_path.parts:
        return False
    name = rel_path.name.lower()
    if "adc" not in name:
        return False
    return name.endswith((".nii.gz", ".nii", ".json"))


def _clinical_dwi_destination_relative_path(transformed_rel_path: Path) -> Path:
    parts = transformed_rel_path.parts
    start_index = 0
    for index, part in enumerate(parts):
        if part.startswith("sub-"):
            start_index = index
            break
    retained = Path(*parts[start_index:]) if parts else transformed_rel_path
    return Path("derivatives") / "clinical_dwi" / retained


def _path_has_token(rel_path: Path, token: str) -> bool:
    return token in rel_path.parts


def _matches_pattern_list(rel_path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return False

    rel_posix = rel_path.as_posix().lower()
    name_lower = rel_path.name.lower()
    for raw_pattern in patterns:
        pattern = raw_pattern.strip().lower()
        if not pattern:
            continue
        if any(char in pattern for char in GLOB_WILDCARD_CHARS):
            if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(name_lower, pattern):
                return True
        elif pattern in rel_posix or pattern in name_lower:
            return True
    return False


def _split_known_suffix(filename: str) -> tuple[str, str]:
    for suffix in (".nii.gz", ".nii", ".json", ".bval", ".bvec", ".tsv"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)], suffix
    return filename, ""


def _ensure_acq_entity(stem: str, acq_label: str) -> str:
    tokens = stem.split("_") if stem else [stem]
    acq_token = f"acq-{acq_label}"

    for index, token in enumerate(tokens):
        if token.startswith("acq-"):
            tokens[index] = acq_token
            return "_".join(tokens)

    insert_index = 0
    if tokens and tokens[0].startswith("sub-"):
        insert_index = 1
        if len(tokens) > 1 and tokens[1].startswith("ses-"):
            insert_index = 2

    tokens.insert(insert_index, acq_token)
    return "_".join(tokens)


def _move_fmap_file_to_fmap_dir(
    transformed_rel_path: Path,
    acq_label: str,
) -> Path:
    parts = list(transformed_rel_path.parts)
    modality_index = None
    for index, token in enumerate(parts):
        if token in {"func", "dwi"}:
            modality_index = index
            break

    if modality_index is None:
        return transformed_rel_path

    parts[modality_index] = "fmap"
    stem, suffix = _split_known_suffix(parts[-1])
    parts[-1] = f"{_ensure_acq_entity(stem, acq_label)}{suffix}"
    return Path(*parts)


def _fmap_reclassified_relative_path(
    source_rel_path: Path,
    transformed_rel_path: Path,
    fmap_fmri_patterns: list[str],
    fmap_dwi_patterns: list[str],
) -> Path | None:
    in_func = _path_has_token(source_rel_path, "func")
    in_dwi = _path_has_token(source_rel_path, "dwi")

    matched_fmri = in_func and _matches_pattern_list(source_rel_path, fmap_fmri_patterns)
    matched_dwi = in_dwi and _matches_pattern_list(source_rel_path, fmap_dwi_patterns)

    if matched_fmri and matched_dwi:
        raise ValueError(
            "File matches both --fmap-fmri-pattern and --fmap-dwi-pattern; make patterns more specific: "
            f"{source_rel_path}"
        )

    if matched_fmri:
        return _move_fmap_file_to_fmap_dir(transformed_rel_path, acq_label="fmri")
    if matched_dwi:
        return _move_fmap_file_to_fmap_dir(transformed_rel_path, acq_label="dwi")
    return None


def _extract_bids_entity(rel_path: Path, entity_prefix: str) -> str | None:
    for token in rel_path.parts:
        if token.startswith(entity_prefix):
            return token
    return None


def _collect_intendedfor_candidates(target_dir: Path) -> dict[tuple[str, str | None], list[str]]:
    collected: dict[tuple[str, str | None], set[str]] = {}
    for nii_path in sorted(target_dir.rglob("*.nii.gz")):
        rel_path = nii_path.relative_to(target_dir)
        name = rel_path.name
        if not name.endswith(INTENDEDFOR_SUFFIXES):
            continue

        subject = _extract_bids_entity(rel_path, "sub-")
        if subject is None:
            continue

        subject_rel = _to_subject_relative_path(rel_path)
        if subject_rel is None:
            continue

        session = _extract_bids_entity(rel_path, "ses-")
        collected.setdefault((subject, session), set()).add(subject_rel)

    return {key: sorted(values) for key, values in collected.items()}


def _matching_intendedfor_entries(
    rel_json_path: Path,
    intendedfor_candidates: dict[tuple[str, str | None], list[str]],
    intendedfor_modality_override: str | None = None,
) -> list[str]:
    subject = _extract_bids_entity(rel_json_path, "sub-")
    if subject is None:
        return []

    session = _extract_bids_entity(rel_json_path, "ses-")
    if session is not None:
        entries = list(intendedfor_candidates.get((subject, session), []))
    else:
        merged: set[str] = set()
        for (candidate_subject, _candidate_session), entries in intendedfor_candidates.items():
            if candidate_subject == subject:
                merged.update(entries)
        entries = sorted(merged)

    desired_modality = intendedfor_modality_override or _desired_intendedfor_modality(rel_json_path.name)
    if desired_modality is None:
        return entries
    return [entry for entry in entries if entry.endswith(f"_{desired_modality}.nii.gz")]


def _desired_intendedfor_modality(fmap_json_name: str) -> str | None:
    name = fmap_json_name.lower()
    has_fmri = "acq-fmri" in name
    has_dwi = "acq-dwi" in name
    if has_fmri and not has_dwi:
        return "bold"
    if has_dwi and not has_fmri:
        return "dwi"
    return None


def _to_subject_relative_path(rel_path: Path) -> str | None:
    parts = list(rel_path.parts)
    for index, token in enumerate(parts):
        if token.startswith("sub-"):
            if index + 1 >= len(parts):
                return None
            return Path(*parts[index + 1 :]).as_posix()
    return None


def _normalize_intendedfor_values(value: Any, subject: str) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = [item for item in value if isinstance(item, str)]
    else:
        candidates = []

    normalized: list[str] = []
    subject_prefix = f"{subject}/"
    for candidate in candidates:
        path_value = candidate.replace("\\", "/").lstrip("/")
        if path_value.startswith(subject_prefix):
            path_value = path_value[len(subject_prefix) :]
        if path_value and path_value not in normalized:
            normalized.append(path_value)

    return normalized


def _populate_fmap_intendedfor(target_dir: Path, intendedfor_modality_override: str | None = None) -> int:
    intendedfor_candidates = _collect_intendedfor_candidates(target_dir)
    if not intendedfor_candidates:
        return 0

    updated = 0
    for json_path in sorted(target_dir.rglob("*.json")):
        rel_path = json_path.relative_to(target_dir)
        if "fmap" not in rel_path.parts:
            continue

        subject = _extract_bids_entity(rel_path, "sub-")
        if subject is None:
            continue

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue

        discovered = _matching_intendedfor_entries(
            rel_path,
            intendedfor_candidates,
            intendedfor_modality_override=intendedfor_modality_override,
        )
        if not discovered:
            continue

        existing = _normalize_intendedfor_values(payload.get("IntendedFor"), subject)
        merged = [*existing]
        for entry in discovered:
            if entry not in merged:
                merged.append(entry)

        if merged == existing:
            continue

        payload["IntendedFor"] = merged
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        updated += 1

    return updated


def _format_metric(value: float) -> str:
    return f"{value:.1f}"


def _coerce_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _is_imaging_file(path: Path) -> bool:
    return path.name.endswith(".nii.gz") or path.suffix.lower() == ".nii"


def _sidecar_json_path(image_path: Path) -> Path:
    if image_path.name.endswith(".nii.gz"):
        return image_path.with_name(image_path.name[: -len(".nii.gz")] + ".json")
    return image_path.with_suffix(".json")


def _bids_stem(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[: -len(".nii.gz")]
    if path.suffix:
        return path.name[: -len(path.suffix)]
    return path.name


def _read_numeric_vector(path: Path) -> list[float]:
    if not path.exists():
        return []

    text = _read_sidecar_text(path)
    if not text:
        return []

    parsed: list[float] = []
    for token in text.replace("\n", " ").split():
        value = _coerce_float(token)
        if value is None:
            continue
        parsed.append(value)
    return parsed


def _read_bvec_columns(path: Path) -> list[tuple[float, float, float]]:
    if not path.exists():
        return []

    text = _read_sidecar_text(path)
    if not text:
        return []

    rows: list[list[float]] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        row: list[float] = []
        for token in parts:
            value = _coerce_float(token)
            row.append(0.0 if value is None else value)
        rows.append(row)

    if len(rows) < 3:
        return []

    x, y, z = rows[0], rows[1], rows[2]
    width = min(len(x), len(y), len(z))
    return [(x[i], y[i], z[i]) for i in range(width)]


def _read_sidecar_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""

    if not raw:
        return ""

    # Some datasets ship gzipped payloads with plain .bval/.bvec extensions.
    if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return ""

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _count_diffusion_directions(
    bvals: list[float],
    bvec_columns: list[tuple[float, float, float]],
) -> int:
    if bvals:
        n = len(bvals)
        if bvec_columns:
            n = min(n, len(bvec_columns))
        count = 0
        for index in range(n):
            if bvals[index] <= 0:
                continue
            if bvec_columns:
                x, y, z = bvec_columns[index]
                if x == 0 and y == 0 and z == 0:
                    continue
            count += 1
        return count

    count = 0
    for x, y, z in bvec_columns:
        if x == 0 and y == 0 and z == 0:
            continue
        count += 1
    return count


def _extract_modality(rel_path: Path) -> str:
    for token in rel_path.parts:
        if token in IMAGING_MODALITY_PARTS:
            return token
    return ""


def _extract_nifti_voxel_size(image: nib.spatialimages.SpatialImage) -> str:
    zooms = image.header.get_zooms()
    xyz = zooms[:3]
    if len(xyz) < 3:
        return ""
    return ",".join(_format_metric(float(value)) for value in xyz)


def _load_sidecar_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _is_t1w_lesion_space(lesion_space: str | None) -> bool:
    return bool(lesion_space and lesion_space.strip().lower() == "t1w")


def _is_t1w_scan(rel_path: Path) -> bool:
    name = rel_path.name
    return (name.endswith("_T1w.nii.gz") or name.endswith("_T1w.nii")) and "anat" in rel_path.parts


def _find_matching_t1w_scan(target_dir: Path, lesion_rel_path: Path) -> Path | None:
    subject = _extract_bids_entity(lesion_rel_path, "sub-")
    if subject is None:
        return None
    session = _extract_bids_entity(lesion_rel_path, "ses-")

    candidates: list[Path] = []
    for candidate in sorted(target_dir.rglob("*.nii*")):
        rel_path = candidate.relative_to(target_dir)
        if "derivatives" in rel_path.parts or "lesion" in rel_path.name.lower():
            continue
        if not _is_t1w_scan(rel_path):
            continue
        if _extract_bids_entity(rel_path, "sub-") != subject:
            continue
        candidate_session = _extract_bids_entity(rel_path, "ses-")
        if session is not None and candidate_session != session:
            continue
        candidates.append(candidate)

    return candidates[0] if candidates else None


def _needs_resample(moving_img: nib.spatialimages.SpatialImage, reference_img: nib.spatialimages.SpatialImage) -> bool:
    if moving_img.shape[:3] != reference_img.shape[:3]:
        return True
    return not np.allclose(moving_img.affine, reference_img.affine, atol=1e-4)


def _resample_lesion_to_t1w(lesion_path: Path, t1w_path: Path) -> bool:
    try:
        lesion_img = nib.load(str(lesion_path))
        t1w_img = nib.load(str(t1w_path))
    except Exception:
        return False

    if not _needs_resample(lesion_img, t1w_img):
        return False

    resampled = resample_from_to(lesion_img, t1w_img, order=0)
    # Keep lesion masks binary after nearest-neighbor resampling.
    mask_data = (np.asarray(resampled.dataobj) > 0).astype(np.uint8)
    output = nib.Nifti1Image(mask_data, t1w_img.affine, header=t1w_img.header.copy())
    output.set_qform(t1w_img.affine, code=1)
    output.set_sform(t1w_img.affine, code=1)
    nib.save(output, str(lesion_path))
    return True


def _nifti_stem(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[: -len(".nii.gz")]
    if path.suffix.lower() == ".nii":
        return path.stem
    return path.name


def _load_axial_volume(path: Path) -> np.ndarray | None:
    try:
        image = nib.load(str(path))
        data = np.asarray(image.dataobj)
    except Exception:
        return None

    if data.ndim < 3:
        return None
    if data.ndim > 3:
        data = data[..., data.shape[3] // 2]
    return np.asarray(data, dtype=np.float32)


FIXED_FIGURE_SIZE_INCHES = (18.0, 3.0)
FIXED_FIGURE_DPI = 100


def _axial_slice_indices(n_slices: int, count: int = 6) -> list[int]:
    if n_slices <= 0:
        return []
    if count <= 1:
        return [max(0, n_slices // 2)]
    return [int(round(value)) for value in np.linspace(0, n_slices - 1, num=count)]


def _volume_to_montage_uint8(volume: np.ndarray, indices: list[int], rows: int = 2, cols: int = 3) -> np.ndarray:
    if not indices:
        raise ValueError("indices cannot be empty")

    normalized = _normalize_volume_to_uint8(volume)
    first_index = max(0, min(indices[0], normalized.shape[2] - 1))
    first_tile = np.rot90(normalized[:, :, first_index])
    tile_height, tile_width = first_tile.shape
    montage = np.zeros((rows * tile_height, cols * tile_width), dtype=np.uint8)

    for panel_index in range(rows * cols):
        row = panel_index // cols
        col = panel_index % cols
        if panel_index < len(indices):
            z_index = max(0, min(indices[panel_index], normalized.shape[2] - 1))
            tile = np.rot90(normalized[:, :, z_index])
            montage[
                row * tile_height : (row + 1) * tile_height,
                col * tile_width : (col + 1) * tile_width,
            ] = tile

    return montage


def _save_axial_slice_png(image_path: Path, output_png: Path) -> bool:
    try:
        from nilearn import image as nilearn_image
        from nilearn import plotting
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise RuntimeError("Figure export requires nilearn and matplotlib to be installed") from exc

    try:
        image = nib.load(str(image_path))
    except Exception:
        return False

    if len(image.shape) > 3:
        image = nilearn_image.index_img(image, image.shape[3] // 2)

    output_png.parent.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(figsize=FIXED_FIGURE_SIZE_INCHES, dpi=FIXED_FIGURE_DPI)
    display = plotting.plot_anat(
        image,
        figure=figure,
        display_mode="z",
        cut_coords=6,
        annotate=False,
        draw_cross=False,
        black_bg=True,
    )
    display.savefig(str(output_png))
    display.close()
    plt.close(figure)
    return True


def _save_t1w_lesion_overlay_png(t1w_path: Path, lesion_path: Path, output_png: Path) -> bool:
    try:
        from nilearn import plotting
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise RuntimeError("Figure export requires nilearn and matplotlib to be installed") from exc

    try:
        base_image = nib.load(str(t1w_path))
        lesion_image = nib.load(str(lesion_path))
    except Exception:
        return False

    if base_image.shape[:3] != lesion_image.shape[:3]:
        return False

    output_png.parent.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(figsize=FIXED_FIGURE_SIZE_INCHES, dpi=FIXED_FIGURE_DPI)
    display = plotting.plot_anat(
        base_image,
        figure=figure,
        display_mode="z",
        cut_coords=6,
        annotate=False,
        draw_cross=False,
        black_bg=True,
    )
    display.add_contours(lesion_image, levels=[0.5], colors=["r"], linewidths=1.2)
    display.savefig(str(output_png))
    display.close()
    plt.close(figure)
    return True


def _is_subject_directory_name(name: str) -> bool:
    if name.startswith("sub-"):
        return True
    return SUBJECT_ID_WITH_PREFIX_PATTERN.fullmatch(name) is not None


def _is_subject_root_file(rel_path: Path) -> bool:
    return len(rel_path.parts) == 2 and _is_subject_directory_name(rel_path.parts[0])


def _cleanup_illegal_subject_subfolders(target_dir: Path) -> int:
    removed = 0
    for subject_path in sorted(target_dir.iterdir()):
        if not subject_path.is_dir() or not _is_subject_directory_name(subject_path.name):
            continue

        for illegal_name in ILLEGAL_SUBJECT_SUBFOLDERS:
            illegal_path = subject_path / illegal_name
            if not illegal_path.exists():
                continue

            has_files = illegal_path.is_file() or any(path.is_file() for path in illegal_path.rglob("*"))
            if has_files:
                rel_path = illegal_path.relative_to(target_dir).as_posix()
                warnings.warn(f"Removing illegal subject sub-folder with files: {rel_path}")

            _remove_path(illegal_path)
            removed += 1

    return removed


def _set_tree_read_only(root_dir: Path) -> int:
    changed = 0
    for path in sorted(root_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            continue
        mode = 0o555 if path.is_dir() else 0o444
        os.chmod(path, mode)
        changed += 1

    if not root_dir.is_symlink():
        os.chmod(root_dir, 0o555)
        changed += 1

    return changed


def _is_path_in_subject_tree(rel_path: Path) -> bool:
    return len(rel_path.parts) > 1 and _is_subject_directory_name(rel_path.parts[0])


def _has_matching_imaging_sidecar(rel_path: Path, source_dir: Path) -> bool:
    if rel_path.suffix.lower() != ".json":
        return True
    stem = rel_path.name[: -len(".json")]
    sibling_dir = source_dir / rel_path.parent
    return (sibling_dir / f"{stem}.nii.gz").exists() or (sibling_dir / f"{stem}.nii").exists()


_NUMERIC_COMMA_PATTERN = re.compile(r"^[+-]?\d+,\d+(?:[eE][+-]?\d+)?$")


def _normalize_participants_numeric_value(value: str) -> str:
    text = value.strip()
    if not text or "," not in text:
        return value
    if not _NUMERIC_COMMA_PATTERN.fullmatch(text):
        return value
    return text.replace(",", ".")


def _find_matching_native_scan(
    target_dir: Path,
    lesion_rel_path: Path,
    lesion_space: str,
) -> Path | None:
    normalized_space = lesion_space.strip().lower()
    for candidate in _find_matching_native_scans(target_dir, lesion_rel_path):
        rel_path = candidate.relative_to(target_dir)
        space_label = _native_space_label_for_scan(rel_path)
        if space_label is None:
            continue
        if space_label.lower() == normalized_space:
            return candidate
    return None


def _native_space_label_for_scan(rel_path: Path) -> str | None:
    if _is_t1w_scan(rel_path):
        return "T1w"

    name_lower = rel_path.name.lower()
    if "anat" in rel_path.parts and "flair" in name_lower and name_lower.endswith((".nii.gz", ".nii")):
        return "FLAIR"
    if "dwi" in rel_path.parts and name_lower.endswith(("_dwi.nii.gz", "_dwi.nii")):
        return "dwi"
    return None


def _find_matching_native_scans(target_dir: Path, lesion_rel_path: Path) -> list[Path]:
    subject = _extract_bids_entity(lesion_rel_path, "sub-")
    if subject is None:
        return []
    session = _extract_bids_entity(lesion_rel_path, "ses-")

    candidates: list[Path] = []
    for candidate in sorted(target_dir.rglob("*.nii*")):
        rel_path = candidate.relative_to(target_dir)
        if "derivatives" in rel_path.parts or "lesion" in rel_path.name.lower():
            continue
        if _extract_bids_entity(rel_path, "sub-") != subject:
            continue
        candidate_session = _extract_bids_entity(rel_path, "ses-")
        if session is not None and candidate_session != session:
            continue
        if _native_space_label_for_scan(rel_path) is None:
            continue
        candidates.append(candidate)

    return candidates


def _lesion_resample_destination_relative_path(
    lesion_rel_path: Path,
    reference_rel_path: Path,
    space_label: str,
) -> Path:
    subject = _extract_subject_label(lesion_rel_path)
    if subject is None:
        raise ValueError(f"Could not infer subject ID for lesion file: {lesion_rel_path}")

    suffix = _path_suffix(lesion_rel_path)
    reference_desc = _safe_descriptor_token(_nifti_stem(reference_rel_path))
    if "mni" not in space_label.lower():
        filename = f"{subject}_space-{space_label}_desc-{reference_desc}_lesion_roi{suffix}"
        return Path(subject) / "anat" / filename

    filename = f"{subject}_space-{space_label}_desc-{reference_desc}_label-lesion_mask{suffix}"
    return Path("derivatives") / "manual_masks" / subject / "anat" / filename


def _resample_lesion_to_reference(lesion_path: Path, reference_path: Path, output_path: Path) -> bool:
    try:
        lesion_img = nib.load(str(lesion_path))
        reference_img = nib.load(str(reference_path))
    except Exception as exc:
        raise ValueError(f"Failed to read lesion/reference images for resampling: {lesion_path}") from exc

    target = (reference_img.shape[:3], reference_img.affine)
    needs_resample = _needs_resample(lesion_img, reference_img)
    if needs_resample:
        resampled = resample_from_to(lesion_img, target, order=0)
        mask_data = (np.asarray(resampled.dataobj) > 0).astype(np.uint8)
    else:
        mask_data = (np.asarray(lesion_img.dataobj) > 0).astype(np.uint8)

    header = reference_img.header.copy()
    header.set_data_shape(mask_data.shape)
    output = nib.Nifti1Image(mask_data, reference_img.affine, header=header)
    output.set_qform(reference_img.affine, code=1)
    output.set_sform(reference_img.affine, code=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(output, str(output_path))
    return needs_resample


def _validate_lesion_native_space_geometry(lesion_path: Path, reference_path: Path, lesion_space: str) -> None:
    try:
        lesion_img = nib.load(str(lesion_path))
        reference_img = nib.load(str(reference_path))
    except Exception as exc:
        raise ValueError(f"Failed to read lesion/reference images for native-space check: {lesion_path}") from exc

    lesion_zooms = tuple(float(value) for value in lesion_img.header.get_zooms()[:3])
    reference_zooms = tuple(float(value) for value in reference_img.header.get_zooms()[:3])
    if len(lesion_zooms) < 3 or len(reference_zooms) < 3 or not np.allclose(lesion_zooms, reference_zooms, atol=1e-4):
        raise ValueError(
            f"Lesion voxel size does not match {lesion_space} scan voxel size: "
            f"{lesion_path.name} ({lesion_zooms}) vs {reference_path.name} ({reference_zooms})"
        )

    lesion_axcodes = nib.aff2axcodes(lesion_img.affine)
    reference_axcodes = nib.aff2axcodes(reference_img.affine)
    if lesion_axcodes != reference_axcodes:
        raise ValueError(
            f"Lesion orientation does not match {lesion_space} scan orientation: "
            f"{lesion_path.name} ({lesion_axcodes}) vs {reference_path.name} ({reference_axcodes})"
        )


def _normalize_slice_to_uint8(slice_data: np.ndarray) -> np.ndarray:
    finite_values = slice_data[np.isfinite(slice_data)]
    if not finite_values.size:
        return np.zeros(slice_data.shape, dtype=np.uint8)

    vmin = float(np.percentile(finite_values, 1))
    vmax = float(np.percentile(finite_values, 99))
    if vmax <= vmin:
        vmax = vmin + 1.0

    scaled = (slice_data - vmin) / (vmax - vmin)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)


def _normalize_volume_to_uint8(volume: np.ndarray) -> np.ndarray:
    finite_values = volume[np.isfinite(volume)]
    if not finite_values.size:
        return np.zeros(volume.shape, dtype=np.uint8)

    vmin = float(np.percentile(finite_values, 1))
    vmax = float(np.percentile(finite_values, 99))
    if vmax <= vmin:
        vmax = vmin + 1.0

    scaled = (volume - vmin) / (vmax - vmin)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)


def _write_png_rgb(path: Path, rgb: np.ndarray) -> None:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected an HxWx3 uint8 array for PNG export")
    if rgb.dtype != np.uint8:
        rgb = rgb.astype(np.uint8)

    height, width, _ = rgb.shape

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    raw_rows = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))
    png_payload = zlib.compress(raw_rows, level=9)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    content = signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", png_payload) + _chunk(b"IEND", b"")
    path.write_bytes(content)


def _write_scan_figures(
    target_dir: Path,
    figure_dir: Path,
    overlay_pairs: list[tuple[Path, Path]],
) -> tuple[int, int]:
    scan_figures = 0
    overlay_figures = 0

    for image_path in sorted(target_dir.rglob("*.nii*")):
        rel_path = image_path.relative_to(target_dir)
        if "derivatives" in rel_path.parts or "lesion" in rel_path.name.lower():
            continue
        output_png = figure_dir / rel_path.parent / f"{_nifti_stem(rel_path)}_axial.png"
        if _save_axial_slice_png(image_path, output_png):
            scan_figures += 1

    for t1w_path, lesion_path in overlay_pairs:
        lesion_rel = lesion_path.relative_to(target_dir)
        output_png = figure_dir / lesion_rel.parent / f"{_nifti_stem(lesion_rel)}_overlay.png"
        if _save_t1w_lesion_overlay_png(t1w_path, lesion_path, output_png):
            overlay_figures += 1

    return scan_figures, overlay_figures


def _subject_from_path(path: Path) -> str | None:
    for token in path.parts:
        if token.startswith("sub-"):
            return token
    match = re.search(r"(sub-[A-Za-z0-9]+)", path.name)
    if match:
        return match.group(1)
    return None


def _write_subject_figure_html_pages(figure_dir: Path) -> int:
    grouped: dict[str, list[Path]] = {}
    for png_path in sorted(figure_dir.rglob("*.png")):
        rel_path = png_path.relative_to(figure_dir)
        subject = _subject_from_path(rel_path)
        if subject is None:
            continue
        grouped.setdefault(subject, []).append(rel_path)

    written = 0
    for subject, figures in grouped.items():
        html_lines = [
            "<!doctype html>",
            "<html lang=\"en\">",
            "<head>",
            "  <meta charset=\"utf-8\">",
            f"  <title>{subject} figures</title>",
            "  <style>",
            "    body { font-family: Arial, sans-serif; margin: 24px; }",
            "    .fig { margin-bottom: 24px; }",
            "    img { max-width: 100%; border: 1px solid #ddd; }",
            "    h1, h2 { margin: 0 0 12px; }",
            "  </style>",
            "</head>",
            "<body>",
            f"  <h1>{subject}</h1>",
        ]

        for rel_path in figures:
            rel_posix = rel_path.as_posix()
            html_lines.extend(
                [
                    "  <div class=\"fig\">",
                    f"    <h2>{rel_posix}</h2>",
                    f"    <img src=\"{rel_posix}\" alt=\"{rel_posix}\">",
                    "  </div>",
                ]
            )

        html_lines.extend(["</body>", "</html>"])
        (figure_dir / f"{subject}.html").write_text("\n".join(html_lines) + "\n", encoding="utf-8")
        written += 1

    return written


def _write_acquisitions_bids_tsv(target_dir: Path) -> int:
    filepaths: list[Path] = []
    for image_path in sorted(target_dir.rglob("*")):
        if not image_path.is_file() or not _is_imaging_file(image_path):
            continue
        rel_path = image_path.relative_to(target_dir)
        name_lower = rel_path.name.lower()
        if "derivatives" in rel_path.parts and "lesion" not in name_lower:
            continue
        if _extract_bids_entity(rel_path, "sub-") is None:
            continue
        filepaths.append(image_path)

    fields = [
        "participant_id",
        "session_id",
        "modality",
        "acquisition_type",
        "scan_path",
        "time_repetition",
        "total_length_minutes",
        "manufacturer",
        "machine",
        "tesla_field",
        "echo_time",
        "flip_angle",
        "head_coil",
        "resolution_x",
        "resolution_y",
        "resolution_z",
        "acquisition_plan",
        "vol_num",
        "bvecs_num",
        "bval",
    ]
    rows: list[dict[str, str]] = []

    for image_path in filepaths:
        rel_path = image_path.relative_to(target_dir)
        subject = _extract_bids_entity(rel_path, "sub-") or ""
        session = _extract_bids_entity(rel_path, "ses-") or ""
        modality = _extract_modality(rel_path)
        sidecar_payload = _load_sidecar_metadata(_sidecar_json_path(image_path))

        try:
            image = nib.load(str(image_path))
        except Exception:
            continue
            
        zooms = image.header.get_zooms()
        res_x = _format_metric(zooms[0]) if len(zooms) > 0 else ""
        res_y = _format_metric(zooms[1]) if len(zooms) > 1 else ""
        res_z = _format_metric(zooms[2]) if len(zooms) > 2 else ""

        dmp_type = ""
        path_str = rel_path.as_posix()
        name_lower = rel_path.name.lower()
        if "lesion" in name_lower:
            dmp_type = "lesion"
        elif "rest" in name_lower:
            dmp_type = "fMRI_rest"
        elif "/fmap/" in f"/{path_str}":
            dmp_type = "SE"
        elif "t1w" in name_lower:
            if "ce-gadolinium" in name_lower:
                dmp_type = "T1w_wca"
            else:
                dmp_type = "T1w"
        elif "t2w" in name_lower:
            dmp_type = "T2w"
        elif "flair" in name_lower:
            dmp_type = "Flair"
        elif "/dwi/" in f"/{path_str}" or "dwi" in name_lower:
            dmp_type = "dMRI"
        elif "perf" in name_lower or "/perf/" in f"/{path_str}":
            dmp_type = "perf"
        elif "swi" in name_lower:
            dmp_type = "SWI"

        row = {
            "participant_id": subject,
            "session_id": session,
            "modality": modality,
            "acquisition_type": dmp_type,
            "scan_path": rel_path.as_posix(),
            "time_repetition": "",
            "total_length_minutes": "",
            "manufacturer": str(sidecar_payload.get("Manufacturer", "")),
            "machine": str(sidecar_payload.get("ManufacturersModelName", "")),
            "tesla_field": "",
            "echo_time": str(sidecar_payload.get("EchoTime", "")),
            "flip_angle": str(sidecar_payload.get("FlipAngle", "")),
            "head_coil": str(sidecar_payload.get("ReceiveCoilName", "")),
            "resolution_x": res_x,
            "resolution_y": res_y,
            "resolution_z": res_z,
            "acquisition_plan": "",
            "vol_num": "",
            "bvecs_num": "",
            "bval": "",
        }

        axcodes = nib.aff2axcodes(image.affine)
        if len(axcodes) >= 3:
            z_ax = axcodes[2]
            if z_ax in ('I', 'S'):
                row["acquisition_plan"] = "Axial"
            elif z_ax in ('L', 'R'):
                row["acquisition_plan"] = "Sagittal"
            elif z_ax in ('A', 'P'):
                row["acquisition_plan"] = "Coronal"

        tesla_value = _coerce_float(sidecar_payload.get("MagneticFieldStrength"))
        if tesla_value is not None:
            row["tesla_field"] = _format_metric(tesla_value)

        tr = _coerce_float(sidecar_payload.get("RepetitionTime"))
        if tr is None:
            if len(zooms) > 3:
                tr = _coerce_float(zooms[3])
        if tr is not None:
            row["time_repetition"] = _format_metric(tr)

        shape = image.shape
        n_volumes = int(shape[3]) if len(shape) > 3 else 1
        row["vol_num"] = str(n_volumes)

        if modality == "func" and tr is not None and n_volumes > 0:
            total_minutes = (tr * n_volumes) / 60.0
            row["total_length_minutes"] = _format_metric(total_minutes)
            
        stem = _bids_stem(image_path)
        bvals = _read_numeric_vector(image_path.with_name(f"{stem}.bval"))
        if bvals:
            unique_values = sorted({int(round(value)) for value in bvals})
            row["bval"] = ",".join(str(v) for v in unique_values)

        bvec_columns = _read_bvec_columns(image_path.with_name(f"{stem}.bvec"))
        if bvec_columns is not None:
            row["bvecs_num"] = str(len(bvec_columns))

        rows.append(row)

    out_path = target_dir / "acquisitions.tsv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


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
    intendedfor_modality_override: str | None = None,
    lesion_space: str | None = None,
    lesion_source_subdir: str | None = None,
    lesion_pattern: str | None = None,
    lesion_resample: bool = False,
    lesion_configs: list[dict[str, Any]] | None = None,
    lesion_split: bool = False,
    lesion_split_labels: dict[Any, Any] | list[tuple[list[int], str]] | list[tuple[tuple[int, ...], str]] | None = None,
    lesion_split_combined_desc: str | None = None,
    lesion_split_primary_desc: str | None = None,
    figure_dir: Path | None = None,
    fmap_fmri_patterns: list[str] | None = None,
    fmap_dwi_patterns: list[str] | None = None,
    make_target_read_only: bool = False,
) -> dict[str, int]:
    source_dir = source_dir.expanduser().resolve()
    target_dir = target_dir.expanduser().resolve()
    resolved_figure_dir = figure_dir.expanduser().resolve() if figure_dir is not None else None

    missing_json_fields = missing_json_fields or {}
    json_fields_conv = json_fields_conv or DEFAULT_JSON_FIELDS_CONVERSION
    substitutions = substitutions or []
    skip_source_patterns = skip_source_patterns or []
    fmap_fmri_patterns = fmap_fmri_patterns or []
    fmap_dwi_patterns = fmap_dwi_patterns or []
    if intendedfor_modality_override not in (None, "bold", "dwi"):
        raise ValueError("intendedfor_modality_override must be one of: None, 'bold', 'dwi'")

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source directory does not exist: {source_dir}")

    resolved_lesion_configs = _resolve_lesion_configs(
        lesion_configs=lesion_configs,
        lesion_space=lesion_space,
        lesion_source_subdir=lesion_source_subdir,
        lesion_pattern=lesion_pattern,
        lesion_resample=lesion_resample,
        lesion_split=lesion_split,
        lesion_split_labels=lesion_split_labels,
        lesion_split_combined_desc=lesion_split_combined_desc,
        lesion_split_primary_desc=lesion_split_primary_desc,
    )

    detected_lesion_paths = set(_find_lesion_files(source_dir))
    if resolved_lesion_configs:
        for src_path in source_dir.rglob("*"):
            if not src_path.is_file():
                continue
            rel_path = src_path.relative_to(source_dir)
            for config in resolved_lesion_configs:
                if _is_lesion_related_file(
                    rel_path,
                    lesion_source_subdir=config.source_subdir,
                    lesion_pattern=config.pattern,
                ):
                    detected_lesion_paths.add(rel_path)
                    break
    lesion_relative_paths = sorted(detected_lesion_paths)
    if lesion_relative_paths and not resolved_lesion_configs:
        raise ValueError("Lesion files detected in source_dir: please specify --lesion-space")

    lesion_config_by_relative_path: dict[Path, LesionConfig] = {}
    lesion_config_index_by_relative_path: dict[Path, int] = {}
    for rel_path in lesion_relative_paths:
        matches = [
            (index, config)
            for index, config in enumerate(resolved_lesion_configs)
            if _is_lesion_related_file(
                rel_path,
                lesion_source_subdir=config.source_subdir,
                lesion_pattern=config.pattern,
            )
        ]
        if not matches:
            if len(resolved_lesion_configs) == 1:
                continue
            raise ValueError(f"Lesion file does not match any lesion config: {rel_path}")
        if len(matches) > 1:
            raise ValueError(f"Lesion file matches multiple lesion configs: {rel_path}")
        match_index, match_config = matches[0]
        lesion_config_by_relative_path[rel_path] = match_config
        lesion_config_index_by_relative_path[rel_path] = match_index

    lesion_count_by_config_subject: dict[tuple[int, str], int] = {}
    for rel_path, config_index in lesion_config_index_by_relative_path.items():
        subject = _extract_subject_label(rel_path)
        if subject is None:
            continue
        key = (config_index, subject)
        lesion_count_by_config_subject[key] = lesion_count_by_config_subject.get(key, 0) + 1

    multiple_lesion_subjects = _subjects_with_multiple_lesions(lesion_relative_paths)
    if (
        multiple_lesion_subjects
        and len(resolved_lesion_configs) == 1
        and not (resolved_lesion_configs[0].source_subdir or resolved_lesion_configs[0].pattern)
    ):
        raise ValueError(
            "Multiple lesion files detected for at least one subject. "
            "Specify --lesion-source-subdir or --lesion-pattern."
        )

    if target_dir.exists():
        # Safety guard: never delete source or a parent/child relationship by mistake.
        if target_dir == source_dir or source_dir.is_relative_to(target_dir) or target_dir.is_relative_to(source_dir):
            raise ValueError("Refusing to remove target directory because source/target paths overlap")
        _remove_path(target_dir)

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
        "intendedfor_updated": 0,
        "acquisitions_bids_rows": 0,
        "lesions_resampled": 0,
        "lesion_resample_outputs": 0,
        "adc_files_relocated": 0,
        "scan_figures": 0,
        "overlay_figures": 0,
        "subject_html_pages": 0,
        "fmap_files_reclassified": 0,
        "illegal_subject_subfolders_removed": 0,
        "lesion_split_outputs": 0,
        "read_only_paths": 0,
    }

    emitted_paths: set[Path] = set()
    copied_lesion_targets: list[tuple[Path, str, bool]] = []

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
        final_rel_path = transformed_rel_path
        if final_rel_path.name == "acquisitions.tsv":
            final_rel_path = final_rel_path.with_name("acquisitions_dmp.tsv")
        lesion_config = lesion_config_by_relative_path.get(rel_path) if src_path.is_file() else None
        if src_path.is_file() and lesion_config is not None:
            lesion_subject = _extract_subject_label(transformed_rel_path) or _extract_subject_label(rel_path)
            config_index = lesion_config_index_by_relative_path.get(rel_path)
            multiple_for_subject = bool(
                lesion_subject
                and config_index is not None
                and lesion_count_by_config_subject.get((config_index, lesion_subject), 0) > 1
            )

            if lesion_config.split and _is_nifti_path(rel_path):
                split_outputs = _split_integer_lesion_mask(
                    source_path=src_path,
                    source_rel_path=rel_path,
                    transformed_rel_path=transformed_rel_path,
                    lesion_space=lesion_config.space,
                    split_labels=lesion_config.split_labels or {},
                    combined_desc=lesion_config.combined_desc,
                    multiple_for_subject=multiple_for_subject,
                )

                primary_desc = lesion_config.primary_desc
                if lesion_config.space.strip().lower() == "t1w":
                    if not primary_desc:
                        raise ValueError(
                            "When using split lesions in T1w space, specify a primary desc label "
                            "(lesion_split_primary_desc or lesion_config primary_desc)."
                        )

                written_paths: list[tuple[Path, bool]] = []
                for split_desc, mask_data, source_image in split_outputs:
                    output_rel_paths: list[tuple[Path, bool]] = []
                    if lesion_config.space.strip().lower() == "t1w" and split_desc == primary_desc:
                        anat_rel = _lesion_destination_relative_path(
                            source_rel_path=rel_path,
                            transformed_rel_path=transformed_rel_path,
                            lesion_space=lesion_config.space,
                            multiple_for_subject=multiple_for_subject,
                            desc_label=split_desc,
                        )
                        derivatives_rel = _lesion_destination_relative_path(
                            source_rel_path=rel_path,
                            transformed_rel_path=transformed_rel_path,
                            lesion_space=lesion_config.space,
                            multiple_for_subject=multiple_for_subject,
                            desc_label=split_desc,
                            force_derivatives=True,
                        )
                        output_rel_paths.extend([(anat_rel, True), (derivatives_rel, True)])
                    elif lesion_config.space.strip().lower() == "t1w":
                        derivatives_rel = _lesion_destination_relative_path(
                            source_rel_path=rel_path,
                            transformed_rel_path=transformed_rel_path,
                            lesion_space=lesion_config.space,
                            multiple_for_subject=multiple_for_subject,
                            desc_label=split_desc,
                            force_derivatives=True,
                        )
                        output_rel_paths.append((derivatives_rel, True))
                    else:
                        output_rel_paths.append(
                            (
                                _lesion_destination_relative_path(
                                    source_rel_path=rel_path,
                                    transformed_rel_path=transformed_rel_path,
                                    lesion_space=lesion_config.space,
                                    multiple_for_subject=multiple_for_subject,
                                    desc_label=split_desc,
                                ),
                                True,
                            )
                        )

                    for split_rel_path, track_for_postproc in output_rel_paths:
                        split_dst_path = target_dir / split_rel_path
                        if split_dst_path in emitted_paths:
                            raise FileExistsError(f"Multiple source files map to the same target path: {split_dst_path}")
                        emitted_paths.add(split_dst_path)

                        if split_dst_path.exists() or split_dst_path.is_symlink():
                            if not overwrite:
                                raise FileExistsError(f"Path already exists in target: {split_dst_path}")
                            _remove_path(split_dst_path)

                        _save_binary_mask_like(source_image, mask_data, split_dst_path)
                        written_paths.append((split_rel_path, track_for_postproc))

                for split_rel_path, track_for_postproc in written_paths:
                    if track_for_postproc:
                        copied_lesion_targets.append((split_rel_path, lesion_config.space, lesion_config.resample))
                stats["lesion_split_outputs"] += len(written_paths)
                continue

            if lesion_config.split and rel_path.suffix.lower() == ".json":
                stats["skipped_source_files"] += 1
                continue

            final_rel_path = _lesion_destination_relative_path(
                source_rel_path=rel_path,
                transformed_rel_path=transformed_rel_path,
                lesion_space=lesion_config.space,
                multiple_for_subject=multiple_for_subject,
            )
            copied_lesion_targets.append((final_rel_path, lesion_config.space, lesion_config.resample))
        elif src_path.is_file() and _is_adc_dwi_file(rel_path):
            final_rel_path = _clinical_dwi_destination_relative_path(transformed_rel_path)
            stats["adc_files_relocated"] += 1
        elif src_path.is_file():
            reclassified_fmap = _fmap_reclassified_relative_path(
                source_rel_path=rel_path,
                transformed_rel_path=transformed_rel_path,
                fmap_fmri_patterns=fmap_fmri_patterns,
                fmap_dwi_patterns=fmap_dwi_patterns,
            )
            if reclassified_fmap is not None:
                final_rel_path = reclassified_fmap
                stats["fmap_files_reclassified"] += 1

        dst_path = target_dir / final_rel_path

        if final_rel_path != rel_path:
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

        if src_path.is_file() and _is_subject_root_file(rel_path):
            stats["skipped_source_files"] += 1
            continue

        if src_path.is_file() and _is_path_in_subject_tree(rel_path) and rel_path.suffix.lower() == ".tsv":
            stats["skipped_source_files"] += 1
            continue

        if src_path.is_file() and _is_path_in_subject_tree(rel_path) and rel_path.suffix.lower() == ".json":
            if not _has_matching_imaging_sidecar(rel_path, source_dir):
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
                relative_paths = [rel_path.as_posix(), transformed_rel_path.as_posix()]
                defaults = _matching_missing_fields(relative_paths[0], missing_json_fields)
                defaults.update(_matching_missing_fields(relative_paths[1], missing_json_fields))
                defaults.update(_matching_range_missing_fields(relative_paths, missing_json_fields))
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
        normalize_numeric_columns=True,
    ):
        stats["participants_normalized"] += 1

    acquisitions_target = target_dir / "acquisitions_dmp.tsv"
    if acquisitions_target.exists() and _normalize_tsv_participant_id(
        acquisitions_target,
        collapse_subject_id=collapse_subject_id,
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
            normalize_numeric_columns=True,
        ):
            stats["participants_normalized"] += 1
        if acquisitions_target.exists() and _normalize_tsv_participant_id(
            acquisitions_target,
            collapse_subject_id=collapse_subject_id,
        ):
            stats["acquisitions_normalized"] += 1

    if _ensure_bidsignore(target_dir, DEFAULT_BIDSIGNORE_PATTERNS):
        stats["bidsignore_updated"] += 1

    if _sync_participants_json_with_tsv(target_dir):
        stats["participants_json_updated"] += 1

    stats["illegal_subject_subfolders_removed"] += _cleanup_illegal_subject_subfolders(target_dir)

    overlay_pairs: list[tuple[Path, Path]] = []
    for lesion_rel_path, lesion_target_space, lesion_target_resample in copied_lesion_targets:
        if not lesion_rel_path.name.endswith((".nii.gz", ".nii")):
            continue
        lesion_path = target_dir / lesion_rel_path
        normalized_space = lesion_target_space.strip().lower()

        if normalized_space == "t1w":
            t1w_path = _find_matching_t1w_scan(target_dir, lesion_rel_path)
            if t1w_path is not None:
                overlay_pairs.append((t1w_path, lesion_path))
                if not lesion_target_resample and _resample_lesion_to_t1w(lesion_path, t1w_path):
                    stats["lesions_resampled"] += 1

        if normalized_space in {"flair", "dwi"} and not lesion_target_resample:
            native_scan = _find_matching_native_scan(target_dir, lesion_rel_path, lesion_target_space)
            if native_scan is None:
                raise ValueError(
                    f"Could not find matching {lesion_target_space} scan for lesion native-space check: {lesion_rel_path}"
                )
            _validate_lesion_native_space_geometry(lesion_path, native_scan, lesion_target_space)

        if lesion_target_resample and normalized_space in {"t1w", "flair", "dwi"}:
            native_scan = _find_matching_native_scan(target_dir, lesion_rel_path, lesion_target_space)
            if native_scan is None:
                raise ValueError(
                    f"Could not find matching {lesion_target_space} scan for lesion resampling: {lesion_rel_path}"
                )
            if _resample_lesion_to_reference(lesion_path, native_scan, lesion_path):
                stats["lesions_resampled"] += 1
            stats["lesion_resample_outputs"] += 1

    stats["intendedfor_updated"] += _populate_fmap_intendedfor(
        target_dir,
        intendedfor_modality_override=intendedfor_modality_override,
    )
    stats["acquisitions_bids_rows"] = _write_acquisitions_bids_tsv(target_dir)

    if resolved_figure_dir is not None:
        scan_figures, overlay_figures = _write_scan_figures(
            target_dir=target_dir,
            figure_dir=resolved_figure_dir,
            overlay_pairs=overlay_pairs,
        )
        stats["scan_figures"] = scan_figures
        stats["overlay_figures"] = overlay_figures
        stats["subject_html_pages"] = _write_subject_figure_html_pages(resolved_figure_dir)

    if make_target_read_only:
        stats["read_only_paths"] = _set_tree_read_only(target_dir)

    return stats

