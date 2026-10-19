"""Exercise Windows orchestration without installing packages or requiring a GPU."""

import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from elovision import windows_runtime as runtime


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "CACHE", tmp_path / ".cache")
    for name in (".venv", ".venv-amd"):
        python = runtime.python_for(name)
        python.parent.mkdir(parents=True)
        python.touch()
    runtime.CACHE.mkdir()
    runtime.write_json(runtime.CACHE / "amd-install.json", {"target": "gfx1201"})
    monkeypatch.setattr(runtime, "windows_adapters", lambda: [
        "AMD Radeon(TM) Graphics", "AMD Radeon RX 9070 XT",
    ])
    monkeypatch.delenv("ELOVISION_DEVICE", raising=False)
    return tmp_path


@pytest.fixture
def nvidia_installation(installation, monkeypatch):
    python = runtime.python_for(".venv-nvidia")
    python.parent.mkdir(parents=True)
    python.touch()
    (runtime.CACHE / "amd-install.json").unlink()
    runtime.write_json(runtime.CACHE / "nvidia-install.json", {"name": "NVIDIA GeForce RTX 5090"})
    monkeypatch.setattr(runtime, "windows_adapters", lambda: [
        "Intel UHD Graphics", "NVIDIA GeForce RTX 5090",
    ])
    monkeypatch.setattr(runtime, "nvidia_cuda_build", lambda: "cu128")
    return installation


def test_detects_discrete_radeon_among_integrated_graphics():
    assert runtime.amd_target(["AMD Radeon(TM) Graphics", "AMD Radeon RX 9070 XT"]) == (
        "AMD Radeon RX 9070 XT", "gfx1201",
    )
    assert runtime.amd_target(["NVIDIA GeForce GTX 970", "AMD Radeon(TM) Graphics"]) is None
    assert runtime.amd_target(["Unknown RX 9070 XT"]) is None
    assert runtime.amd_target(["AMD Radeon RX 7900 XTX"])[1] == "gfx1100"
    assert runtime.amd_target(["AMD Radeon RX 9060 XT"])[1] == "gfx1200"


def test_cim_handles_one_or_multiple_adapters_and_rejects_bad_output(monkeypatch):
    for output, expected in [
        ('"AMD Radeon RX 9070 XT"', ["AMD Radeon RX 9070 XT"]),
        ('\ufeff["AMD Radeon(TM) Graphics", "AMD Radeon RX 9070 XT"]',
         ["AMD Radeon(TM) Graphics", "AMD Radeon RX 9070 XT"]),
    ]:
        monkeypatch.setattr(runtime, "run", lambda *a, **kw: SimpleNamespace(stdout=output))
        assert runtime.windows_adapters() == expected
    monkeypatch.setattr(runtime, "run", lambda *a, **kw: SimpleNamespace(stdout='{"error":1}'))
    with pytest.raises(ValueError, match="list of graphics"):
        runtime.windows_adapters()


def test_rocm_selects_expected_card_instead_of_igpu():
    properties = [
        SimpleNamespace(name="AMD Radeon(TM) Graphics", gcnArchName="gfx1150", total_memory=512),
        SimpleNamespace(name="AMD Radeon RX 9070 XT", gcnArchName="gfx1201:sramecc-",
                        total_memory=16384),
    ]
    torch = SimpleNamespace(
        version=SimpleNamespace(hip="fixture"),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 2,
                             get_device_properties=lambda i: properties[i]),
    )
    assert runtime.rocm_device(torch, "gfx1201") == "cuda:1"
    # Some Windows runtimes omit architecture metadata.
    del properties[1].gcnArchName
    assert runtime.rocm_device(torch, "gfx1201") == "cuda:1"
    with pytest.raises(RuntimeError, match="expected AMD GPU"):
        runtime.rocm_device(torch, "gfx1100")
    torch.version.hip = None
    with pytest.raises(RuntimeError, match="cannot access"):
        runtime.rocm_device(torch)


def comparison():
    return {"weights_sha256": "same", "positions": [
        {"fen": "fixture", "ratings": [1800, 1800], "probabilities": {"e2e4": 0.6, "d2d4": 0.4}},
    ]}


def test_comparison_accepts_tolerances_and_rejects_changed_probabilities():
    cpu, gpu = comparison(), comparison()
    gpu["positions"][0]["probabilities"]["e2e4"] += 1e-7
    assert runtime.compare_probabilities(cpu, gpu) < 1e-5
    gpu["positions"][0]["probabilities"]["e2e4"] += 0.01
    with pytest.raises(ValueError, match="exceeds"):
        runtime.compare_probabilities(cpu, gpu)


@pytest.mark.parametrize("change", ["weights", "positions", "ratings", "moves", "nan", "empty"])
def test_comparison_cannot_pass_mismatched_or_invalid_results(change):
    cpu, gpu = comparison(), copy.deepcopy(comparison())
    if change == "weights":
        gpu["weights_sha256"] = "other"
    elif change == "positions":
        gpu["positions"] = []
    elif change == "ratings":
        gpu["positions"][0]["ratings"] = [400, 400]
    elif change == "moves":
        del gpu["positions"][0]["probabilities"]["d2d4"]
    elif change == "nan":
        gpu["positions"][0]["probabilities"]["d2d4"] = float("nan")
    else:
        cpu["positions"][0]["probabilities"] = {}
        gpu["positions"][0]["probabilities"] = {}
    with pytest.raises(ValueError):
        runtime.compare_probabilities(cpu, gpu)


@pytest.mark.parametrize("failure", [78, -1073741819])
def test_gpu_inference_failure_or_native_crash_starts_cpu(installation, monkeypatch, failure):
    cpu_calls = []
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=failure,
    ))
    monkeypatch.setattr(runtime.subprocess, "call", lambda args, **kw: cpu_calls.append(args) or 0)
    assert runtime.start() == 0
    assert cpu_calls[0][0] == str(runtime.python_for(".venv"))
    assert cpu_calls[0][1:] == ["-m", "elovision", "serve", "--open"]


def test_successful_gpu_session_does_not_spawn_second_server(installation, monkeypatch):
    def launch(args, **kwargs):
        assert args[0] == str(runtime.python_for(".venv-amd"))
        output = args[args.index("--output") + 1]
        runtime.write_json(output, {"device": "cuda:1"})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", launch)
    monkeypatch.setattr(runtime.subprocess, "call", lambda *a, **kw: pytest.fail("CPU started"))
    assert runtime.start() == 0


def test_partial_gpu_install_is_never_selected(installation, monkeypatch):
    (runtime.CACHE / "amd-install.json").unlink()
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: pytest.fail("AMD started"))
    monkeypatch.setattr(runtime.subprocess, "call", lambda *a, **kw: 0)
    assert runtime.start() == 0


def test_explicit_cpu_bypasses_gpu_and_explicit_gpu_never_silently_falls_back(
    installation, monkeypatch,
):
    monkeypatch.setenv("ELOVISION_DEVICE", "cpu")
    monkeypatch.setattr(runtime, "windows_adapters", lambda: pytest.fail("Graphics scan"))
    monkeypatch.setattr(runtime.subprocess, "call", lambda *a, **kw: 0)
    assert runtime.start() == 0
    monkeypatch.setenv("ELOVISION_DEVICE", "cuda:1")
    monkeypatch.setattr(runtime, "windows_adapters", lambda: ["AMD Radeon RX 9070 XT"])
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=78))
    monkeypatch.setattr(runtime.subprocess, "call", lambda *a, **kw: pytest.fail("CPU started"))
    assert runtime.start() == 78


def test_failed_amd_install_preserves_cpu_setup_and_disables_partial_install(
    installation, monkeypatch,
):
    calls = []

    def execute(args, **kwargs):
        calls.append([str(arg) for arg in args])
        if runtime.AMD_INDEX in args:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(runtime, "run", execute)
    assert runtime.install() == 0
    assert not (runtime.CACHE / "amd-install.json").exists()
    assert any("torch==2.8.0+cpu" in args for args in calls)
    assert any("torch[device-gfx1201]>=2.8,<3" in args for args in calls)
    # Both installs target project-owned Python executables; no global pip invocation.
    assert all(args[0] in {str(runtime.python_for(".venv")),
                          str(runtime.python_for(".venv-amd"))} for args in calls)


def test_probe_failure_cannot_write_success_report(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "real_probe", lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("GPU kernel failed"),
    ))
    output = tmp_path / "success.json"
    output.write_text('{"stale": "success"}')
    with pytest.raises(RuntimeError, match="GPU kernel failed"):
        runtime.probe("amd", output)
    assert not output.exists()


def test_cpu_baseline_failure_is_not_reported_as_successful_setup(installation, monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        if "probe" in args:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(runtime, "run", execute)
    with pytest.raises(subprocess.CalledProcessError):
        runtime.install()
    assert not (runtime.CACHE / "amd-install.json").exists()
    assert not any(runtime.AMD_INDEX in args for args in calls)


def test_amd_install_pins_its_torch_and_enables_only_after_comparison(installation, monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        if "-c" in args:
            return SimpleNamespace(stdout="2.11.0+rocmfixture\n", returncode=0)
        if "--reference" in args:
            assert not (runtime.CACHE / "amd-install.json").exists()
        return SimpleNamespace(stdout="fixture-package==1\n", returncode=0)

    monkeypatch.setattr(runtime, "run", execute)
    assert runtime.install() == 0
    receipt = json.loads((runtime.CACHE / "amd-install.json").read_text())
    assert receipt["target"] == "gfx1201"
    assert (runtime.CACHE / "amd-torch-constraint.txt").read_text() == (
        "torch==2.11.0+rocmfixture\n"
    )
    assert any("-c" in args and "-e" in args for args in calls)
    assert any("probe" in args and "--reference" in args for args in calls)
    assert not any("--pre" in args for args in calls)


@pytest.mark.parametrize("vendor", ["amd", "nvidia"])
def test_gpu_server_reuses_verified_loaded_service(tmp_path, monkeypatch, vendor):
    service = SimpleNamespace(config=SimpleNamespace(), policy=SimpleNamespace())
    from elovision.config import ModelConfig

    service.config = ModelConfig(device="cuda:1")
    monkeypatch.setattr(runtime, "real_probe", lambda *a, **kw: (service, {
        "device_label": "fixture Radeon", "device": "cuda:1", "positions": [],
    }))
    import elovision.__main__ as cli

    seen = []
    monkeypatch.setattr(cli, "main", lambda **kw: seen.append(kw["service"]))
    monkeypatch.setattr(runtime.sys, "argv", [])
    assert runtime.serve_gpu(vendor, "gfx1201", tmp_path / "ready.json") == 0
    assert seen == [service]
    assert service.policy.config.device == "auto"
    assert json.loads((tmp_path / "ready.json").read_text())["device"] == "cuda:1"


@pytest.mark.parametrize("output, build", [
    ("12.0\n", "cu128"), ("8.6\n", "cu126"), ("5.2\n", "cu126"),
    ("8.6\n12.0\n", "cu128"), ("8.6\nN/A\n", "cu128"), ("", "cu128"),
])
def test_nvidia_cuda_build_supports_blackwell_and_older_cards(monkeypatch, output, build):
    monkeypatch.setattr(runtime, "run", lambda *a, **kw: SimpleNamespace(stdout=output))
    assert runtime.nvidia_cuda_build() == build


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("smi", 20)])
def test_nvidia_smi_failure_does_not_prevent_optional_setup(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(runtime, "run", fail)
    assert runtime.nvidia_cuda_build() == "cu128"


def test_nvidia_device_uses_cuda_backend_and_accepts_older_geforce_names():
    assert runtime.nvidia_adapter(["AMD Radeon(TM) Graphics", "NVIDIA GeForce RTX 4090"])
    assert runtime.nvidia_adapter(["AMD Radeon RX 9070 XT"]) is None
    properties = [
        SimpleNamespace(name="NVIDIA GeForce RTX 3060", total_memory=12),
        SimpleNamespace(name="GeForce GTX 1080 Ti", total_memory=11),
    ]
    torch = SimpleNamespace(
        version=SimpleNamespace(hip=None, cuda="12.6"),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: len(properties),
                             get_device_properties=lambda i: properties[i]),
    )
    assert runtime.nvidia_device(torch) == "cuda:0"
    torch.cuda.is_available = lambda: False
    with pytest.raises(RuntimeError, match="cannot access an NVIDIA"):
        runtime.nvidia_device(torch)
    torch.cuda.is_available = lambda: True
    torch.version.hip = "fixture"
    with pytest.raises(RuntimeError, match="cannot access an NVIDIA"):
        runtime.nvidia_device(torch)
    torch.version.hip = None
    properties.clear()
    with pytest.raises(RuntimeError, match="did not expose"):
        runtime.nvidia_device(torch)


def test_nvidia_install_is_isolated_pinned_and_compared_before_activation(
    nvidia_installation, monkeypatch,
):
    calls = []
    runtime.python_for(".venv-nvidia").unlink()

    def execute(args, **kwargs):
        calls.append([str(arg) for arg in args])
        if "-c" in args:
            return SimpleNamespace(stdout="2.8.0+cu128\n")
        if "--reference" in args:
            assert not (runtime.CACHE / "nvidia-install.json").exists()
        return SimpleNamespace(stdout="fixture-package==1\n")

    monkeypatch.setattr(runtime, "run", execute)
    assert runtime.install() == 0
    assert (runtime.CACHE / "nvidia-install.json").exists()
    assert (runtime.CACHE / "nvidia-torch-constraint.txt").read_text() == "torch==2.8.0+cu128\n"
    assert any("torch==2.8.0+cpu" in args for args in calls)
    assert any(runtime.NVIDIA_INDEX + "cu128" in args and "torch==2.8.0+cu128" in args
               for args in calls)
    assert any("venv" in args and str(runtime.ROOT / ".venv-nvidia") in args for args in calls)
    assert any("--reference" in args and "nvidia" in args for args in calls)
    assert all(args[0] in {str(runtime.python_for(".venv")),
                          str(runtime.python_for(".venv-nvidia"))} for args in calls)


@pytest.mark.parametrize("failure_at", ["download", "inference"])
def test_nvidia_failed_install_revokes_stale_receipt_and_preserves_cpu(
    nvidia_installation, monkeypatch, failure_at,
):
    def execute(args, **kwargs):
        if (failure_at == "download" and runtime.NVIDIA_INDEX + "cu128" in args) or (
            failure_at == "inference" and "--reference" in args
        ):
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout="2.8.0+cu128\n")

    monkeypatch.setattr(runtime, "run", execute)
    assert runtime.install() == 0
    assert not (runtime.CACHE / "nvidia-install.json").exists()
    assert (runtime.CACHE / "nvidia-setup-error.txt").exists()
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: pytest.fail("GPU started"))
    cpu_calls = []
    monkeypatch.setattr(runtime.subprocess, "call", lambda args, **kw: cpu_calls.append(args) or 0)
    assert runtime.start() == 0
    assert cpu_calls[0][0] == str(runtime.python_for(".venv"))


def test_verified_nvidia_is_preferred_on_mixed_vendor_pc(nvidia_installation, monkeypatch):
    runtime.write_json(runtime.CACHE / "amd-install.json", {"target": "gfx1201"})
    monkeypatch.setattr(runtime, "windows_adapters", lambda: [
        "AMD Radeon RX 9070 XT", "NVIDIA GeForce RTX 5090",
    ])

    def launch(args, **kwargs):
        assert args[0] == str(runtime.python_for(".venv-nvidia"))
        assert "serve-nvidia" in args
        runtime.write_json(args[args.index("--output") + 1], {"device": "cuda:0"})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", launch)
    monkeypatch.setattr(runtime.subprocess, "call", lambda *a, **kw: pytest.fail("CPU started"))
    assert runtime.start() == 0


@pytest.mark.parametrize("failure", [78, -1073741819, 0])
def test_nvidia_failed_start_or_missing_verification_marker_falls_back(
    nvidia_installation, monkeypatch, failure,
):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=failure,
    ))
    cpu_calls = []
    monkeypatch.setattr(runtime.subprocess, "call", lambda args, **kw: cpu_calls.append(args) or 0)
    assert runtime.start() == 0
    assert cpu_calls[0][0] == str(runtime.python_for(".venv"))
    monkeypatch.setenv("ELOVISION_DEVICE", "cuda:0")
    monkeypatch.setattr(runtime.subprocess, "call", lambda *a, **kw: pytest.fail("CPU started"))
    assert runtime.start() == (failure or runtime.GPU_FAILURE)


def test_nvidia_cpu_override_bypasses_gpu(nvidia_installation, monkeypatch):
    monkeypatch.setenv("ELOVISION_DEVICE", "cpu")
    monkeypatch.setattr(runtime, "windows_adapters", lambda: pytest.fail("GPU discovery"))
    calls = []
    monkeypatch.setattr(runtime.subprocess, "call", lambda args, **kw: calls.append(kw) or 0)
    assert runtime.start() == 0
    assert calls[0]["env"]["ELOVISION_DEVICE"] == "cpu"


def test_nvidia_probe_rejects_cpu_inference_and_closes_service(monkeypatch):
    import elovision.inference as inference

    torch = SimpleNamespace(
        version=SimpleNamespace(hip=None, cuda="12.8"),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1,
                             get_device_properties=lambda i: SimpleNamespace(total_memory=16),
                             reset_peak_memory_stats=lambda device: None),
    )
    monkeypatch.setitem(runtime.sys.modules, "torch", torch)
    closed = []

    def service(config):
        assert config.device == "cuda:0"
        return SimpleNamespace(
            predict_many=lambda *a: [{"model": {"device": "cpu"}}],
            close=lambda: closed.append(True),
        )

    monkeypatch.setattr(inference, "InferenceService", service)
    with pytest.raises(RuntimeError, match="did not actually infer"):
        runtime.real_probe("nvidia")
    assert closed == [True]
