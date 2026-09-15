"""Project and current service paths."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def project_root() -> Path:
    env = os.environ.get("PITR_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "pyproject.toml").exists() and (p / "src" / "pitr").exists():
            return p
    return Path.cwd()


@dataclass
class Settings:
    root: Path = field(default_factory=project_root)

    @property
    def data_dir(self) -> Path:
        return Path(os.environ.get("PITR_DATA_DIR", self.root / "data"))


    @property
    def schemas_dir(self) -> Path:
        return self.root / "schemas"


settings = Settings()
