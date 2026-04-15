from __future__ import annotations

import argparse
import json
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

    parser.set_defaults(copy_source_files=True, collapse_subject_id=True)
    parser.add_argument("source_dir", type=Path, help="Input folder to convert.")
    parser.add_argument("target_dir", type=Path, help="Output BIDS-ready folder.")
    parser.add_argument(
        "--missing-json-fields-file",
        type=Path,
        help=(
            "Optional Python file that defines file_to_json_fields.\n"
            "Supported forms:\n"
            "  {glob: {key: value}}\n"
            "  {'0001-0100': {'Flair': {key: value}}}\n"
            "Matching JSON files receive missing default fields."
        ),
    )
    parser.add_argument(
        "--skip-missing-json-defaults",
        action="store_true",
        help="Skip loading missing JSON field defaults (including bundled defaults).",
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
        "--lesion-space",
        help=(
            "Space of lesion masks found in source data (required when lesion files are present).\n"
            "Use T1w to store masks in sub/anat; any other space stores masks in derivatives/manual_masks/sub-*/anat."
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

    substitutions = [*DEFAULT_FILENAME_SUBSTITUTIONS, *args.substitute_pattern]

    missing_json_fields: dict[str, dict[str, object]] = {}
    if not args.skip_missing_json_defaults:
        missing_fields_path = args.missing_json_fields_file or get_bundled_missing_json_fields_file()
        missing_json_fields = load_missing_json_fields(missing_fields_path)

    reference_root = None
    if not args.skip_copy_top_level:
        reference_root = args.reference_bids_root or get_bundled_reference_bids_root()

    intendedfor_modality_override = None
    if args.intendedfor_fmri_only:
        intendedfor_modality_override = "bold"
    elif args.intendedfor_dwi_only:
        intendedfor_modality_override = "dwi"

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
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()

