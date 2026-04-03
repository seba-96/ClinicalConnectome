from __future__ import annotations

import importlib
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_SPACE = "MNI152NLin2009cAsym"
DEFAULT_TEMPLATE_RESOLUTION = 1
DEFAULT_LESION_MASK_PATTERNS = [
	"{t1_base}_label-lesion_mask.nii.gz",
	"{t1_base}_label-lesion_mask.nii",
	"{t1_base}_desc-lesion_mask.nii.gz",
	"{t1_base}_desc-lesion_mask.nii",
]


@dataclass
class RegistrationConfig:
	bids_root: Path
	output_root: Path
	subjects: list[str] | None = None
	template_space: str = DEFAULT_TEMPLATE_SPACE
	template_resolution: int = DEFAULT_TEMPLATE_RESOLUTION
	transform_type: str = "SyN"
	lesion_mask_patterns: list[str] | None = None
	run_n4_bias_correction: bool = True
	run_brain_extraction: bool = True
	bet_frac: float | None = None
	use_lesion_mask_for_registration: bool = True
	register_lesion_masks: bool = True
	fast: bool = False
	ants_threads: int | None = None
	keep_temp: bool = False
	overwrite: bool = False
	fail_fast: bool = False


def _strip_nii_suffix(name: str) -> str:
	if name.endswith(".nii.gz"):
		return name[: -len(".nii.gz")]
	if name.endswith(".nii"):
		return name[: -len(".nii")]
	return Path(name).stem


def _normalize_subject_filter(subjects: list[str] | None) -> set[str] | None:
	if not subjects:
		return None
	normalized: set[str] = set()
	for subject in subjects:
		token = subject.strip()
		if not token:
			continue
		if not token.startswith("sub-"):
			token = f"sub-{token}"
		normalized.add(token)
	return normalized or None


def find_subject_t1w_images(bids_root: Path, subjects: list[str] | None = None) -> list[Path]:
	bids_root = bids_root.expanduser().resolve()
	if not bids_root.is_dir():
		raise NotADirectoryError(f"BIDS root does not exist: {bids_root}")

	subject_filter = _normalize_subject_filter(subjects)
	t1w_images: list[Path] = []

	for subject_dir in sorted(path for path in bids_root.glob("sub-*") if path.is_dir()):
		if subject_filter is not None and subject_dir.name not in subject_filter:
			continue

		for anat_dir in sorted(subject_dir.rglob("anat")):
			if not anat_dir.is_dir():
				continue
			for pattern in ("*_T1w.nii.gz", "*_T1w.nii"):
				for t1w_path in sorted(anat_dir.glob(pattern)):
					t1w_images.append(t1w_path)

	return t1w_images


def find_lesion_mask_for_t1w(
	t1w_path: Path,
	mask_patterns: list[str] | None = None,
) -> Path | None:
	patterns = mask_patterns or DEFAULT_LESION_MASK_PATTERNS
	t1_stem = _strip_nii_suffix(t1w_path.name)
	if not t1_stem.endswith("_T1w"):
		return None

	t1_base = t1_stem[: -len("_T1w")]
	for pattern in patterns:
		candidate = t1w_path.parent / pattern.format(t1_base=t1_base)
		if candidate.exists():
			return candidate
	return None


def resolve_mni_template(template_space: str, template_resolution: int) -> Path:
	try:
		from templateflow.api import get as templateflow_get
	except ImportError as exc:
		raise ImportError(
			"templateflow is required for registration. Install project dependencies with `pip install -e .`."
		) from exc

	template = templateflow_get(
		template_space,
		resolution=template_resolution,
		suffix="T1w",
		extension=".nii.gz",
	)
	if isinstance(template, (list, tuple)):
		if not template:
			raise FileNotFoundError(
				f"TemplateFlow did not return a template for {template_space} at resolution {template_resolution}"
			)
		template = template[0]

	template_path = Path(str(template))
	if not template_path.exists():
		raise FileNotFoundError(f"Template file not found: {template_path}")
	return template_path


def _build_moving_mask(moving_image_path: Path, lesion_mask_path: Path, output_mask_path: Path) -> Path:
	try:
		nib = importlib.import_module("nibabel")
		np = importlib.import_module("numpy")
	except ImportError as exc:
		raise ImportError(
			"nibabel and numpy are required for lesion masking. Install project dependencies with `pip install -e .`."
		) from exc

	moving = nib.load(str(moving_image_path))
	lesion = nib.load(str(lesion_mask_path))

	moving_data = moving.get_fdata(dtype=np.float32)
	lesion_data = lesion.get_fdata(dtype=np.float32)

	support_mask = moving_data != 0
	lesion_binary = lesion_data > 0
	valid_mask = np.logical_and(support_mask, np.logical_not(lesion_binary)).astype(np.uint8)

	nib.save(nib.Nifti1Image(valid_mask, moving.affine, moving.header), str(output_mask_path))
	return output_mask_path


def _configure_registration_interface(registration: Any, transform_type: str, fast: bool) -> None:
	registration.inputs.dimension = 3
	registration.inputs.float = True
	registration.inputs.initial_moving_transform_com = True
	registration.inputs.winsorize_lower_quantile = 0.005
	registration.inputs.winsorize_upper_quantile = 0.995

	transform_key = transform_type.strip().lower()
	if transform_key == "syn":
		registration.inputs.transforms = ["Rigid", "Affine", "SyN"]
		registration.inputs.transform_parameters = [(0.1,), (0.1,), (0.1, 3.0, 0.0)]
		registration.inputs.metric = ["MI", "MI", "CC"]
		registration.inputs.metric_weight = [1.0, 1.0, 1.0]
		registration.inputs.radius_or_number_of_bins = [32, 32, 4]
		registration.inputs.sampling_strategy = ["Regular", "Regular", None]
		registration.inputs.sampling_percentage = [0.25, 0.25, None]
		if fast:
			registration.inputs.number_of_iterations = [
				[300, 150, 60],
				[300, 150, 60],
				[60, 30, 15],
			]
			registration.inputs.shrink_factors = [[4, 2, 1], [4, 2, 1], [4, 2, 1]]
			registration.inputs.smoothing_sigmas = [[2, 1, 0], [2, 1, 0], [1, 0, 0]]
		else:
			registration.inputs.number_of_iterations = [
				[1000, 500, 250, 100],
				[1000, 500, 250, 100],
				[100, 70, 50, 20],
			]
			registration.inputs.shrink_factors = [[8, 4, 2, 1], [8, 4, 2, 1], [8, 4, 2, 1]]
			registration.inputs.smoothing_sigmas = [[3, 2, 1, 0], [3, 2, 1, 0], [2, 1, 0, 0]]
		registration.inputs.sigma_units = ["vox", "vox", "vox"]
		registration.inputs.use_histogram_matching = [True, True, True]
		registration.inputs.convergence_threshold = [1e-6, 1e-6, 1e-6]
		registration.inputs.convergence_window_size = [10, 10, 10]
		return

	if transform_key == "rigid":
		registration.inputs.transforms = ["Rigid"]
	elif transform_key == "affine":
		registration.inputs.transforms = ["Affine"]
	else:
		registration.inputs.transforms = [transform_type]

	registration.inputs.transform_parameters = [(0.1,)]
	registration.inputs.metric = ["MI"]
	registration.inputs.metric_weight = [1.0]
	registration.inputs.radius_or_number_of_bins = [32]
	registration.inputs.sampling_strategy = ["Regular"]
	registration.inputs.sampling_percentage = [0.25]
	registration.inputs.number_of_iterations = [[300, 150, 60]] if fast else [[1000, 500, 250, 100]]
	registration.inputs.shrink_factors = [[4, 2, 1]] if fast else [[8, 4, 2, 1]]
	registration.inputs.smoothing_sigmas = [[2, 1, 0]] if fast else [[3, 2, 1, 0]]
	registration.inputs.sigma_units = ["vox"]
	registration.inputs.use_histogram_matching = [True]
	registration.inputs.convergence_threshold = [1e-6]
	registration.inputs.convergence_window_size = [10]


def _run_ants_registration(
	*,
	t1w_path: Path,
	template_path: Path,
	output_anat_dir: Path,
	output_prefix: str,
	transform_type: str,
	lesion_mask_path: Path | None,
	run_n4_bias_correction: bool,
	run_brain_extraction: bool,
	bet_frac: float | None,
	use_lesion_mask_for_registration: bool,
	register_lesion_masks: bool,
	fast: bool,
	ants_threads: int | None,
	keep_temp: bool,
	overwrite: bool,
) -> dict[str, Any]:
	def _collect_synquick_forward_transforms(prefix: Path) -> list[str]:
		prefix_str = str(prefix)
		ordered: list[Path] = []
		warp = Path(f"{prefix_str}1Warp.nii.gz")
		affine = Path(f"{prefix_str}0GenericAffine.mat")
		if warp.exists():
			ordered.append(warp)
		if affine.exists():
			ordered.append(affine)
		if ordered:
			return [str(path.resolve()) for path in ordered]

		# Fallback for uncommon output naming.
		fallback = sorted(prefix.parent.glob(f"{prefix.name}*"))
		return [str(path.resolve()) for path in fallback if path.suffix in {".mat", ".h5", ".gz"}]

	try:
		from nipype.interfaces.ants import ApplyTransforms, Registration, RegistrationSynQuick
	except ImportError as exc:
		raise ImportError(
			"nipype is required for registration. Install project dependencies with `pip install -e .`."
		) from exc

	output_anat_dir.mkdir(parents=True, exist_ok=True)
	warped_t1w_path = output_anat_dir / f"{output_prefix}.nii.gz"
	if warped_t1w_path.exists() and not overwrite:
		return {
			"status": "skipped_exists",
			"warped_t1w": str(warped_t1w_path),
			"transforms": [],
			"warped_lesion_mask": None,
		}

	tmp_dir = Path(tempfile.mkdtemp(prefix="bids_reg_"))
	keep_tmp_dir_path: str | None = str(tmp_dir) if keep_temp else None
	try:
		start_time = time.perf_counter()
		if ants_threads is not None and ants_threads > 0:
			os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(ants_threads)
			logger.debug("Using %s ANTs thread(s) for %s", ants_threads, t1w_path.name)

		moving_path = t1w_path
		if run_n4_bias_correction:
			from nipype.interfaces.ants import N4BiasFieldCorrection

			n4_output = tmp_dir / "n4_corrected.nii.gz"
			n4 = N4BiasFieldCorrection()
			if ants_threads is not None and ants_threads > 0:
				n4.inputs.num_threads = ants_threads
			n4.inputs.dimension = 3
			n4.inputs.input_image = str(moving_path)
			n4.inputs.output_image = str(n4_output)
			n4.run()
			moving_path = n4_output
			logger.debug("N4 bias correction completed for %s", t1w_path.name)

		if run_brain_extraction:
			from nipype.interfaces.fsl import BET

			bet_output = tmp_dir / "bet_brain.nii.gz"
			bet = BET()
			bet.inputs.in_file = str(moving_path)
			bet.inputs.out_file = str(bet_output)
			bet.inputs.mask = True
			bet.inputs.robust = True
			if bet_frac is not None:
				bet.inputs.frac = bet_frac
			bet.run()
			moving_path = bet_output
			logger.debug("BET brain extraction completed for %s", t1w_path.name)

		transform_key = transform_type.strip().lower()
		forward_transforms: list[str] = []
		resolved_transforms: list[str] = []

		if transform_key in {"registrationsynquick", "synquick", "antsregistrationsynquick"}:
			if lesion_mask_path is not None and use_lesion_mask_for_registration:
				logger.warning(
					"RegistrationSynQuick does not apply moving lesion masks; continuing without mask for %s",
					t1w_path.name,
				)
			synquick_prefix = output_anat_dir / f"{output_prefix}_"
			synquick = RegistrationSynQuick()
			if ants_threads is not None and ants_threads > 0 and hasattr(synquick.inputs, "num_threads"):
				synquick.inputs.num_threads = ants_threads
			synquick.inputs.dimension = 3
			synquick.inputs.fixed_image = str(template_path)
			synquick.inputs.moving_image = str(moving_path)
			synquick.inputs.output_prefix = str(synquick_prefix)
			synquick.inputs.transform_type = "s"
			synquick.run()

			synquick_warped = Path(f"{synquick_prefix}Warped.nii.gz")
			if not synquick_warped.exists():
				raise FileNotFoundError(f"RegistrationSynQuick warped output not found: {synquick_warped}")
			copy2(synquick_warped, warped_t1w_path)
			resolved_transforms = _collect_synquick_forward_transforms(synquick_prefix)
			forward_transforms = list(resolved_transforms)
		else:
			registration = Registration()
			if ants_threads is not None and ants_threads > 0:
				registration.inputs.num_threads = ants_threads
			registration.inputs.fixed_image = str(template_path)
			registration.inputs.moving_image = str(moving_path)
			registration.inputs.output_transform_prefix = str(output_anat_dir / f"{output_prefix}_")
			registration.inputs.output_warped_image = str(warped_t1w_path)
			_configure_registration_interface(registration, transform_type, fast=fast)

			if lesion_mask_path is not None and use_lesion_mask_for_registration:
				moving_mask_path = tmp_dir / "moving_mask.nii.gz"
				generated_mask = _build_moving_mask(moving_path, lesion_mask_path, moving_mask_path)
				if hasattr(registration.inputs, "moving_image_masks"):
					registration.inputs.moving_image_masks = [str(generated_mask)]
				elif hasattr(registration.inputs, "moving_image_mask"):
					registration.inputs.moving_image_mask = str(generated_mask)

			registration_result = registration.run()
			output_obj = registration_result.outputs
			forward_transforms = list(getattr(output_obj, "forward_transforms", []) or [])
			resolved_transforms = [str(Path(transform).resolve()) for transform in forward_transforms]

		warped_lesion_mask_path: str | None = None
		if lesion_mask_path is not None and register_lesion_masks and forward_transforms:
			lesion_output_path = output_anat_dir / f"{output_prefix}_label-lesion_mask.nii.gz"
			apply = ApplyTransforms()
			if ants_threads is not None and ants_threads > 0:
				apply.inputs.num_threads = ants_threads
			apply.inputs.dimension = 3
			apply.inputs.input_image = str(lesion_mask_path)
			apply.inputs.reference_image = str(template_path)
			apply.inputs.transforms = forward_transforms
			apply.inputs.interpolation = "NearestNeighbor"
			apply.inputs.output_image = str(lesion_output_path)
			apply.run()
			warped_lesion_mask_path = str(lesion_output_path)

		elapsed = time.perf_counter() - start_time
		logger.info("Registered %s in %.1fs", t1w_path.name, elapsed)

		return {
			"status": "ok",
			"warped_t1w": str(warped_t1w_path),
			"transforms": resolved_transforms,
			"warped_lesion_mask": warped_lesion_mask_path,
			"temp_dir": keep_tmp_dir_path,
		}
	finally:
		if keep_temp:
			logger.info("Keeping temp directory for %s at %s", t1w_path.name, tmp_dir)
		else:
			shutil.rmtree(tmp_dir, ignore_errors=True)


def register_dataset(config: RegistrationConfig) -> dict[str, Any]:
	bids_root = config.bids_root.expanduser().resolve()
	output_root = config.output_root.expanduser().resolve()
	output_root.mkdir(parents=True, exist_ok=True)

	logger.info(
		"Starting registration: bids_root=%s output_root=%s fast=%s n4=%s bet=%s bet_frac=%s keep_temp=%s",
		bids_root,
		output_root,
		config.fast,
		config.run_n4_bias_correction,
		config.run_brain_extraction,
		config.bet_frac,
		config.keep_temp,
	)
	template_path = resolve_mni_template(config.template_space, config.template_resolution)
	t1w_images = find_subject_t1w_images(bids_root, config.subjects)
	logger.info("Template=%s | T1w images found=%d", template_path, len(t1w_images))

	stats: dict[str, Any] = {
		"template": str(template_path),
		"processed": 0,
		"registered": 0,
		"skipped": 0,
		"failed": 0,
		"lesion_masks_found": 0,
		"lesion_masks_warped": 0,
		"results": [],
	}

	mask_patterns = config.lesion_mask_patterns or DEFAULT_LESION_MASK_PATTERNS

	for t1w_path in t1w_images:
		stats["processed"] += 1
		logger.debug("Processing %s", t1w_path)
		relative_t1w = t1w_path.relative_to(bids_root)
		output_anat_dir = output_root / relative_t1w.parent

		t1_stem = _strip_nii_suffix(t1w_path.name)
		if not t1_stem.endswith("_T1w"):
			continue

		t1_base = t1_stem[: -len("_T1w")]
		output_prefix = f"{t1_base}_space-{config.template_space}_desc-preproc_T1w"

		lesion_mask_path = find_lesion_mask_for_t1w(t1w_path, mask_patterns)
		if lesion_mask_path is not None:
			stats["lesion_masks_found"] += 1

		try:
			result = _run_ants_registration(
				t1w_path=t1w_path,
				template_path=template_path,
				output_anat_dir=output_anat_dir,
				output_prefix=output_prefix,
				transform_type=config.transform_type,
				lesion_mask_path=lesion_mask_path,
				run_n4_bias_correction=config.run_n4_bias_correction,
				run_brain_extraction=config.run_brain_extraction,
				bet_frac=config.bet_frac,
				use_lesion_mask_for_registration=config.use_lesion_mask_for_registration,
				register_lesion_masks=config.register_lesion_masks,
				fast=config.fast,
				ants_threads=config.ants_threads,
				keep_temp=config.keep_temp,
				overwrite=config.overwrite,
			)
		except Exception as exc:
			logger.exception("Registration failed for %s", t1w_path)
			stats["failed"] += 1
			failure = {
				"status": "error",
				"source_t1w": str(t1w_path),
				"error": str(exc),
			}
			stats["results"].append(failure)
			if config.fail_fast:
				raise
			continue

		result["source_t1w"] = str(t1w_path)
		result["lesion_mask"] = str(lesion_mask_path) if lesion_mask_path else None
		stats["results"].append(result)

		if result["status"] == "ok":
			stats["registered"] += 1
			if result.get("warped_lesion_mask"):
				stats["lesion_masks_warped"] += 1
		elif result["status"] == "skipped_exists":
			logger.info("Skipping existing output for %s", t1w_path.name)
			stats["skipped"] += 1

	logger.info(
		"Finished registration: processed=%d registered=%d skipped=%d failed=%d",
		stats["processed"],
		stats["registered"],
		stats["skipped"],
		stats["failed"],
	)

	return stats

