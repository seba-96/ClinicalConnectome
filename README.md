# ClinicalConnectome

A CLI utility designed to transform neuroimaging data organized according to the EBRAINS 2.4 Data Management Plan into fully compliant BIDS (Brain Imaging Data Structure) folder structures.

## Overview

The `bids-converter` tool automates the tedious parts of dataset conversion and curation by applying:

- structural heuristics for filename/path substitutions
- subject ID normalization (`sub-` prefix + optional ID collapsing)
- JSON key renaming and missing default JSON field injection via configs
- automatic `IntendedFor` population in `fmap/*.json` from discovered BOLD/DWI scans
- advanced lesion mask handling with `--lesion-space` routing
- bundled copying of top-level reference BIDS metadata
- data provenance preservation (original DMP participant IDs in `participant_id_dmp` column)
- immediately makes output trees read-only (to stop accidental mutation)
- automatic generation of montage figures via `nilearn` (if requested via `--figure-dir`)
- immediate BIDS compliance validation with `bids-validator-deno`

The repository already includes:

- a bundled reference BIDS top-level template in `src/bids_converter/resources/reference_bids/`
- a bundled default missing-fields JSON configuration in `src/bids_converter/resources/missing_json_fields.json`

## Where and how to run

This package can be run **locally** on your computer terminal, or on a **PHI. 
If you are running it on PHI:
1. Open a new Desktop in PHI.
2. Open a `'MULTI'` terminal.

### Clone and install

Run the following commands in your terminal to clone the repository and set up the virtual environment. Python 3.10+ and Git are required. 

```bash
git clone https://github.com/seba-96/ClinicalConnectome.git
cd ClinicalConnectome
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### Updating the app

To pull the latest changes and update the application via Git, drop into your project directory and run:

```bash
cd ClinicalConnectome
git pull
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
You can pass custom defaults via an external JSON file or inline JSON string directly in the CLI:

```bash
bids-converter \
  /path/to/source \
  /path/to/output \
  --reference-bids-root /path/to/reference_bids \
  --missing-json-fields '{"*FLAIR*": {"TaskName": "hello"}}'
```

If you don't need figure generation (or only want to clear existing default substitutions), you can modify the default behavior using flags:

```bash
bids-converter /path/to/source /path/to/output \
  --no-figure-dir \
  --clear-substitutions \
  --substitute-pattern 'my_old_pattern=>my_new_pattern'
```

By default, the converter validates generated output with `bids-validator-deno` after conversion. It also sets the output destination to read-only (`--target-read-only`).

To skip validation for a run:

```bash
bids-converter /path/to/source /path/to/output --no-validate-bids
```

To inspect full CLI help:

```bash
bids-converter --help
```

### Inject missing JSON fields into an existing tree

If you have an **already converted BIDS dataset** and simply want to retroactively inject missing JSON fields without repeating the entire conversion process, you can bypass `source_dir` requirements by providing `--inject-missing-json-only`:

```bash
bids-converter /path/to/existing_bids_output \
  --inject-missing-json-only \
  --missing-json-fields '{"0001-0100": {"FLAIR": {"TaskName": "rest"}}}'
```

The above command skips conversion and directly targets `*.json` sidecars in your existing `/path/to/existing_bids_output` dataset.

### IntendedFor Auto-Population

For fmap sidecars, `IntendedFor` auto-discovery is modality aware by filename:
- if fmap JSON name contains `acq-fmri`, only BOLD targets are added
- if fmap JSON name contains `acq-dwi`, only DWI targets are added

You can force one modality globally for a conversion run:

```bash
bids-converter /path/to/source /path/to/output --intendedfor-fmri-only
bids-converter /path/to/source /path/to/output --intendedfor-dwi-only
```

### Lesion Rules and Redirection

If lesion files are present in the source directory, you must provide `--lesion-space`.

```bash
bids-converter /path/to/source /path/to/output --lesion-space T1w
```

**Lesion destination rules:**
- `--lesion-space T1w`: place masks in `sub-*/anat/` as `sub-XXX_lesion_roi.nii.gz`
- `--lesion-space MNI152NLin2009cAsym` (or any other space): place masks in `derivatives/manual_masks/sub-XXX/anat/`. Even if the source file is located in an `anat/` source subfolder, specifying MNI bounds it to derivatives automatically.

If multiple lesion files are detected for the same subject, specify one selector:

```bash
bids-converter /path/to/source /path/to/output --lesion-space MNI152NLin2009cAsym --lesion-source-subdir manual_masks
```

`--lesion-resample` safely resamples a mask over to the matching specified space.

### Splitting multi-label discrete lesion masks

If you supply a mask where `1=core`, `2=edema`, etc., you can split it into binary structures. You can also specify overlaps logic recursively. For example, if you want regions `1, 2, and 3` pooled together to mean `core`:

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-space T1w \
  --lesion-pattern '*lesion*' \
  --lesion-split \
  --lesion-split-label 1,2,3:core \
  --lesion-split-label 4:edema \
  --lesion-split-combined-desc edemacore \
  --lesion-split-primary-desc core
```

When split masks are built for `--lesion-space T1w`, exactly one split mask (`--lesion-split-primary-desc core`) places its output directly in `sub-XXX/anat/` while dumping everything else (the `edema` desc, combinations, duplicates of `core`) to `derivatives/manual_masks/`.

For fully customized settings across different source lesion types in a massive folder tree, specify configurations recursively via JSON:

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-config '{"pattern":"*space-FLAIR_les*","space":"FLAIR","resample":true}' \
  --lesion-config '{"pattern":"*space-MNI*","space":"MNI152NLin2009cAsym","split":true,"split_labels":{"1,2,3":"core","4":"edema"},"combined_desc":"edemacore"}'
```

If the target directory already exists, it is structurally replaced (to clear invalid trees), preventing pollution.

## Participant ID provenance

When IDs are normalized, the original DMP ID is preserved in an additional `participant_id_dmp` column in both `participants.tsv` and `acquisitions.tsv`.

## Project layout

- `src/bids_converter/cli.py`: command-line entrypoint and argument parsing
- `src/bids_converter/converter.py`: conversion logic
- `src/bids_converter/resources/`: bundled reference BIDS files and missing JSON defaults
- `main.py`: compatibility launcher (`python main.py ...`)
- `tests/`: comprehensive regression tests checking affine compliance, plots, overlapping mask derivation, etc.

