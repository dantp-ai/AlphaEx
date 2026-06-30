#######################################################################
# Copyright (C) 2019 Yi Wan(wan6@ualberta.ca)                         #
# Permission given to modify the code as long as you keep this        #
# declaration at the top                                              #
#######################################################################
import shlex
import subprocess
import time
from dataclasses import dataclass, fields
from pathlib import Path

_REQUIRED_CLUSTER_KEYS = ("name", "capacity", "account", "project_root_dir")


@dataclass(frozen=True)
class Cluster:
    """Immutable description of one cluster the submitter targets.

    Construct directly, or from a config dict via :meth:`from_dict` (which the
    ``Submitter`` applies to any dict it is handed). Frozen so a cluster's
    config can never be mutated by the orchestration loop; per-run state such as
    the resolved SSH username lives in the ``Submitter``, not here (issue #42).

    ``exp_results_from`` and ``exp_results_to`` are parallel sequences: once a
    cluster drains, results at each remote path are copied to the corresponding
    local path.
    """

    name: str
    capacity: int
    account: str
    project_root_dir: str
    exp_results_from: tuple = ()
    exp_results_to: tuple = ()

    def __post_init__(self):
        if len(self.exp_results_from) != len(self.exp_results_to):
            raise ValueError(
                "exp_results_from and exp_results_to must have the same length"
            )

    @classmethod
    def from_dict(cls, cluster):
        """Build a ``Cluster`` from a config dict without mutating it (issue #42).

        Raises ``ValueError`` on an unknown key (likely a typo), a missing
        required key, or a one-sided ``exp_results_*`` specification.
        """
        allowed = {f.name for f in fields(cls)}
        unknown = set(cluster) - allowed
        if unknown:
            raise ValueError(f"unknown cluster key(s) {sorted(unknown)} in {cluster!r}")
        for key in _REQUIRED_CLUSTER_KEYS:
            if key not in cluster:
                raise ValueError(
                    f"required cluster key {key!r} missing from {cluster!r}"
                )
        has_from = "exp_results_from" in cluster
        has_to = "exp_results_to" in cluster
        if has_from != has_to:
            raise ValueError(
                "exp_results_from and exp_results_to must be both specified "
                "or both omitted"
            )
        return cls(
            name=cluster["name"],
            capacity=cluster["capacity"],
            account=cluster["account"],
            project_root_dir=cluster["project_root_dir"],
            exp_results_from=tuple(cluster.get("exp_results_from", ())),
            exp_results_to=tuple(cluster.get("exp_results_to", ())),
        )


def _normalize_job_list(job_list):
    """Return a new job list with bare ints promoted to ``(n, n)`` tuples.

    Tuples pass through unchanged. The input list is not mutated (issue #42).
    Asserts ``job_list`` is non-empty.
    """
    assert len(job_list) != 0
    return [(item, item) if isinstance(item, int) else item for item in job_list]


def _build_job_array_string(
    job_list, starting_idx, starting_num, capacity, current_jobs
):
    """Greedily fill one cluster's remaining capacity from ``job_list``.

    ``job_list`` is a normalized list of ``(start, end)`` tuples (inclusive).
    ``starting_idx`` is the index of the tuple to begin at; ``starting_num``
    is the first id to submit inside that tuple. ``capacity`` and
    ``current_jobs`` describe the cluster's max and currently-queued counts.

    Returns ``(array_string, new_starting_idx, new_starting_num,
    finish_submitting)``. ``array_string`` has no leading comma; it is
    empty when no jobs can be scheduled. ``finish_submitting`` is ``True``
    iff every tuple in ``job_list`` has been consumed.
    """
    parts = []
    finish_submitting = False
    available = capacity - current_jobs
    idx = starting_idx
    num = starting_num
    while idx < len(job_list):
        end = job_list[idx][1]
        assert end >= num
        chunk_size = end - num + 1
        if chunk_size <= available:
            parts.append(f"{num}-{end}")
            available -= chunk_size
            current_jobs += chunk_size
            idx += 1
            if idx == len(job_list):
                finish_submitting = True
                break
            num = job_list[idx][0]
        else:
            if available > 0:
                last_end = num + available - 1
                parts.append(f"{num}-{last_end}")
                num += available
            break
    return ",".join(parts), idx, num, finish_submitting


def _build_sbatch_command(
    cluster_name,
    project_root_dir,
    job_array_string,
    account,
    sbatch_params,
    export_params,
    script_path,
):
    """Build the ``["ssh", <name>, "cd <dir> && sbatch ..."]`` argv list.

    The ``ssh`` invocation is an argv list, so no local shell is involved. The
    remote command (the third element) is a shell string run by the cluster's
    own shell; interpolated paths are ``shlex.quote``d so a path with spaces
    stays a single token (issue #15).
    """
    arg_export = ",".join(f"{k}={v}" for k, v in export_params.items())
    parts = [
        f"cd {shlex.quote(project_root_dir)}",
        "&&",
        "sbatch",
        f"--array={job_array_string}",
        f"--account={account}",
    ]
    parts += [f"--{k}={v}" for k, v in sbatch_params.items()]
    parts.append(f"--export={arg_export}")
    parts.append(shlex.quote(script_path))
    return ["ssh", cluster_name, " ".join(parts)]


def _build_squeue_command(cluster_name, username):
    return ["ssh", cluster_name, "squeue", "-u", username, "-r"]


def _build_scp_command(cluster_name, remote_path, local_path):
    return ["scp", "-r", f"{cluster_name}:{remote_path}/*", f"{local_path}/"]


def _count_active_jobs(squeue_output, script_basename):
    """Count lines in ``squeue_output`` containing ``script_basename``."""
    return sum(1 for line in squeue_output.split("\n") if script_basename in line)


def _build_git_sync_command(cluster_name, root_dir, repo_url):
    """Build the ssh command that ensures the project repo is up to date on a cluster.

    If ``root_dir`` exists on the cluster the working tree is hard-reset to the
    remote's current default branch (resolved via ``origin/HEAD``). This sidesteps
    the legacy ``git pull origin master`` form, which silently no-ops on every
    ``main``-default repo (issue #14).

    If ``root_dir`` does not exist it is created by cloning ``repo_url`` into
    ``<root_dir>/..``; the clone implicitly checks out the remote's default branch.

    The reset is destructive of any cluster-side local changes — a conscious
    trade-off for "the cluster should mirror the remote".
    """
    root_path, _, project_name = root_dir.rpartition("/")
    root_dir_q = shlex.quote(root_dir)
    root_path_q = shlex.quote(root_path)
    repo_url_q = shlex.quote(repo_url)
    project_name_q = shlex.quote(project_name)
    update = (
        f"cd {root_dir_q} "
        "&& git fetch origin "
        "&& git remote set-head origin --auto "
        "&& git reset --hard origin/HEAD"
    )
    clone = f"cd {root_path_q} && git clone {repo_url_q} {project_name_q}"
    remote_cmd = f"if [ -d {root_dir_q} ]; then {update}; else {clone}; fi"
    return ["ssh", cluster_name, remote_cmd]


class Submitter:
    """
    Create a job submitter and which will ssh to clusters and submit slurm array jobs.

    Args:
        clusters (list): ``Cluster`` instances or config dicts (each coerced
            via ``Cluster.from_dict``) describing the target clusters
        job_list (list): list of ints / (start, end) tuples describing
            slurm array indices to submit
        script_path (str): the slurm array job submission script in the experiment
            project
        export_params (dict): containing arguments and their respective values
            that can be passed to slurm jobs.
        sbatch_params (dict): containing SBATCH arguments and
            their respective values that can be passed to slurm jobs. Alternatively,
            these arguments can be passed in the slurm script at the top of the file,
            e.g. '#SBATCH --time=00:10:00'. See the sbatch documentation
            for more details https://slurm.schedmd.com/sbatch.html)
        duration_between_two_polls (int): duration between two polls in seconds.
            Default value is 60.
        repo_url (str): experiment code's git repo url. If this is not provided,
            the user needs to copy experiment code to each cluster manually.
            When provided, each cluster's checkout is hard-reset to the remote's
            current default branch — see ``_build_git_sync_command`` for the
            destructive-update semantics.
        max_polls (int): maximum number of poll cycles ``submit()`` may run
            before raising ``RuntimeError``. ``None`` (the default) means
            unbounded. Use this to guard against stuck clusters that never
            drain.

    Each entry is a ``Cluster`` instance, or a dict coerced via
    ``Cluster.from_dict`` that must contain 4 fields:

    name (str): the name of your remote cluster, it should be defined in .ssh/config
    of the server.

    capacity (int): maximum number of jobs you want to run in that cluster, usually
    each cluster provides this information in its user manual.

    account (str): the account name, for example, def-sutton, rrg-whitem.

    project_root_dir (str): the root directory containing the project in the cluster.
    If repo_url is not None, then submitter
    will clone/pull codebase from github to this directory. Otherwise the user must
    copy experiment code to this directory manually.

    2 Additional fields are optional:

    exp_results_from (list): a list of experiment results paths in the cluster

    exp_results_to (list): a list of paths where experiment results will be copied to

    """

    def __init__(
        self,
        clusters,
        job_list,
        script_path,
        export_params=None,
        sbatch_params=None,
        duration_between_two_polls=60,
        repo_url=None,
        max_polls=None,
    ):
        if sbatch_params is None:
            sbatch_params = {}
        if export_params is None:
            export_params = {}
        self.clusters = [
            c if isinstance(c, Cluster) else Cluster.from_dict(c) for c in clusters
        ]

        if repo_url is not None:
            for cluster in self.clusters:
                self._run_command(
                    _build_git_sync_command(
                        cluster.name, cluster.project_root_dir, repo_url
                    ),
                    check=True,
                )

        for cluster in self.clusters:
            for remote_path, local_path in zip(
                cluster.exp_results_from, cluster.exp_results_to
            ):
                self._run_command(
                    ["ssh", cluster.name, f"mkdir -p {shlex.quote(remote_path)}"],
                    check=True,
                )
                self._run_command(["mkdir", "-p", local_path], check=True)

        self.script_path = script_path
        self.duration_between_two_polls = duration_between_two_polls
        self.export_params = export_params
        self.sbatch_params = sbatch_params
        self.job_list = _normalize_job_list(job_list)
        self.starting_job_list_index = 0
        self.starting_job_num = self.job_list[0][0]
        self.max_polls = max_polls

    def _run_command(self, cmd, check=False):
        """Single seam wrapping subprocess so tests can mock it.

        ``cmd`` is an argv list run with ``shell=False`` (issue #15): no local
        shell ever interprets the interpolated cluster names, paths, or account
        names, removing the shell-injection category of bug. Commands that need
        remote shell features (the git-sync heredoc, the ``cd <dir> && sbatch``
        chain) are passed as ``["ssh", <name>, "<remote shell string>"]`` whose
        remote string already ``shlex.quote``s its interpolated paths.

        Captures both stdout and stderr as text and prints them to keep the
        live-tail UX of the previous ``os.popen`` form. ``stdout`` is returned;
        callers that need ``stderr`` go through the raised exception below.

        When ``check`` is ``True`` and the command's return code is non-zero,
        raises ``subprocess.CalledProcessError`` carrying stdout and stderr.
        This is how the orchestrator turns a failed ``sbatch`` / ``scp`` / ssh
        into a loud failure instead of a silent no-op (issue #12).
        """
        print(shlex.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )
        return result.stdout

    def _sleep(self, seconds):
        """Single seam wrapping ``time.sleep`` so tests can mock it.

        Mirrors the ``_run_command`` seam pattern: production sleeps; tests
        monkeypatch the class attribute to drive the polling loop
        deterministically without real wall-clock delay.
        """
        time.sleep(seconds)

    def submit_jobs(self, job_array_string, cluster_name, account, project_root_dir):
        cmd = _build_sbatch_command(
            cluster_name,
            project_root_dir,
            job_array_string,
            account,
            self.sbatch_params,
            self.export_params,
            self.script_path,
        )
        self._run_command(cmd, check=True)
        print(f"submit job array {job_array_string} to {cluster_name}.")

    def submit(self):
        usernames = {}
        for cluster in self.clusters:
            output = self._run_command(["ssh", cluster.name, "whoami"], check=True)
            usernames[cluster.name] = output.split("\n")[0]

        finish_submitting = False
        temp_clusters = self.clusters.copy()
        script_basename = self.script_path.split("/")[-1]
        polls = 0
        while True:
            for cluster in temp_clusters[:]:
                output = self._run_command(
                    _build_squeue_command(cluster.name, usernames[cluster.name]),
                    check=True,
                )
                num_current_jobs = _count_active_jobs(output, script_basename)
                print(f"cluster {cluster.name} has {num_current_jobs} jobs")

                if finish_submitting:
                    if num_current_jobs == 0:
                        for remote_path, local_path in zip(
                            cluster.exp_results_from, cluster.exp_results_to
                        ):
                            Path(local_path).mkdir(parents=True, exist_ok=True)
                            self._run_command(
                                _build_scp_command(
                                    cluster.name, remote_path, local_path
                                ),
                                check=True,
                            )
                        temp_clusters.remove(cluster)
                    if len(temp_clusters) == 0:
                        print("Finish all experimental results copying.\nDone\n")
                        return
                elif num_current_jobs < cluster.capacity:
                    array_string, new_idx, new_num, just_finished = (
                        _build_job_array_string(
                            self.job_list,
                            self.starting_job_list_index,
                            self.starting_job_num,
                            cluster.capacity,
                            num_current_jobs,
                        )
                    )
                    self.starting_job_list_index = new_idx
                    self.starting_job_num = new_num
                    if just_finished:
                        finish_submitting = True
                    print("submit jobs " + array_string)
                    if finish_submitting:
                        print("Finish submitting all jobs")
                    self.submit_jobs(
                        array_string,
                        cluster.name,
                        cluster.account,
                        cluster.project_root_dir,
                    )

            polls += 1
            if self.max_polls is not None and polls >= self.max_polls:
                raise RuntimeError(
                    f"submit() exceeded max_polls={self.max_polls} without "
                    f"draining; {len(temp_clusters)} cluster(s) still active"
                )
            self._sleep(self.duration_between_two_polls)
