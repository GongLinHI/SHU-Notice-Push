from pathlib import Path
import shutil

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def seed_runtime_config_for_temporary_repo(tmp_path):
    destination = tmp_path / "resources" / "config" / "runtime.yml"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / "resources" / "config" / "runtime.yml", destination)
