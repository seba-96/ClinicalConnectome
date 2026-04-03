# ClinicalConnectome / bids_converter

`bids_converter` converts a source dataset tree into a BIDS-ready directory while applying:

- filename/path substitutions
- subject ID normalization (`sub-` prefix + optional ID collapsing)
- JSON key renaming and default JSON field injection
- bundled copy of top-level BIDS metadata files (overridable)
- participant ID mapping TSV export when IDs are collapsed

The repository already includes:

- a bundled reference BIDS top-level template in `src/bids_converter/resources/reference_bids/`
- a bundled default missing-fields module in `src/bids_converter/resources/missing_json_fields.py`

## Clone and install

```bash
git clone https://github.com/<your-org>/ClinicalConnectome.git
cd ClinicalConnectome
python -m pip install -e .
```

## Quick start

```bash
bids-converter \
  --source-dir /path/to/source \
  --target-dir /path/to/output
```

By default, the converter uses bundled reference files and bundled missing JSON defaults.
You can override either one:

```bash
bids-converter \
  --source-dir /path/to/source \
  --target-dir /path/to/output \
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
bids-converter --source-dir ... --target-dir ... --no-participant-id-map
```


## Development

Run tests:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Project layout

- `src/bids_converter/cli.py`: command-line entrypoint and argument parsing
- `src/bids_converter/converter.py`: conversion logic
- `src/bids_converter/resources/`: bundled reference BIDS files and missing JSON defaults
- `main.py`: compatibility launcher (`python main.py ...`)
- `tests/`: minimal regression tests for CLI and mapping output

