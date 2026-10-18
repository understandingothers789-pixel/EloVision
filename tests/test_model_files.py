import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from elovision.config import MODEL_FILE, MODEL_REPO, ModelConfig
from elovision.errors import VisionError
from elovision.model_files import install_model, verified_manifest


def test_checksum_failure_never_loads_changed_weights(tmp_path):
    config = ModelConfig(model_dir=tmp_path)
    config.checkpoint.write_bytes(b"test file, not a model")
    manifest = {
        "repo": MODEL_REPO,
        "filename": MODEL_FILE,
        "revision": "test-revision",
        "sha256": hashlib.sha256(config.checkpoint.read_bytes()).hexdigest(),
    }
    config.manifest.write_text(json.dumps(manifest))
    assert verified_manifest(config) == manifest
    config.checkpoint.write_bytes(b"changed")
    with pytest.raises(VisionError) as error:
        verified_manifest(config)
    assert error.value.code == "model_checksum"


def test_installer_resolves_revision_and_verifies_official_checksum(tmp_path, monkeypatch):
    source = tmp_path / "download.pt"
    source.write_bytes(b"test-only download fixture, not Maia weights")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    info = SimpleNamespace(
        sha="immutable-test-revision",
        siblings=[SimpleNamespace(rfilename=MODEL_FILE, lfs=SimpleNamespace(sha256=digest))],
        card_data=SimpleNamespace(to_dict=lambda: {"license": "test-license"}),
    )
    calls = []

    def download(repo, filename, **kwargs):
        calls.append((repo, filename, kwargs))
        return str(source)

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(
            HfApi=lambda: SimpleNamespace(model_info=lambda *a, **kw: info),
            hf_hub_download=download,
        ),
    )
    config = ModelConfig(model_dir=tmp_path / "installed")
    result = install_model(config)
    assert result["sha256"] == digest
    assert result["license"] == "test-license"
    assert calls[0][2]["revision"] == "immutable-test-revision"
    assert verified_manifest(config) == result
    # Repeating installation uses only the verified local files, even without network.
    install_model(config)
    assert len(calls) == 1
    # An integrity failure during replacement cannot destroy the prior installation.
    source.write_bytes(b"corrupted fixture")
    with pytest.raises(VisionError):
        install_model(config, force=True)
    assert verified_manifest(config) == result
