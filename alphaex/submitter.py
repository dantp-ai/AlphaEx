#######################################################################
# Copyright (C) 2019 Yi Wan(wan6@ualberta.ca)                         #
# Permission given to modify the code as long as you keep this        #
# declaration at the top                                              #
#######################################################################
import subprocess
import time
from pathlib import Path

_REQUIRED_CLUSTER_KEYS = ("name", "capacity", "account", "project_root_dir")


def _normalize_job_list(job_list):
    """Convert bare ints in ``job_list`` to ``(n, n)`` tuples in place.

    Tuples pass through unchanged. Asserts ``job_list`` is non-empty.
    Returns the same list, mutated.
    """
    assert len(job_list) != 0
    for i, item in enumerate(job_list):
        if isinstance(item, int):
            job_list[i] = (item, item)
    return job_list


def _validate_cluster(cluster):
    """Validate a cluster config dict and default ``exp_results_*`` to ``[]``.

    Raises ``ValueError`` on a missing required key, a length mismatch
    between ``exp_results_from`` and ``exp_results_to``, or a partial
    specification (only one of the two). Returns the same dict, possibly
    mutated.
    """
    for key in _REQUIRED_CLUSTER_KEYS:
        if key not in cluster:
            raise ValueError(f"required cluster key {key!r} missing from {cluster!r}")

    has_from = "exp_results_from" in cluster
    has_to = "exp_results_to" in cluster
    if has_from and has_to:
        if len(cluster["exp_results_from"]) != len(cluster["exp_results_to"]):
            raise ValueError(
                "exp_results_from and exp_results_to must have the same length"
            )
    elif has_from != has_to:
        raise ValueError(
            "exp_results_from and exp_results_to must be both specified or both omitted"
        )
    else:
        cluster["exp_results_from"] = []
        cluster["exp_results_to"] = []
    return cluster


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
    """Build the ``ssh <name> 'cd <dir>; sbatch ...'`` string."""
    arg_export = ",".join(f"{k}={v}" for k, v in export_params.items())
    arg_opt_sbatch = " ".join(f"--{k}={v}" for k, v in sbatch_params.items())
    cmd = (
        f"ssh {cluster_name} "
        f"'cd {project_root_dir}; "
        f"sbatch "
        f"--array={job_array_string} "
        f"--account={account} "
        f"{arg_opt_sbatch} "
        f"--export={arg_export} "
        f"{script_path}'"
    )
    return " ".join(cmd.split())


def _build_squeue_command(cluster_name, username):
    return f"ssh {cluster_name} squeue -u {username} -r"


def _build_scp_command(cluster_name, remote_path, local_path):
    return f"scp -r {cluster_name}:{remote_path}/* {local_path}/"


def _count_active_jobs(squeue_output, script_basename):
    """Count lines in ``squeue_output`` containing ``script_basename``."""
    return sum(1 for line in squeue_output.split("\n") if script_basename in line)


class Submitter:
    """
    Create a job submitter and which will ssh to clusters and submit slurm array jobs.

    Args:
        clusters (list): clusters information
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

    The clusters information is stored in a list of dictionaries.

    Each dictionary must contain 4 fields:

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
    ):
        if sbatch_params is None:
            sbatch_params = {}
        if export_params is None:
            export_params = {}
        for cluster in clusters:
            _validate_cluster(cluster)

        if repo_url is not None:
            for cluster in clusters:
                root_dir = cluster["project_root_dir"]
                root_path = "/".join(root_dir.split("/")[:-1])
                project_name = root_dir.split("/")[-1]
                self._run_command(
                    f"ssh {cluster['name']} 'if [ -d {root_dir} ]; "
                    f"then cd {root_dir}; git pull origin master; "
                    f"else cd {root_path}; git clone {repo_url} {project_name}; fi'"
                )

        for cluster in clusters:
            for remote_path, local_path in zip(
                cluster["exp_results_from"], cluster["exp_results_to"]
            ):
                self._run_command(f"ssh {cluster['name']} 'mkdir -p {remote_path}'")
                self._run_command(f"mkdir -p {local_path}")

        self.clusters = clusters.copy()
        self.script_path = script_path
        self.duration_between_two_polls = duration_between_two_polls
        self.export_params = export_params
        self.sbatch_params = sbatch_params
        self.job_list = _normalize_job_list(job_list)
        self.starting_job_list_index = 0
        self.starting_job_num = self.job_list[0][0]

    def _run_command(self, cmd):
        """Single seam wrapping subprocess so tests can mock it.

        Mirrors ``os.popen(cmd).read()`` semantics: captures stdout (returned
        as text) and lets stderr inherit so failures stay visible.
        """
        print(cmd)
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True)
        print(result.stdout, end="")
        return result.stdout

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
        self._run_command(cmd)
        print(f"submit job array {job_array_string} to {cluster_name}.")

    def submit(self):
        for cluster in self.clusters:
            output = self._run_command(f"ssh {cluster['name']} whoami")
            cluster["username"] = output.split("\n")[0]

        finish_submitting = False
        temp_clusters = self.clusters.copy()
        script_basename = self.script_path.split("/")[-1]
        while True:
            for cluster in temp_clusters[:]:
                output = self._run_command(
                    _build_squeue_command(cluster["name"], cluster["username"])
                )
                num_current_jobs = _count_active_jobs(output, script_basename)
                print(f"cluster {cluster['name']} has {num_current_jobs} jobs")

                if finish_submitting:
                    if num_current_jobs == 0:
                        for remote_path, local_path in zip(
                            cluster["exp_results_from"], cluster["exp_results_to"]
                        ):
                            Path(local_path).mkdir(parents=True, exist_ok=True)
                            self._run_command(
                                _build_scp_command(
                                    cluster["name"], remote_path, local_path
                                )
                            )
                        temp_clusters.remove(cluster)
                    if len(temp_clusters) == 0:
                        print("Finish all experimental results copying.\nDone\n")
                        return
                elif num_current_jobs < cluster["capacity"]:
                    array_string, new_idx, new_num, just_finished = (
                        _build_job_array_string(
                            self.job_list,
                            self.starting_job_list_index,
                            self.starting_job_num,
                            cluster["capacity"],
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
                        cluster["name"],
                        cluster["account"],
                        cluster["project_root_dir"],
                    )

            time.sleep(self.duration_between_two_polls)
