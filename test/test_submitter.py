#######################################################################
# Copyright (C) 2019 Yi Wan(wan6@ualberta.ca)                         #
# Permission given to modify the code as long as you keep this        #
# declaration at the top                                              #
#######################################################################
"""Runnable Submitter usage example against a real HPC cluster.

This file is the canonical example referenced from README.md. The clusters
listed below assume you have ssh access to ``cedar`` and ``mp2`` (compute
canada style) configured in ``~/.ssh/config``. Tailor the names, capacities,
and result paths to whatever clusters you have access to.

Three values that vary per-account are read from environment variables so
the file is runnable as-is without editing:

  ALPHAEX_PROJECT_ROOT  - absolute path on each cluster where AlphaEx is
                          cloned (e.g. /home/<you>/projects/<account>/<you>/AlphaEx).
  ALPHAEX_ACCOUNT       - your slurm account name (e.g. def-sutton, rrg-whitem).
  ALPHAEX_REPO_URL      - your fork of AlphaEx (defaults to upstream).

Example:

    ALPHAEX_PROJECT_ROOT=/home/alice/projects/def-sutton/alice/AlphaEx \\
    ALPHAEX_ACCOUNT=def-sutton \\
    python -m test.test_submitter

This file is intentionally excluded from pytest collection (see
``[tool.pytest.ini_options]`` in ``pyproject.toml``) - it talks to live
clusters and is meant to be run by hand.
"""

import os

from alphaex.submitter import Submitter

PROJECT_ROOT_DIR = os.environ.get("ALPHAEX_PROJECT_ROOT", "<set ALPHAEX_PROJECT_ROOT>")
ACCOUNT = os.environ.get("ALPHAEX_ACCOUNT", "<set ALPHAEX_ACCOUNT>")
REPO_URL = os.environ.get(
    "ALPHAEX_REPO_URL", "https://github.com/AmiiThinks/AlphaEx.git"
)


def test_submitter():
    clusters = [
        {
            "name": "cedar",
            "capacity": 3,
            "account": ACCOUNT,
            "project_root_dir": PROJECT_ROOT_DIR,
            "exp_results_from": [
                f"{PROJECT_ROOT_DIR}/test/output",
                f"{PROJECT_ROOT_DIR}/test/error",
            ],
            "exp_results_to": ["test/output", "test/error"],
        },
        {
            "name": "mp2",
            "capacity": 3,
            "account": ACCOUNT,
            "project_root_dir": PROJECT_ROOT_DIR,
            "exp_results_from": [
                f"{PROJECT_ROOT_DIR}/test/output",
                f"{PROJECT_ROOT_DIR}/test/error",
            ],
            "exp_results_to": ["test/output", "test/error"],
        },
    ]
    job_list = [(1, 4), 6, (102, 105), 100, (8, 12), 107]
    script_path = "test/submit.sh"
    submitter = Submitter(
        clusters,
        job_list,
        script_path,
        export_params={
            "python_module": "test.my_experiment_entrypoint",
            "config_file": "test/cfg/variables.json",
        },
        sbatch_params={
            "time": "00:10:00",
            "mem-per-cpu": "1G",
            "job-name": script_path.split("/")[1],
        },
        repo_url=REPO_URL,
        duration_between_two_polls=60,
    )
    submitter.submit()


if __name__ == "__main__":
    test_submitter()
