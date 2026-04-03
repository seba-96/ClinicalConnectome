# ClinicalConnectome

`ClinicalConnectome` includes a BIDS conversion tool that transforms a source dataset from EBRAINS 2.4 Data Management Plan (DMP) to a BIDS-ready dataset while applying:

- filename/path substitutions
- subject ID normalization (`sub-` prefix + optional ID collapsing)
- JSON key renaming and default JSON field injection
- bundled copy of top-level BIDS metadata files (overridable)
- participant ID mapping TSV export when IDs are collapsed

The repository already includes:

- a bundled reference BIDS top-level template in `src/bids_converter/resources/reference_bids/`
- a bundled default missing-fields module in `src/bids_converter/resources/missing_json_fields.py`

## Clone and install

Use a virtual environment to run the app (recommended and expected for this project).

Python 3.10+ is required.

```bash
git clone https://github.com/seba-96/ClinicalConnectome.git
cd ClinicalConnectome
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Quick start

```bash
bids-converter \
  /path/to/source \
  /path/to/output
```

By default, the converter uses bundled reference files and bundled missing JSON defaults.
You can override either one:

```bash
bids-converter \
  /path/to/source \
  /path/to/output \
  --reference-bids-root /path/to/reference_bids \
  --missing-json-fields-file /path/to/missing_json_fields.py
```

To inspect full CLI help:

```bash
bids-converter --help
```

## Participant ID mapping TSV

When `--collapse-subject-id` is enabled (default), the tool writes
`participant_id_map.tsv` inside the target directory with:

- `original_participant_id`
- `bids_participant_id`

Disable this output:

```bash
bids-converter ... ... --no-participant-id-map
```

## T1w to MNI registration
Install the project (includes required dependencies like `nipype`, `templateflow`, `nibabel`, and `numpy`):

```bash
python -m pip install -e .
```

Register all available subject T1w images in a BIDS dataset:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni
```

Run on selected subjects only:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni --subject 01 --subject 02
```

Run a faster (lower-accuracy) preset:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni --fast
```

Run ANTs `RegistrationSynQuick` for a very fast registration path:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni --transform-type RegistrationSynQuick
```

By default, registration runs ANTs N4 bias correction and BET brain extraction
before the nonlinear registration step.

Disable preprocessing steps if needed:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni --no-n4-bias-correction --no-brain-extraction
```

Tune BET aggressiveness when brain extraction is enabled:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni --bet-frac 0.35
```

Temporary preprocessing files (such as `n4_corrected.nii.gz`, `bet_brain.nii.gz`, and
`moving_mask.nii.gz`) are created in the system temporary directory and automatically
removed at the end of each subject run.

To keep those files for debugging, use:

```bash
register-mni /path/to/bids /path/to/derivatives/ants_mni --keep-temp
```

When `--keep-temp` is used, each result entry includes `temp_dir` with the preserved path.

Lesion masks are auto-detected in each `anat` folder using patterns like
`{t1_base}_label-lesion_mask.nii.gz`. If found, they are used to mask registration
and warped to template space with nearest-neighbor interpolation.

Registration is executed via `nipype` ANTs interfaces, so ANTs binaries must be
available on the target system `PATH`.


## Project layout

- `src/bids_converter/cli.py`: command-line entrypoint and argument parsing
- `src/bids_converter/converter.py`: conversion logic
- `src/clinical_connectome/register_cli.py`: registration CLI entrypoint (`register-mni`)
- `src/clinical_connectome/registration.py`: BIDS T1w discovery and ANTs/templateflow registration orchestration
- `src/bids_converter/resources/`: bundled reference BIDS files and missing JSON defaults
- `main.py`: compatibility launcher (`python main.py ...`)
- `tests/`: minimal regression tests for CLI and mapping output

