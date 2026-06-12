#!/bin/bash
# Short-name variant of test/submit.sh used by the local mini-Slurm test.
# A short basename ("run.sh") survives slurm's default squeue NAME-column
# width so `_count_active_jobs` substring matching keeps working.

#SBATCH --output=test/output/submit_%a.txt
#SBATCH --error=test/error/submit_%a.txt

mkdir -p test/output test/error
export OMP_NUM_THREADS=1

echo "${python_module}" "${SLURM_ARRAY_TASK_ID}" "${config_file}"
python3 -m "${python_module}" "${SLURM_ARRAY_TASK_ID}" "${config_file}"
