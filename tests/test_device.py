from types import SimpleNamespace

import pytest

from elovision.device import device_details, resolve_device


def torch_stub(*, available, hip=None, cuda=None, discovery_error=None):
    def is_available():
        if discovery_error:
            raise discovery_error
        return available

    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=is_available,
            get_device_name=lambda _device: "Fixture GPU",
        ),
        version=SimpleNamespace(hip=hip, cuda=cuda),
    )


@pytest.mark.parametrize(
    "torch", [torch_stub(available=True, hip="6.4"), torch_stub(available=True, cuda="12.8")]
)
def test_auto_selects_torch_gpu_api_for_rocm_and_cuda(torch):
    assert resolve_device(torch, "auto") == "cuda"


def test_auto_falls_back_to_cpu_if_no_gpu_or_device_discovery_fails():
    assert resolve_device(torch_stub(available=False), "auto") == "cpu"
    assert resolve_device(
        torch_stub(available=False, discovery_error=RuntimeError("driver")), "auto"
    ) == "cpu"


def test_explicit_missing_gpu_request_fails_actionably():
    with pytest.raises(RuntimeError, match="cannot access"):
        resolve_device(torch_stub(available=False), "cuda:0")


def test_device_metadata_names_rocm_and_cuda_backends():
    rocm = device_details(torch_stub(available=True, hip="6.4"), "cuda:0")
    cuda = device_details(torch_stub(available=True, cuda="12.8"), "cuda:0")
    assert rocm == {
        "device": "cuda:0",
        "backend": "ROCm",
        "device_name": "Fixture GPU",
        "device_label": "Fixture GPU · ROCm 6.4",
    }
    assert cuda["backend"] == "CUDA"
    assert device_details(torch_stub(available=False), "cpu")["device_label"] == "CPU"
