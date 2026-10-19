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


def test_gpu_server_reuses_verified_loaded_service(tmp_path, monkeypatch):
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
    assert runtime.serve_amd("gfx1201", tmp_path / "ready.json") == 0
    assert seen == [service]
    assert service.policy.config.device == "auto"
    assert json.loads((tmp_path / "ready.json").read_text())["device"] == "cuda:1"
