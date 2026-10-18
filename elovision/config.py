import os
from dataclasses import dataclass, field
from pathlib import Path

UPSTREAM_REVISION = "1e13597c42d4858b7cfd7cfdae01e297263364b2"
MODEL_REPO = "UofTCSSLab/Maia3-79M"
MODEL_FILE = "maia3-79m.pt"
RATINGS = tuple(range(400, 3001, 200))


@dataclass(frozen=True)
class ModelConfig:
    model_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "ELOVISION_MODEL_DIR", str(Path(__file__).resolve().parents[1] / ".models")
            )
        )
        .expanduser()
        .resolve()
    )
    threads: int = field(
        default_factory=lambda: max(
            1, min(4, int(os.environ.get("ELOVISION_THREADS", str(os.cpu_count() or 1))))
        )
    )
    cache_size: int = 1024

    @property
    def checkpoint(self) -> Path:
        return self.model_dir / MODEL_FILE

    @property
    def manifest(self) -> Path:
        return self.model_dir / "manifest.json"
