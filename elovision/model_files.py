"""Explicit online installation; normal inference never reaches the network."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .config import MODEL_FILE, MODEL_REPO, ModelConfig
from .errors import VisionError


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_manifest(config: ModelConfig, *, verify_hash=True) -> dict:
    try:
        data = json.loads(config.manifest.read_text(encoding="utf-8"))
        if data["repo"] != MODEL_REPO or data["filename"] != MODEL_FILE:
            raise ValueError("Unexpected model identity")
        if len(data["sha256"]) != 64 or not data["revision"]:
            raise ValueError("Incomplete model provenance")
        if not config.checkpoint.is_file():
            raise FileNotFoundError(config.checkpoint)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VisionError(
            "model_missing",
            "Maia 3 79M is not installed. Run install.bat, or "
            "python -m elovision model install, then retry.",
            503,
        ) from exc
    if verify_hash and file_sha256(config.checkpoint) != data["sha256"]:
        raise VisionError(
            "model_checksum",
            "The model checksum does not match. Run "
            "python -m elovision model install --force to replace it.",
            503,
        )
    return data


def install_model(config: ModelConfig, *, force=False) -> dict:
    if not force:
        try:
            return verified_manifest(config)
        except VisionError as exc:
            if exc.code != "model_missing":
                raise
    config.model_dir.mkdir(parents=True, exist_ok=True)
    # Keep all caches writable and together with the model. Respect explicit overrides.
    os.environ.setdefault("HF_HOME", str(config.model_dir / "huggingface"))
    os.environ.setdefault("HF_XET_CACHE", str(config.model_dir / "xet"))
    # The official HTTP transport is simpler for local Windows/proxy installations.
    # TLS and the official LFS checksum remain mandatory with either transport.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import HfApi, hf_hub_download

    try:
        info = HfApi().model_info(MODEL_REPO, files_metadata=True, timeout=20)
        entry = next(item for item in info.siblings if item.rfilename == MODEL_FILE)
        expected = entry.lfs.sha256 if entry.lfs else None
        if not expected:
            raise ValueError("Official LFS checksum is unavailable")
        path = Path(
            hf_hub_download(
                MODEL_REPO,
                MODEL_FILE,
                revision=info.sha,
                cache_dir=str(config.model_dir / "hub"),
                force_download=force,
            )
        )
        if file_sha256(path) != expected:
            raise ValueError("Downloaded weights failed the official LFS SHA-256 check")
        card = info.card_data.to_dict() if info.card_data else {}
        manifest = {
            "repo": MODEL_REPO,
            "filename": MODEL_FILE,
            "revision": info.sha,
            "sha256": expected,
            "license": card.get("license", "see model card"),
        }
        # Replace atomically, preserving any working installation on download failure.
        with tempfile.NamedTemporaryFile(dir=config.model_dir, delete=False) as temp:
            temp_path = Path(temp.name)
            with path.open("rb") as source:
                shutil.copyfileobj(source, temp)
        temp_path.replace(config.checkpoint)
        config.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest
    except Exception as exc:
        raise VisionError(
            "model_download",
            "Could not install the official Maia 3 79M weights. "
            "Check access to huggingface.co and its download hosts. "
            f"Details: {type(exc).__name__}: {str(exc)[:240]}",
            503,
        ) from exc
