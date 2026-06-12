"""Integration test against the docker mini-Slurm stack.

Skipped unless ``ALPHAEX_LOCAL_SLURM=1`` is set, so the regular
``pytest`` invocation collects but doesn't try to run it. To enable
locally:

    bash docker/setup.sh
    ALPHAEX_LOCAL_SLURM=1 uv run pytest test/test_submitter_local.py -v
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from alphaex.submitter import Submitter

pytestmark = pytest.mark.skipif(
    os.environ.get("ALPHAEX_LOCAL_SLURM") != "1",
    reason="requires the docker mini-slurm stack (see docker/setup.sh)",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT_DIR = "/home/alphaex/AlphaEx"


@pytest.fixture
def clean_output_dirs():
    out_dir = REPO_ROOT / "test" / "output"
    err_dir = REPO_ROOT / "test" / "error"
    for d in (out_dir, err_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    yield out_dir, err_dir


def test_submitter_drives_two_local_clusters(clean_output_dirs):
    out_dir, _ = clean_output_dirs

    clusters = [
        {
            "name": "cluster-a",
            "capacity": 2,
            "account": "alphaex",
            "project_root_dir": PROJECT_ROOT_DIR,
        },
        {
            "name": "cluster-b",
            "capacity": 2,
            "account": "alphaex",
            "project_root_dir": PROJECT_ROOT_DIR,
        },
    ]

    submitter = Submitter(
        clusters=clusters,
        job_list=[(1, 4)],
        script_path="test/run.sh",
        export_params={
            "python_module": "test.my_experiment_entrypoint",
            "config_file": "test/cfg/variables.json",
        },
        sbatch_params={"time": "00:01:00"},
        duration_between_two_polls=2,
    )

    start = time.monotonic()
    submitter.submit()
    elapsed = time.monotonic() - start
    assert elapsed < 120, f"submitter.submit() ran for {elapsed:.1f}s; expected <120s"

    for task_id in range(1, 5):
        out_file = out_dir / f"submit_{task_id}.txt"
        assert out_file.exists(), f"missing output file {out_file}"
        text = out_file.read_text()
        assert "test.my_experiment_entrypoint" in text
        assert f"sweep_id: {task_id}" in text
        assert "test/cfg/variables.json" in text
