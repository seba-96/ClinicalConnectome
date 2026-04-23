# ClinicalConnectome

`ClinicalConnectome` includes a BIDS conversion tool that transforms a source dataset from EBRAINS 2.4 Data Management Plan (DMP) to a BIDS-ready dataset while applying:

- filename/path substitutions
- subject ID normalization (`sub-` prefix + optional ID collapsing)
- JSON key renaming and default JSON field injection
- automatic `IntendedFor` population in `fmap/*.json` from discovered BOLD/DWI NIfTI files
- lesion mask relocation with explicit `--lesion-space` handling
- bundled copy of top-level BIDS metadata files (overridable)
- original DMP participant IDs preserved in `participant_id_dmp` column

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

By default, the converter validates generated output with `bids-validator-deno`
after conversion:

```bash
bids-converter \
  /path/to/source \
  /path/to/output
```

This runs `bids-validator-deno /path/to/output` and prints validator output
directly to the terminal unchanged. The converter JSON output contains a compact
`bids_validation` entry with command and return code. A non-zero validator exit
code causes the CLI to exit with the same code.

To skip validation for a run:

```bash
bids-converter \
  /path/to/source \
  /path/to/output \
  --no-validate-bids
```

To inspect full CLI help:

```bash
bids-converter --help
```

Missing JSON defaults also support subject numeric ranges. Example custom
`missing_json_fields.py`:

```python
file_to_json_fields = {
    "0001-0100": {
        "Flair": {
            "TaskName": "hello",
        }
    }
}
```

This injects fields only for files matching `Flair` in subjects with numeric
ID suffixes in the inclusive range `0001-0100`.

For fmap sidecars, `IntendedFor` auto-discovery is modality aware by filename:

- if fmap JSON name contains `acq-fmri`, only BOLD targets are added
- if fmap JSON name contains `acq-dwi`, only DWI targets are added
- otherwise, both BOLD and DWI targets are considered

You can force one modality globally for a conversion run:

```bash
bids-converter /path/to/source /path/to/output --intendedfor-fmri-only
bids-converter /path/to/source /path/to/output --intendedfor-dwi-only
```

If neither flag is set, the filename-based heuristic above is used.

If lesion files are present in the source directory, you must provide:

```bash
bids-converter /path/to/source /path/to/output --lesion-space T1w
```

Lesion destination rules:

- `--lesion-space T1w`: place masks in `sub-*/anat/` as `sub-XXX_lesion_roi.nii.gz`
- other spaces (for example `MNI152NLin2009cAsym`): place masks in
  `derivatives/manual_masks/sub-XXX/anat/` as
  `sub-XXX_space-MNI152NLin2009cAsym_label-lesion_mask.nii.gz`

If multiple lesion files are detected for the same subject, specify one selector
to disambiguate which files should be treated as lesion masks:

```bash
bids-converter /path/to/source /path/to/output --lesion-space MNI152NLin2009cAsym --lesion-source-subdir manual_masks
bids-converter /path/to/source /path/to/output --lesion-space MNI152NLin2009cAsym --lesion-pattern '*lesion*'
```

`--lesion-resample` now resamples each selected lesion to the sequence declared in
its lesion space (for native spaces like `T1w`, `FLAIR`, `dwi`) and updates the
same output mask file.

To split integer-valued lesions (for example `1=core`, `2=edema`) into one binary
mask per label:

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-space FLAIR \
  --lesion-pattern '*space-FLAIR_les*' \
  --lesion-split \
  --lesion-split-label 1:core \
  --lesion-split-label 2:edema \
  --lesion-split-combined-desc edemacore
```

You can group multiple labels under the same desc (for example labels `1,2,3`
as `core`, excluding label `4` by not mapping it):

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-space T1w \
  --lesion-pattern '*lesion*' \
  --lesion-split \
  --lesion-split-label 1,2,3:core \
  --lesion-split-primary-desc core
```

When split masks are used with `--lesion-space T1w`, exactly one split mask
(`--lesion-split-primary-desc`) is kept in `sub-*/anat/`. All split masks are
written in `derivatives/manual_masks/`, and the primary anat mask is duplicated
there as well.

For datasets with multiple lesion sources that need different options, use
repeatable `--lesion-config` JSON objects (each can define `pattern`, `space`,
`resample`, `split`, `split_labels`, `combined_desc`):

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-config '{"pattern":"*space-FLAIR_les*","space":"FLAIR","resample":true}' \
  --lesion-config '{"pattern":"*space-MNI*","space":"MNI152NLin2009cAsym","split":true,"split_labels":{"1":"core","2":"edema"},"combined_desc":"edemacore"}'
```

By default the output tree is made read-only at the end of conversion; disable
this behavior with `--no-target-read-only`.

If the target directory already exists, it is removed before conversion starts.

## Participant ID provenance

When IDs are normalized, the original DMP ID is preserved in an additional
`participant_id_dmp` column in both `participants.tsv` and `acquisitions.tsv`.

## Project layout

- `src/bids_converter/cli.py`: command-line entrypoint and argument parsing
- `src/bids_converter/converter.py`: conversion logic
- `src/bids_converter/resources/`: bundled reference BIDS files and missing JSON defaults
- `main.py`: compatibility launcher (`python main.py ...`)
- `tests/`: minimal regression tests for CLI and mapping output

