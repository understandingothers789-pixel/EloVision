# Windows AMD GPU setup

ELO Vision can keep two independent Python environments in the project folder:

| Environment | Purpose |
| --- | --- |
| `.venv` | CPU Torch **2.8.0+cpu**, including a working CPU fallback |
| `.venv-amd` | AMD's stable ROCm-enabled Torch **2.x** and matching GPU kernels |

Both use the same source files, `.models` weights, and `.engines` Stockfish binary.
They do not install packages into your global Python or replace your display driver.
The AMD environment may use a newer Torch than 2.8.0. Driver/runtime incompatibility,
missing Windows wheels, or numerical differences can prevent it from being selected;
that is why the CPU environment is kept separately. No administrator terminal is needed.

## What to do on your PC

1. Close ELO Vision's running terminal with **Ctrl+C**.
2. Download and extract the updated ELO Vision project. If upgrading an existing folder,
   replace the source files and launchers; keep `.models`, `.engines`, and `.venv`.
   If extracting to a new folder, `.models` and `.engines` can be copied into it to
   reuse downloads. Recreate Python environments by running the installer.
3. Keep **64-bit Python 3.12** and a compatible AMD Adrenalin driver installed.
   Restart Windows if the driver installer requests it. Updating Adrenalin does
   not by itself install GPU-enabled PyTorch.
4. Double-click **`install.bat`**. It first prepares CPU Torch 2.8.0. It then detects
   Windows graphics adapters using PowerShell/CIM (WMIC is not required). A recognized
   Radeon, including **RX 9070 XT / gfx1201**, triggers the isolated AMD installation.
   Allow several GB of downloads and additional disk space for both environments.
5. Look for **“AMD setup and real Maia CPU/GPU comparison passed.”** If AMD setup
   fails, the terminal explains why and CPU setup remains usable. Do not interpret
   “CPU setup is complete” as a successful GPU installation.
6. Double-click **`start.bat`**. It verifies GPU Maia inference again, then starts
   the app with the loaded model. The console should say **“Verified real Maia
   inference: … RX 9070 XT … ROCm …”**. The website's model status should identify
   the Radeon and ROCm. `Ready · CPU · Offline` means CPU is being used.

Use **`start-cpu.bat`** to select CPU manually. **`check-device.bat`** prints Windows
adapter names and the Torch, ROCm, CUDA, and GPU details for both environments.
Its GPU enumeration is a diagnostic; only the real Maia check confirms GPU inference.
Stockfish is a CPU engine and does not use this ROCm setup.

## Automatic checks and fallback

Installation compares nine real Maia distributions: three positions (including
game history and promotion) at 600, 1800, and 2600 Elo. It checks the same verified
weights, legal-move sets, finite normalized probabilities, and a maximum absolute
CPU/GPU probability difference of **0.00001** (0.001 percentage points). CPU results
come from the CPU environment, so the comparison also covers different Torch builds.
The normal model adapter checks tensor placement and uses float32 without AMP.

The launcher checks actual GPU inference in a child process so even a GPU import
failure or native startup crash can fall back to CPU. It reuses the successfully
loaded model rather than loading the weights twice. No network access occurs during
these launch checks. Later recoverable GPU inference errors use the existing CPU
fallback in the model adapter. Explicit `ELOVISION_DEVICE=cuda:N` requests do not
silently fall back. Default `auto` is recommended.

An incomplete AMD installation is never activated. Unknown GPU models, unavailable
packages, unavailable PowerShell discovery, failed inference, and failed numerical
comparisons leave the CPU path available. On a PC with both integrated and discrete
Radeon graphics, the runtime selects the matching GPU architecture and then the
largest GPU memory capacity, rather than assuming the first adapter is the RX card.

## If GPU setup fails

- Keep the exact error text above the fallback message. Missing compatible wheels,
  network failures, and incompatible drivers need different fixes.
- Run `check-device.bat`. A ROCm value of `None` in `.venv` is expected; `.venv-amd`
  must report a ROCm build and a visible Radeon. If it cannot import Torch, share
  that error rather than uninstalling your working CPU environment.
- Run `install.bat` again after correcting the prerequisite. Successful packages
  and verified model weights are reused. The installer does not install nightly
  wheels, override the GPU architecture, disable TLS, or change your display driver.
- The project needs access to `stable.repo.amd.com` and any official artifact hosts
  referenced by its index, in addition to the CPU PyTorch/PyPI/model download hosts.
  A failed optional AMD download does not disable the CPU application.

Local diagnostic files live in `.cache/`: `amd-maia-check.json`,
`cpu-maia-reference.json`, `amd-packages.txt`, `amd-torch-constraint.txt`, and
`amd-setup-error.txt` after a failed optional setup. The package list records exact
versions; it is not a portable lockfile for other PCs or operating systems. A
successful installation writes `amd-install.json`; startup still checks inference
instead of trusting that receipt alone.

## Sources and verification limits

The installer follows AMD's documented **stable aggregate index** and
`torch[device-gfx1201]` package extras, without installing unrelated audio/vision packages:

- [AMD ROCm/TheRock release instructions](https://github.com/ROCm/TheRock/blob/6345e7b6d5944599874285ee0d1157b3f7a58fa1/RELEASES.md)
- [AMD's Windows architecture status, including gfx1201](https://github.com/ROCm/TheRock/blob/6345e7b6d5944599874285ee0d1157b3f7a58fa1/SUPPORTED_GPUS.md)
- [AMD's system support source](https://github.com/ROCm/ROCm/blob/63fd8390bf645ae3c0c715537025137127f892e3/docs/data/os-support.yaml)

These upstream documents describe AMD's general packaging/support, not a successful
ELO Vision run on your PC. The cloud development environment has CPU-only Torch,
no Radeon GPU, and no verified model weights. Windows launchers, downloads from
AMD's index, actual RX 9070 XT inference, latency, throughput, and peak VRAM have
**not been verified here**. Tests of the launcher and failure handling use mocked
Windows subprocesses; installation performs the required real-model checks locally.
GPU acceleration is reported as working only after those checks pass on your PC.
