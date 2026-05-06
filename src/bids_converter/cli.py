from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .converter import (
    DEFAULT_FILENAME_SUBSTITUTIONS,
    DEFAULT_TOPLEVEL_COPY,
    create_bids_ready_tree,
    get_bundled_missing_json_fields_file,
    get_bundled_reference_bids_root,
    load_missing_json_fields,
)


def _parse_substitution_rule(value: str) -> tuple[str, str]:
    if "=>" not in value:
        raise argparse.ArgumentTypeError(
            f"Invalid substitution rule {value!r}. Use PATTERN=>REPLACEMENT."
        )
    pattern, replacement = value.split("=>", 1)
    if not pattern:
        raise argparse.ArgumentTypeError("Substitution pattern cannot be empty.")
    return pattern, replacement


def _parse_lesion_split_label(value: str) -> tuple[list[int], str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError(f"Invalid split label {value!r}. Use LABEL[,LABEL...]:DESC.")
    raw_label, raw_desc = value.split(":", 1)
    labels: list[int] = []
    for token in [part for part in raw_label.replace("-", ",").split(",") if part.strip()]:
        try:
            label = int(token.strip())
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid split label key {token!r}. Use integers > 0.") from exc
        if label <= 0:
            raise argparse.ArgumentTypeError("Split label keys must be integers > 0.")
        labels.append(label)
    if not labels:
        raise argparse.ArgumentTypeError("At least one split label key is required.")
    desc = raw_desc.strip()
    if not desc:
        raise argparse.ArgumentTypeError("Split label description cannot be empty.")
    return labels, desc


def _parse_lesion_config_json(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid lesion config JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("Each --lesion-config must be a JSON object.")
    return payload


def _parse_json_dict(value: str) -> dict[str, Any]:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid JSON: {exc}") from exc


def _run_bids_validator(target_dir: Path) -> dict[str, object]:
    commands = [
        # ["bids-validator", str(target_dir)],
        ["bids-validator-deno", str(target_dir)],
    ]
    last_error: Exception | None = None
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
            )
            return {
                "command": command,
                "returncode": completed.returncode,
            }
        except FileNotFoundError as exc:
            last_error = exc

    raise RuntimeError(
        "Could not run bids-validator or bids-validator-deno. Install the dependency and ensure the executable is on PATH."
    ) from last_error

    return {
        "command": command,
        "returncode": completed.returncode,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bids-converter",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Create a BIDS-ready mirror directory from a source folder.\n"
            "The converter can rename paths, normalize subject IDs, patch JSON keys,\n"
            "and copy/symlink source files with optional top-level metadata from a reference BIDS root."
        ),
        epilog=(
            "Examples:\n"
            "  bids-converter ./input ./output\n"
            "  bids-converter ./input ./output --symlink-source-files\n"
            "  bids-converter ./input ./output \\\n"
            "    --missing-json-fields-file ./missing_json_fields.py\n"
        ),
    )

    parser.set_defaults(copy_source_files=True, collapse_subject_id=True, validate_bids=True)
    parser.add_argument("source_dir", type=Path, nargs="?", help="Input folder to convert (not required if using --inject-missing-json-only).")
    parser.add_argument("target_dir", type=Path, help="Output BIDS-ready folder.")
    parser.add_argument(
        "--inject-missing-json-only",
        action="store_true",
        help="Only inject missing JSON defaults iteratively into an existing BIDS output tree. Skips actual conversion.",
    )
    parser.add_argument(
        "--missing-json-fields-file",
        type=Path,
        help=(
            "Optional JSON file that defines missing default fields.\n"
            "Matches against both source and target paths.\n"
            "Supported forms:\n"
            "  {glob: {key: value}}\n"
            "  {'0001-0100': {'Flair': {key: value}}}"
        ),
    )
    parser.add_argument(
        "--missing-json-fields",
        type=_parse_json_dict,
        help="Optional inline JSON string that defines missing default fields (matches both source and target paths).",
    )
    parser.add_argument(
        "--skip-missing-json-defaults",
        action="store_true",
        help="Skip loading missing JSON field defaults (including bundled defaults).",
    )
    parser.add_argument(
        "--drop-json-fields",
        nargs="+",
        metavar="FIELD",
        help="Remove these JSON fields during --inject-missing-json-only (repeatable fields allowed).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing target files if needed.",
    )
    parser.add_argument(
        "--no-sub-prefix",
        action="store_true",
        help="Disable automatic sub- prefix normalization for subject-like names.",
    )
    parser.add_argument(
        "--clear-substitutions",
        action="store_true",
        help="Discard the default filename substitutions so only custom ones are applied.",
    )
    parser.add_argument(
        "--substitute-pattern",
        action="append",
        type=_parse_substitution_rule,
        default=[],
        metavar="PATTERN=>REPLACEMENT",
        help="Regex replacement applied to each path component (repeatable).",
    )
    parser.add_argument(
        "--reference-bids-root",
        type=Path,
        help="Copy common top-level BIDS files from this directory (defaults to bundled template).",
    )
    parser.add_argument(
        "--skip-copy-top-level",
        action="store_true",
        help="Do not copy top-level metadata files from the reference BIDS root.",
    )
    parser.add_argument(
        "--copy-source-files",
        dest="copy_source_files",
        action="store_true",
        help="Copy source data files (default).",
    )
    parser.add_argument(
        "--symlink-source-files",
        dest="copy_source_files",
        action="store_false",
        help="Create symlinks for source data files instead of copying.",
    )
    parser.add_argument(
        "--collapse-subject-id",
        dest="collapse_subject_id",
        action="store_true",
        help=(
            "Collapse IDs like ST_UNIPD_0001 into STUNIPD0001 (default).\n"
            "Original IDs are kept in participant_id_dmp in participants/acquisitions TSVs."
        ),
    )
    parser.add_argument(
        "--no-collapse-subject-id",
        dest="collapse_subject_id",
        action="store_false",
        help="Keep IDs unchanged (except optional sub- prefix).",
    )
    parser.add_argument(
        "--skip-source-pattern",
        action="append",
        default=[],
        metavar="GLOB",
        help="Skip source files matching this glob on relative path or filename (repeatable).",
    )
    parser.add_argument(
        "--validate-bids",
        dest="validate_bids",
        action="store_true",
        help="Run bids-validator (or bids-validator-deno) against the generated target directory after conversion (default).",
    )
    parser.add_argument(
        "--no-validate-bids",
        dest="validate_bids",
        action="store_false",
        help="Skip bids-validator validation after conversion.",
    )
    parser.add_argument(
        "--lesion-space",
        help=(
            "Space of lesion masks found in source data (required when lesion files are present).\n"
            "Use T1w (or other native spaces) to store masks in sub/anat; MNI spaces store masks in derivatives/manual_masks/sub-*/anat."
        ),
    )
    parser.add_argument(
        "--lesion-resample",
        action="store_true",
        help=(
            "Resample lesions to the sequence in --lesion-space (native spaces only)."
        ),
    )
    parser.add_argument(
        "--lesion-split",
        action="store_true",
        help="Split integer-valued lesion masks into one binary output per label > 0.",
    )
    parser.add_argument(
        "--lesion-split-label",
        action="append",
        type=_parse_lesion_split_label,
        default=[],
        metavar="LABELS:DESC",
        help="Optional label mapping used with --lesion-split (repeatable), e.g. 1,2,3:core 4:edema.",
    )
    parser.add_argument(
        "--lesion-split-combined-desc",
        help="Also write a combined binary lesion mask (>0) with this desc entity, e.g. edemacore.",
    )
    parser.add_argument(
        "--lesion-config",
        action="append",
        type=_parse_lesion_config_json,
        default=[],
        metavar="JSON",
        help=(
            "Repeatable lesion config as JSON object for per-file handling.\n"
            "Example: '{\"pattern\":\"*space-FLAIR_les*\",\"space\":\"FLAIR\",\"resample\":true,"
            "\"split\":true,\"split_labels\":{\"1\":\"core\",\"2\":\"edema\"},\"combined_desc\":\"edemacore\"}'"
        ),
    )
    parser.add_argument(
        "--figure-dir",
        type=Path,
        help=(
            "Optional directory where 6-slice axial montage PNGs of all scans are written.\n"
            "When --lesion-space T1w is used, lesion overlays on T1w are also saved here.\n"
            "A subject-level HTML page embedding all generated figures is created for each subject."
        ),
    )
    parser.add_argument(
        "--no-figure-dir",
        dest="skip_figures",
        action="store_true",
        help="Skip figure generation even if --figure-dir is provided.",
    )
    parser.add_argument(
        "--fmap-fmri-pattern",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Treat matching files currently under func/ as fieldmaps and move them to fmap/\n"
            "while forcing filename entity acq-fmri (repeatable; supports substring or glob)."
        ),
    )
    parser.add_argument(
        "--fmap-dwi-pattern",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Treat matching files currently under dwi/ as fieldmaps and move them to fmap/\n"
            "while forcing filename entity acq-dwi (repeatable; supports substring or glob)."
        ),
    )
    lesion_selector_group = parser.add_mutually_exclusive_group()
    lesion_selector_group.add_argument(
        "--lesion-source-subdir",
        help="Restrict lesion detection to files located in this source subdirectory.",
    )
    lesion_selector_group.add_argument(
        "--lesion-pattern",
        help="Restrict lesion detection to files matching this glob/path pattern (for example '*lesion*').",
    )
    intendedfor_group = parser.add_mutually_exclusive_group()
    intendedfor_group.add_argument(
        "--intendedfor-fmri-only",
        action="store_true",
        help="Force IntendedFor discovery to include only BOLD targets for all fmap sidecars.",
    )
    intendedfor_group.add_argument(
        "--intendedfor-dwi-only",
        action="store_true",
        help="Force IntendedFor discovery to include only DWI targets for all fmap sidecars.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    missing_json_fields: dict[str, dict[str, object]] = {}
    if not args.skip_missing_json_defaults:
        if args.missing_json_fields:
            missing_json_fields = args.missing_json_fields
        else:
            missing_fields_path = args.missing_json_fields_file or get_bundled_missing_json_fields_file()
            missing_json_fields = load_missing_json_fields(missing_fields_path)

    if args.inject_missing_json_only:
        from .converter import inject_missing_json_in_place

        result = inject_missing_json_in_place(
            args.target_dir,
            missing_json_fields,
            drop_json_fields=args.drop_json_fields,
        )

        if args.validate_bids:
            validation_result = _run_bids_validator(args.target_dir)
            result["bids_validation"] = validation_result

        print(json.dumps(result, indent=2, ensure_ascii=True))

        if args.validate_bids and int(result["bids_validation"]["returncode"]) != 0:
            raise SystemExit(int(result["bids_validation"]["returncode"]))
        return

    if not args.source_dir:
        parser.error("source_dir is required unless --inject-missing-json-only is used.")

    substitutions = [] if args.clear_substitutions else [*DEFAULT_FILENAME_SUBSTITUTIONS]
    substitutions.extend(args.substitute_pattern)

    reference_root = None
    if not args.skip_copy_top_level:
        reference_root = args.reference_bids_root or get_bundled_reference_bids_root()

    intendedfor_modality_override = None
    if args.intendedfor_fmri_only:
        intendedfor_modality_override = "bold"
    elif args.intendedfor_dwi_only:
        intendedfor_modality_override = "dwi"

    if args.lesion_config and (args.lesion_space or args.lesion_source_subdir or args.lesion_pattern):
        parser.error("--lesion-config cannot be combined with --lesion-space/--lesion-source-subdir/--lesion-pattern")

    lesion_split_label_recipe = args.lesion_split_label

    resolved_figure_dir = args.figure_dir if not getattr(args, "skip_figures", False) else None

    result = create_bids_ready_tree(
        source_dir=args.source_dir,
        target_dir=args.target_dir,
        missing_json_fields=missing_json_fields,
        overwrite=args.overwrite,
        substitutions=substitutions,
        add_sub_prefix=not args.no_sub_prefix,
        reference_bids_root=reference_root,
        copy_top_level_files=DEFAULT_TOPLEVEL_COPY,
        copy_source_files=args.copy_source_files,
        collapse_subject_id=args.collapse_subject_id,
        skip_source_patterns=args.skip_source_pattern,
        intendedfor_modality_override=intendedfor_modality_override,
        lesion_space=args.lesion_space,
        lesion_source_subdir=args.lesion_source_subdir,
        lesion_pattern=args.lesion_pattern,
        lesion_resample=args.lesion_resample,
        lesion_configs=args.lesion_config,
        lesion_split=args.lesion_split,
        lesion_split_labels=lesion_split_label_recipe,
        lesion_split_combined_desc=args.lesion_split_combined_desc,
        figure_dir=resolved_figure_dir,
        fmap_fmri_patterns=args.fmap_fmri_pattern,
        fmap_dwi_patterns=args.fmap_dwi_pattern,
    )

    if args.validate_bids:
        validation_result = _run_bids_validator(args.target_dir)
        result["bids_validation"] = validation_result

    print(json.dumps(result, indent=2, ensure_ascii=True))

    if args.validate_bids and int(result["bids_validation"]["returncode"]) != 0:
        raise SystemExit(int(result["bids_validation"]["returncode"]))


if __name__ == "__main__":
    main()

