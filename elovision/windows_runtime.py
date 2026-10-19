"""Windows CPU/AMD environments. Bootstrap code uses only the standard library.

Package source: ROCm/TheRock RELEASES.md at
6345e7b6d5944599874285ee0d1157b3f7a58fa1 (stable aggregate index, device extras).
No GPU success is recorded until actual checksum-verified Maia inference passes.
"""

import argparse
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
AMD_INDEX = "https://stable.repo.amd.com/rocm/whl-next/"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
GPU_FAILURE = 78
# Conservative product lookup, not a claim that every driver supports these cards.
# Unknown products remain on CPU rather than guessing an architecture.
AMD_TARGETS = (
    (r"\bRX 9070(?: XT| GRE)?\b", "gfx1201"),
    (r"\bRX 9060(?: XT)?\b", "gfx1200"),
    (r"\bRX 7900(?: XTX| XT| GRE)?\b", "gfx1100"),
    (r"\bRX (?:7800 XT|7700 XT)\b", "gfx1101"),
    (r"\bRX 7600(?: XT)?\b", "gfx1102"),
)


def python_for(name):
    return ROOT / name / "Scripts" / "python.exe"


def run(args, *, capture=False, timeout=None, env=None):
    return subprocess.run(
        [str(arg) for arg in args], cwd=ROOT, check=True, timeout=timeout,
        text=True, encoding="utf-8", errors="replace", env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def windows_adapters():
    """No WMIC dependency; Windows 11 includes PowerShell and CIM."""
    result = run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
         "@(Get-CimInstance Win32_VideoController -ErrorAction Stop | "
         "Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress"],
        capture=True, timeout=20,
    )
    names = json.loads(result.stdout.lstrip("\ufeff"))
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("Windows did not return a list of graphics adapters.")
    return names


def amd_target(names):
    for pattern, target in AMD_TARGETS:
        for name in names:
            if ("AMD" in name.upper() or "RADEON" in name.upper()) and re.search(
                pattern, name, re.IGNORECASE
            ):
                return name, target
    return None


def write_json(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(path)


def compare_probabilities(reference, candidate, tolerance=1e-5):
    if reference["weights_sha256"] != candidate["weights_sha256"]:
        raise ValueError("CPU/GPU checks used different model weights.")
    if not reference["positions"] or len(reference["positions"]) != len(candidate["positions"]):
        raise ValueError("CPU/GPU checks used different position counts.")
    maximum = 0.0
    for cpu, gpu in zip(reference["positions"], candidate["positions"]):
        if cpu["fen"] != gpu["fen"] or cpu["ratings"] != gpu["ratings"]:
            raise ValueError("CPU/GPU checks used different positions or ratings.")
        if cpu["probabilities"].keys() != gpu["probabilities"].keys():
            raise ValueError("CPU/GPU checks returned different legal moves.")
        if not cpu["probabilities"]:
            raise ValueError("CPU/GPU check returned no probabilities.")
        for move, expected in cpu["probabilities"].items():
            actual = gpu["probabilities"][move]
            if not math.isfinite(actual) or not math.isfinite(expected):
                raise ValueError("CPU/GPU check returned non-finite probabilities.")
            maximum = max(maximum, abs(expected - actual))
    if maximum > tolerance:
        raise ValueError(f"CPU/GPU probability delta {maximum:.8g} exceeds {tolerance}.")
    return maximum


def rocm_device(torch, target=None):
    if not torch.version.hip or not torch.cuda.is_available():
        raise RuntimeError("This PyTorch environment cannot access an AMD ROCm GPU.")
    candidates = []
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        architecture = str(getattr(properties, "gcnArchName", "") or "").split(":")[0]
        # Some Windows wheels omit gcnArchName; fall back to the same product map.
        product = amd_target([properties.name])
        if target and architecture != target and (not product or product[1] != target):
            continue
        candidates.append((properties.total_memory, index))
    if not candidates:
        raise RuntimeError(f"ROCm did not expose the expected AMD GPU ({target}).")
    # On systems with a Ryzen iGPU and Radeon discrete card, use the discrete card.
    return f"cuda:{max(candidates)[1]}"


def real_probe(device, *, target=None, full=False, requested="auto"):
    """Real model, legal-move distributions, no cache/test logits or silent fallback."""
    import chess
    import torch

    from .config import ModelConfig
    from .inference import InferenceService, PredictionRequest

    selected = rocm_device(torch, target) if device == "amd" else "cpu"
    if device == "amd" and requested.startswith("cuda"):
        selected = f"cuda:{torch.cuda.current_device()}" if requested == "cuda" else requested
    config = replace(ModelConfig(), device=selected)
    service = InferenceService(config)
    boards = [chess.Board()]
    if full:
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "d6", "d4", "Bg4", "dxe5", "Bxf3"):
            board.push_san(san)
        boards.extend([board, chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")])
    positions = []
    started = time.perf_counter()
    try:
        if device == "amd":
            torch.cuda.reset_peak_memory_stats(selected)
        for board in boards:
            request = PredictionRequest(
                board.fen(en_passant="fen"), initial_fen=board.root().fen(),
                moves=tuple(move.uci() for move in board.move_stack),
            )
            pairs = [(600, 600), (1800, 1800), (2600, 2600)] if full else [(1800, 1800)]
            for result in service.predict_many(request, pairs):
                if device == "amd" and result["model"]["device"] != selected:
                    raise RuntimeError("Maia did not actually perform inference on the AMD GPU.")
                positions.append({
                    "fen": request.fen,
                    "ratings": [result["player_elo"], result["opponent_elo"]],
                    "probabilities": {m["uci"]: m["probability"] for m in result["moves"]},
                })
        if device == "amd":
            torch.cuda.synchronize(selected)
        metadata = service.policy.metadata
        report = {
            "python": sys.version.split()[0], "executable": sys.executable,
            "torch": str(torch.__version__), "rocm": torch.version.hip,
            "device": metadata["device"], "device_label": metadata["device_label"],
            "weights_sha256": metadata["weights_sha256"],
            "elapsed_seconds_including_load": time.perf_counter() - started,
            "peak_allocated_vram_mb": (
                torch.cuda.max_memory_allocated(selected) / 1024**2 if device == "amd" else 0
            ),
            "positions": positions,
        }
        return service, report
    except BaseException:
        service.close()
        raise


def probe(device, output, reference=None, target=None):
    Path(output).unlink(missing_ok=True)
    service, report = real_probe(device, target=target, full=True)
    try:
        if reference:
            report["max_cpu_gpu_probability_delta"] = compare_probabilities(
                json.loads(Path(reference).read_text(encoding="utf-8")), report
            )
        write_json(output, report)
        print(f"Real Maia check passed: {report['device_label']}", flush=True)
    finally:
        service.close()


def install():
    cpu = python_for(".venv")
    amd = python_for(".venv-amd")
    CACHE.mkdir(exist_ok=True)
    print("Installing CPU Torch 2.8.0 in .venv (global Python is unchanged).", flush=True)
    run([cpu, "-m", "pip", "install", "--index-url", CPU_INDEX, "torch==2.8.0+cpu"])
    run([cpu, "-m", "pip", "install", "-e", "."])
    run([cpu, "-m", "elovision", "model", "install"])
    try:
        names = windows_adapters()
        print("Windows graphics: " + ", ".join(names), flush=True)
        detected = amd_target(names)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Graphics discovery failed: {exc}\nCPU setup is complete.", flush=True)
        return 0
    if not detected:
        print("No mapped AMD Radeon GPU detected. CPU setup is complete.")
        return 0
    name, target = detected
    print(
        f"{name} detected ({target}). Installing AMD stable ROCm/PyTorch in .venv-amd.\n"
        "This can download several GB and use a newer Torch 2.x than the CPU version.\n"
        "Your driver must support AMD's runtime. Failure keeps the CPU app usable.",
        flush=True,
    )
    # Revoke the old receipt before any mutations, including an interrupted reinstall.
    (CACHE / "amd-install.json").unlink(missing_ok=True)
    (CACHE / "amd-maia-check.json").unlink(missing_ok=True)
    reference = CACHE / "cpu-maia-reference.json"
    # A failed mandatory CPU baseline must not be described as successful CPU setup.
    run([cpu, "-m", "elovision.windows_runtime", "probe", "--device", "cpu",
         "--output", reference], timeout=240)
    try:
        if not amd.exists():
            run([cpu, "-m", "venv", ROOT / ".venv-amd"])
        run([amd, "-m", "pip", "install", "--upgrade", "pip"])
        run([amd, "-m", "pip", "install", "--index-url", AMD_INDEX,
             "--only-binary=torch", f"torch[device-{target}]>=2.8,<3"])
        # Exact constraint prevents editable installation from replacing AMD Torch with PyPI Torch.
        version = run([amd, "-c", "import torch; print(torch.__version__)"], capture=True).stdout
        constraint = CACHE / "amd-torch-constraint.txt"
        constraint.write_text(f"torch=={version.strip()}\n", encoding="utf-8")
        run([amd, "-m", "pip", "install", "-c", constraint, "-e", "."])
        run([amd, "-m", "pip", "check"])
        run([amd, "-m", "elovision.windows_runtime", "probe", "--device", "amd",
             "--target", target, "--output", CACHE / "amd-maia-check.json",
             "--reference", reference], timeout=300)
        packages = run([amd, "-m", "pip", "freeze"], capture=True).stdout
        (CACHE / "amd-packages.txt").write_text(packages, encoding="utf-8")
        write_json(CACHE / "amd-install.json", {"target": target, "name": name})
        (CACHE / "amd-setup-error.txt").unlink(missing_ok=True)
        print("AMD setup and real Maia CPU/GPU comparison passed. Run start.bat.")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        (CACHE / "amd-install.json").unlink(missing_ok=True)
        (CACHE / "amd-setup-error.txt").write_text(str(exc), encoding="utf-8")
        print(
            f"\nAMD setup could not be verified: {exc}\n"
            "CPU setup is complete. start.bat will use it.\n"
            "Keep the error above; see docs/WINDOWS_GPU.md or run check-device.bat.",
            flush=True,
        )
    return 0


def start():
    requested = os.environ.get("ELOVISION_DEVICE", "auto").strip().lower()
    amd = python_for(".venv-amd")
    receipt = CACHE / "amd-install.json"
    if requested != "cpu" and amd.exists() and receipt.exists():
        try:
            detected = amd_target(windows_adapters())
            installed = json.loads(receipt.read_text(encoding="utf-8"))
            if not detected or detected[1] != installed["target"]:
                raise ValueError("The installed AMD environment does not match this PC's GPU.")
            # Unique marker distinguishes a native crash before inference from a stopped server.
            with tempfile.TemporaryDirectory(prefix="elovision-start-") as directory:
                marker = Path(directory) / "ready.json"
                result = subprocess.run(
                    [str(amd), "-m", "elovision.windows_runtime", "serve-amd",
                     "--target", detected[1], "--output", str(marker),
                     "--gpu-device", requested], cwd=ROOT,
                )
                if marker.exists() and result.returncode == 0:
                    return result.returncode
                if requested != "auto":
                    return result.returncode or GPU_FAILURE
                print("AMD Maia startup failed; switching to CPU.", flush=True)
        except KeyboardInterrupt:
            return 0
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f"AMD environment unavailable: {exc}", flush=True)
            if requested != "auto":
                return GPU_FAILURE
    environment = os.environ.copy()
    if requested == "auto":
        # .venv may already contain a user-managed NVIDIA CUDA wheel: preserve auto detection.
        print("Starting default Python environment (CPU fallback, or existing CUDA).", flush=True)
    return subprocess.call(
        [str(python_for(".venv")), "-m", "elovision", "serve", "--open"],
        cwd=ROOT, env=environment,
    )


def serve_amd(target, output, requested="auto"):
    try:
        service, report = real_probe("amd", target=target, requested=requested)
    except Exception as exc:
        print(f"AMD real Maia inference failed: {exc}", flush=True)
        return GPU_FAILURE
    # Reuse the already loaded model and allow existing runtime CPU recovery for later failures.
    service.config = replace(service.config, device=requested)
    service.policy.config = service.config
    write_json(output, {key: value for key, value in report.items() if key != "positions"})
    print(f"Verified real Maia inference: {report['device_label']}", flush=True)
    from .__main__ import main as app_main

    sys.argv = ["elovision", "serve", "--open"]
    app_main(service=service)
    return 0


def diagnose():
    try:
        print("Windows adapters:", ", ".join(windows_adapters()), flush=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Graphics discovery failed: {exc}", flush=True)
    code = (
        "import sys, torch; print('Python:', sys.version); "
        "print('Executable:', sys.executable); print('Torch:', torch.__version__); "
        "print('ROCm:', torch.version.hip); print('CUDA:', torch.version.cuda); "
        "print('GPU available:', torch.cuda.is_available()); "
        "print('GPUs:', [torch.cuda.get_device_name(i) "
        "for i in range(torch.cuda.device_count())])"
    )
    for name in (".venv", ".venv-amd"):
        print(f"\n{name}:", flush=True)
        python = python_for(name)
        if python.exists():
            try:
                run([python, "-c", code], timeout=60)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"Environment check failed: {exc}")
        else:
            print("Not installed.")
    print("\nThe website's Ready label reports the device after actual Maia inference.")
    print("GPU enumeration alone does not prove that Maia ran on it.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "start", "diagnose", "probe", "serve-amd"])
    parser.add_argument("--device", choices=["cpu", "amd"], default="cpu")
    parser.add_argument("--target")
    parser.add_argument("--gpu-device", default="auto")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    if args.command in {"install", "start", "diagnose"} and platform.system() != "Windows":
        parser.error("Use these commands on the Windows PC running ELO Vision.")
    if args.command in {"probe", "serve-amd"} and not args.output:
        parser.error("--output is required for a probe or startup check")
    if args.command == "probe":
        probe(args.device, args.output, args.reference, args.target)
        return 0
    if args.command == "serve-amd":
        return serve_amd(args.target, args.output, args.gpu_device)
    if args.command == "diagnose":
        diagnose()
        return 0
    return install() if args.command == "install" else start()


if __name__ == "__main__":
    raise SystemExit(main())
