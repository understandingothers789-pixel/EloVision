"""Select and describe the PyTorch inference device without extra dependencies."""


def resolve_device(torch_module, requested="auto"):
    """Choose a visible PyTorch CUDA/ROCm GPU in auto mode, otherwise CPU."""
    requested = str(requested).strip().lower()
    if requested == "auto":
        try:
            if not torch_module.cuda.is_available():
                return "cpu"
        except Exception:
            # A partially installed runtime or inaccessible driver must not
            # prevent the supported CPU fallback from starting.
            return "cpu"
        if getattr(getattr(torch_module, "version", None), "hip", None):
            try:
                count = torch_module.cuda.device_count()
                if count > 1:

                    def priority(index):
                        properties = torch_module.cuda.get_device_properties(index)
                        # A Ryzen iGPU may be enumerated before the discrete Radeon.
                        return ("radeon rx" in properties.name.lower(), properties.total_memory)

                    return f"cuda:{max(range(count), key=priority)}"
            except Exception:
                # Optional device metadata must not make an available GPU unusable.
                pass
        return "cuda"
    if requested.startswith("cuda"):
        try:
            available = torch_module.cuda.is_available()
        except Exception:
            available = False
        if not available:
            raise RuntimeError(
                f"GPU device '{requested}' was requested, but PyTorch cannot access "
                "a CUDA or ROCm GPU. Use ELOVISION_DEVICE=auto or cpu."
            )
    return requested


def device_details(torch_module, device):
    """Return truthful runtime details for diagnostics and API metadata."""
    if not str(device).startswith("cuda"):
        return {"device": "cpu", "backend": "CPU", "device_name": "CPU", "device_label": "CPU"}

    runtime = getattr(torch_module, "version", None)
    hip = getattr(runtime, "hip", None)
    cuda = getattr(runtime, "cuda", None)
    if hip:
        backend = "ROCm"
        version = hip
    elif cuda:
        backend = "CUDA"
        version = cuda
    else:
        backend = "PyTorch GPU"
        version = None
    try:
        name = torch_module.cuda.get_device_name(device)
    except Exception:
        name = "GPU name unavailable"
    label = f"{name} · {backend}{' ' + str(version) if version else ''}"
    return {
        "device": str(device),
        "backend": backend,
        "device_name": name,
        "device_label": label,
    }
