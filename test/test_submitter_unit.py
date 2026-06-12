import pytest

from alphaex.submitter import (
    Submitter,
    _build_job_array_string,
    _build_sbatch_command,
    _build_scp_command,
    _build_squeue_command,
    _count_active_jobs,
    _normalize_job_list,
    _validate_cluster,
)

# ----- _normalize_job_list -----


def test_normalize_promotes_ints_to_pair_tuples():
    assert _normalize_job_list([1, (2, 5), 7]) == [(1, 1), (2, 5), (7, 7)]


def test_normalize_passes_tuples_through_unchanged():
    job_list = [(1, 4), (102, 105)]
    assert _normalize_job_list(job_list) == [(1, 4), (102, 105)]


def test_normalize_preserves_order_with_mixed_input():
    job_list = [(1, 4), 6, (102, 105), 100, (8, 12), 107]
    assert _normalize_job_list(job_list) == [
        (1, 4),
        (6, 6),
        (102, 105),
        (100, 100),
        (8, 12),
        (107, 107),
    ]


def test_normalize_rejects_empty_list():
    with pytest.raises(AssertionError):
        _normalize_job_list([])


# ----- _validate_cluster -----


def _valid_cluster(**overrides):
    base = {
        "name": "cedar",
        "capacity": 3,
        "account": "def-sutton",
        "project_root_dir": "/home/alice/proj",
    }
    base.update(overrides)
    return base


def test_validate_defaults_exp_results_when_neither_specified():
    cluster = _valid_cluster()
    result = _validate_cluster(cluster)
    assert result["exp_results_from"] == []
    assert result["exp_results_to"] == []


def test_validate_keeps_exp_results_when_both_specified():
    cluster = _valid_cluster(
        exp_results_from=["/r/a", "/r/b"], exp_results_to=["a", "b"]
    )
    _validate_cluster(cluster)
    assert cluster["exp_results_from"] == ["/r/a", "/r/b"]
    assert cluster["exp_results_to"] == ["a", "b"]


@pytest.mark.parametrize("missing", ["name", "capacity", "account", "project_root_dir"])
def test_validate_raises_on_missing_required_key(missing):
    cluster = _valid_cluster()
    del cluster[missing]
    with pytest.raises(ValueError, match=missing):
        _validate_cluster(cluster)


def test_validate_raises_on_length_mismatch():
    cluster = _valid_cluster(exp_results_from=["/r/a"], exp_results_to=["a", "b"])
    with pytest.raises(ValueError, match="same length"):
        _validate_cluster(cluster)


def test_validate_raises_on_one_sided_exp_results():
    cluster = _valid_cluster(exp_results_from=["/r/a"])
    with pytest.raises(ValueError, match="both specified"):
        _validate_cluster(cluster)


# ----- _build_job_array_string -----


# Normalized version of the README's job_list = [(1,4), 6, (102,105), 100, (8,12), 107]
README_JOB_LIST = [(1, 4), (6, 6), (102, 105), (100, 100), (8, 12), (107, 107)]


@pytest.mark.parametrize(
    "job_list,starting_idx,starting_num,capacity,current,expected",
    [
        # Capacity 3, fresh start: first tuple (1,4) is 4 jobs, doesn't fit;
        # split to fill capacity → "1-3", index stays at 0, num bumps to 4.
        (
            README_JOB_LIST,
            0,
            1,
            3,
            0,
            ("1-3", 0, 4, False),
        ),
        # Resuming after the split: pulls 4, then 6, then partial 102.
        (
            README_JOB_LIST,
            0,
            4,
            3,
            0,
            ("4-4,6-6,102-102", 2, 103, False),
        ),
        # Exact fit at the end of the list flips finish_submitting.
        (
            README_JOB_LIST,
            5,
            107,
            3,
            0,
            ("107-107", 6, 107, True),
        ),
        # Capacity already full → empty string, state unchanged.
        (
            README_JOB_LIST,
            0,
            1,
            3,
            3,
            ("", 0, 1, False),
        ),
        # Whole-list fits inside a huge capacity.
        (
            [(1, 2), (5, 5)],
            0,
            1,
            100,
            0,
            ("1-2,5-5", 2, 5, True),
        ),
    ],
)
def test_build_job_array_string(
    job_list, starting_idx, starting_num, capacity, current, expected
):
    assert (
        _build_job_array_string(job_list, starting_idx, starting_num, capacity, current)
        == expected
    )


# ----- _build_sbatch_command -----


def test_build_sbatch_command_collapses_extra_spaces_with_empty_extras():
    cmd = _build_sbatch_command(
        cluster_name="cedar",
        project_root_dir="/home/alice/proj",
        job_array_string="1-3",
        account="def-sutton",
        sbatch_params={},
        export_params={},
        script_path="test/submit.sh",
    )
    assert cmd == (
        "ssh cedar 'cd /home/alice/proj; sbatch --array=1-3 --account=def-sutton "
        "--export= test/submit.sh'"
    )


def test_build_sbatch_command_includes_sbatch_and_export_params():
    cmd = _build_sbatch_command(
        cluster_name="cedar",
        project_root_dir="/home/alice/proj",
        job_array_string="4-4,6-6",
        account="def-sutton",
        sbatch_params={"time": "00:10:00", "mem-per-cpu": "1G"},
        export_params={"python_module": "test.entry", "config_file": "test/cfg.json"},
        script_path="test/submit.sh",
    )
    assert cmd == (
        "ssh cedar 'cd /home/alice/proj; sbatch --array=4-4,6-6 "
        "--account=def-sutton --time=00:10:00 --mem-per-cpu=1G "
        "--export=python_module=test.entry,config_file=test/cfg.json "
        "test/submit.sh'"
    )


# ----- small command builders -----


def test_build_squeue_command():
    assert _build_squeue_command("cedar", "alice") == "ssh cedar squeue -u alice -r"


def test_build_scp_command():
    assert (
        _build_scp_command("cedar", "/remote/output", "test/output")
        == "scp -r cedar:/remote/output/* test/output/"
    )


# ----- _count_active_jobs -----


def test_count_active_jobs_matches_script_basename_in_lines():
    squeue_output = (
        "JOBID NAME            ST USER\n"
        "1001  submit.sh        R alice\n"
        "1002  submit.sh        PD alice\n"
        "1003  other_script.sh  R alice\n"
        "\n"
    )
    assert _count_active_jobs(squeue_output, "submit.sh") == 2


def test_count_active_jobs_returns_zero_on_empty_output():
    assert _count_active_jobs("", "submit.sh") == 0


# ----- Submitter end-to-end via mocked _run_command -----


class FakeRunner:
    """Records every command and returns canned responses keyed by substring."""

    def __init__(self, responses):
        self.calls = []
        self.responses = responses
        self.queue_iter = iter(responses.get("squeue_sequence", []))

    def __call__(self, cmd):
        # NOTE: monkeypatch assigns this instance as a class attribute on
        # Submitter, so attribute access does NOT bind `self` like a function
        # would. The submitter calls us as `runner(cmd)`, not `runner(self, cmd)`.
        self.calls.append(cmd)
        if "whoami" in cmd:
            return self.responses.get("whoami", "alice") + "\n"
        if "squeue" in cmd:
            try:
                return next(self.queue_iter)
            except StopIteration:
                return ""
        # sbatch / scp / mkdir / git: empty stdout matches typical reality
        return ""


@pytest.fixture
def submitter_with_runner(monkeypatch):
    def factory(runner, **overrides):
        clusters = [
            {
                "name": "cedar",
                "capacity": 3,
                "account": "def-sutton",
                "project_root_dir": "/home/alice/proj",
                "exp_results_from": ["/home/alice/proj/test/output"],
                "exp_results_to": ["test/output"],
            }
        ]
        kwargs = {
            "clusters": clusters,
            "job_list": [(1, 3)],
            "script_path": "test/submit.sh",
            "export_params": {"k": "v"},
            "sbatch_params": {"time": "00:10:00"},
            "duration_between_two_polls": 0,
        }
        kwargs.update(overrides)
        monkeypatch.setattr(Submitter, "_run_command", runner)
        return Submitter(**kwargs)

    return factory


def test_submitter_init_runs_mkdir_for_each_results_path(
    monkeypatch, submitter_with_runner
):
    runner = FakeRunner({})
    submitter_with_runner(runner)
    assert "ssh cedar 'mkdir -p /home/alice/proj/test/output'" in runner.calls
    assert "mkdir -p test/output" in runner.calls


def test_submitter_init_skips_git_when_repo_url_is_none(submitter_with_runner):
    runner = FakeRunner({})
    submitter_with_runner(runner)
    assert not any("git" in c for c in runner.calls)


def test_submitter_init_invokes_git_clone_when_repo_url_given(submitter_with_runner):
    runner = FakeRunner({})
    submitter_with_runner(runner, repo_url="https://example.com/repo.git")
    git_calls = [c for c in runner.calls if "git " in c]
    assert len(git_calls) == 1
    assert "git clone https://example.com/repo.git proj" in git_calls[0]
    assert "git pull origin master" in git_calls[0]


def test_submit_happy_path_drains_queue_and_copies_results(
    monkeypatch, submitter_with_runner
):
    # squeue responses: empty → submit jobs; full once → wait; empty → done.
    runner = FakeRunner(
        {
            "squeue_sequence": [
                "JOBID NAME ST\n",  # iteration 1: 0 active → submit 1-3
                "1 submit.sh R alice\n2 submit.sh R alice\n3 submit.sh R alice\n",
                "JOBID NAME ST\n",  # iteration 3: 0 active again → copy results
            ]
        }
    )
    submitter = submitter_with_runner(runner)
    submitter.submit()

    # Expected: one whoami, multiple squeue, one sbatch, one scp, no infinite loop.
    assert any("whoami" in c for c in runner.calls)
    sbatches = [c for c in runner.calls if "sbatch" in c]
    assert len(sbatches) == 1
    assert "--array=1-3" in sbatches[0]
    assert "--account=def-sutton" in sbatches[0]
    assert "--time=00:10:00" in sbatches[0]
    assert "--export=k=v" in sbatches[0]
    assert "scp -r cedar:/home/alice/proj/test/output/* test/output/" in runner.calls
