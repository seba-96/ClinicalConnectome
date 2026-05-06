# ClinicalConnectome

A CLI utility designed to transform neuroimaging data organized according to the EBRAINS 2.4 Data Management Plan into fully compliant BIDS (Brain Imaging Data Structure) folder structures.

## Where and how to run

This package can be run **locally** on your computer terminal, or on a **PHI. 
If you are running it on PHI:
1. Open a new Desktop in PHI.
2. Open a `'MULTI'` terminal.

Remember to keep an original copy of you DMP compliant dataset and place the new BIDS compliant dataset in PHI under the directory /Clinical_connectome_bids/<center>/<dataset_id>
When encountering issues with conversion you can run the bids-converter separately on different sub-groups of the dataset and eventually merge (ie copy) the resulting BIDS compliant sub-datasets together.
Note that in the latter case acquisitions.tsv files must be merged.

### Clone and install

Run the following commands in your terminal to clone the repository and set up the virtual environment. Python 3.10+ and Git are required. 

```bash
git clone https://github.com/seba-96/ClinicalConnectome.git
cd ClinicalConnectome
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

In case of PowerShell, use `.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`.

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

To inspect full CLI help:

```bash
bids-converter --help
```

### Lesion Rules and Redirection

If lesion files are present in the source directory, you must provide `--lesion-space`.

```bash
bids-converter /path/to/source /path/to/output --lesion-space T1w
```

**Lesion destination rules:**
- `--lesion-space T1w`: place masks in `sub-*/anat/` as `sub-XXX_space-T1w_lesion_roi.nii.gz`
- `--lesion-space MNI152NLin2009cAsym` (or any other MNI version): place masks in `derivatives/manual_masks/sub-XXX/anat/`. Even if the source file is located in an `anat/` source subfolder, specifying MNI bounds it to derivatives automatically.
- Other native spaces (e.g., `FLAIR`, `dwi`) place masks in `sub-*/anat/` like T1w.

If you have multiple lesion files in different spaces, specify one `--lesion-config` per pattern. Example with one T1w mask and one MNI mask:

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-config '{"pattern":"*space-T1w*_lesion*", "space":"T1w"}' \
  --lesion-config '{"pattern":"*space-MNI*", "space":"MNI152NLin2009cAsym"}'
```


`--lesion-resample` resamples a mask over to the matching specified space. Defaults to `False`. 

### Splitting multi-label discrete lesion masks

If you supply a mask where `1=core`, `2=edema`, etc., you can split it into binary structures. You can also specify overlaps logic recursively. For example, if you want regions `1, 2, and 3` pooled together to mean `core`:

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-space T1w \
  --lesion-pattern '*lesion*' \
  --lesion-split \
  --lesion-split-label 1,2,3:core \
  --lesion-split-label 4:edema \
  --lesion-split-combined-desc edemacore
```

When split masks are built for non-MNI spaces (including `--lesion-space T1w`), all split outputs are kept in `sub-XXX/anat/`.

For fully customized settings across different source lesion types in a massive folder tree, specify configurations recursively via JSON:

```bash
bids-converter /path/to/source /path/to/output \
  --lesion-config '{"pattern":"*space-FLAIR_les*","space":"FLAIR","resample":true}' \
  --lesion-config '{"pattern":"*space-MNI*","space":"MNI152NLin2009cAsym","split":true,"split_labels":{"1,2,3":"core","4":"edema"},"combined_desc":"edemacore"}'
```

### Field maps

If you have field maps always specify the --fmap-dwi-pattern and/or --fmap-fmri-pattern.

For fmap sidecars, `IntendedFor` auto-discovery is modality aware by filename:
- if fmap JSON name contains `acq-fmri`, only BOLD targets are added
- if fmap JSON name contains `acq-dwi`, only DWI targets are added

You can force one modality globally for a conversion run:

```bash
bids-converter /path/to/source /path/to/output --fmap-fmri-pattern 'fMRI_rest_pa' --intendedfor-fmri-only
bids-converter /path/to/source /path/to/output --fmap-dwi-pattern 'dMRI_pa' --intendedfor-dwi-only
```


### Add missing JSON fields into an existing BIDS dataset

If you have an **already converted BIDS dataset** and simply want to retroactively add missing JSON fields flagged by bids-validator, you can bypass `source_dir` requirements by providing `--inject-missing-json-only`:

```bash
bids-converter /path/to/existing_bids_output \
  --inject-missing-json-only \
  --missing-json-fields '{"0001-0100": {"*func*": {"TaskName": "rest"}}}''
```
The above command skips conversion and directly targets `*.json` sidecars in your existing `/path/to/existing_bids_output` dataset.

You can also restrict JSON injection to a given list of subjects (using `--inject-subjects sub-01 sub-02` or `--inject-subjects all`), and you can choose to remove fields using `--drop-json-fields Field1 Field2` dynamically during the injection.


## Participant ID provenance

When IDs are normalized, the original DMP ID is preserved in an additional `participant_id_dmp` column in both `participants.tsv` and `acquisitions.tsv`.

