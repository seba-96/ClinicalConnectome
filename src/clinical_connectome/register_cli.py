from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .registration import DEFAULT_LESION_MASK_PATTERNS, RegistrationConfig, register_dataset


def _bet_frac(value: str) -> float:
    frac = float(value)
    if not (0.0 < frac < 1.0):
        raise argparse.ArgumentTypeError("--bet-frac must be between 0 and 1 (exclusive).")
    return frac


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="register-mni",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Register BIDS T1w images to an MNI template using ANTs.\n"
            "TemplateFlow is used to download and resolve the fixed template."
        ),
        epilog=(
            "Examples:\n"
            "  register-mni /path/to/bids /path/to/derivatives/ants_mni\n"
            "  register-mni /path/to/bids /path/to/derivatives/ants_mni --subject 01 --subject 02\n"
            "  register-mni /path/to/bids /path/to/derivatives/ants_mni --overwrite\n"
        ),
    )

    parser.add_argument("bids_root", type=Path, help="Input BIDS root directory.")
    parser.add_argument("output_root", type=Path, help="Output directory for registered derivatives.")
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        help="Subject label to process (repeatable, with or without sub- prefix).",
    )
    parser.add_argument(
        "--template-space",
        default="MNI152NLin2009cAsym",
        help="TemplateFlow template ID used as registration target.",
    )
    parser.add_argument(
        "--template-resolution",
        type=int,
        default=1,
        help="TemplateFlow template resolution index (default: 1).",
    )
    parser.add_argument(
        "--transform-type",
        default="SyN",
        help=(
            "ANTs transform type passed to nipype.interfaces.ants.Registration "
            "(default: SyN). Use RegistrationSynQuick for a very fast preset."
        ),
    )
    parser.add_argument(
        "--lesion-mask-pattern",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Filename pattern looked up inside each T1w anat directory to find lesion masks.\n"
            "Use {t1_base} placeholder (e.g. {t1_base}_label-lesion_mask.nii.gz)."
        ),
    )
    parser.add_argument(
        "--no-n4-bias-correction",
        action="store_true",
        help="Disable N4 bias field correction before registration (enabled by default).",
    )
    parser.add_argument(
        "--no-brain-extraction",
        action="store_true",
        help="Disable BET brain extraction before registration (enabled by default).",
    )
    parser.add_argument(
        "--bet-frac",
        type=_bet_frac,
        default=None,
        help="Optional BET fractional intensity threshold (0-1). Lower values typically extract a larger brain mask.",
    )
    parser.add_argument(
        "--no-lesion-mask-for-registration",
        action="store_true",
        help="Do not use lesion masks during registration even if found.",
    )
    parser.add_argument(
        "--no-register-lesion-masks",
        action="store_true",
        help="Do not warp lesion masks to template space.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    parser.add_argument("--fail-fast", action="store_true", help="Abort on first failed subject.")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use a faster registration preset with fewer multiresolution levels and iterations.",
    )
    parser.add_argument(
        "--ants-threads",
        type=int,
        default=None,
        help="Set ANTs/ITK thread count per registration (defaults to ANTs runtime behavior).",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep per-subject temporary preprocessing files for debugging.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity for registration progress (default: INFO).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = RegistrationConfig(
        bids_root=args.bids_root,
        output_root=args.output_root,
        subjects=args.subject,
        template_space=args.template_space,
        template_resolution=args.template_resolution,
        transform_type=args.transform_type,
        lesion_mask_patterns=args.lesion_mask_pattern or DEFAULT_LESION_MASK_PATTERNS,
        run_n4_bias_correction=not args.no_n4_bias_correction,
        run_brain_extraction=not args.no_brain_extraction,
        bet_frac=args.bet_frac,
        use_lesion_mask_for_registration=not args.no_lesion_mask_for_registration,
        register_lesion_masks=not args.no_register_lesion_masks,
        fast=args.fast,
        ants_threads=args.ants_threads,
        keep_temp=args.keep_temp,
        overwrite=args.overwrite,
        fail_fast=args.fail_fast,
    )

    result = register_dataset(config)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()

