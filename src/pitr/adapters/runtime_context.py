"""Host transport receives paths and a ledger, never the research service."""
from dataclasses import dataclass
from pathlib import Path
import os

from pitr.domain.common import digest


@dataclass
class RuntimeContext:
    root: Path
    store: object


def runtime_root(context) -> Path:
    parent = Path(os.environ.get('PITR_RUNTIME_DIR', '~/.pitr-research-runtime')).expanduser()
    return parent / digest(str(Path(context.root).resolve()))[:20]
