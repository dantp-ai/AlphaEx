FROM debian:bullseye-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        slurm-wlm \
        munge \
        openssh-server \
        python3 \
        python3-venv \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd \
    && ssh-keygen -A \
    && useradd --create-home --uid 1000 --shell /bin/bash alphaex \
    && mkdir -p /var/spool/slurmctld /var/spool/slurmd /var/log/slurm \
    && chown slurm:slurm /var/spool/slurmctld /var/spool/slurmd /var/log/slurm

COPY slurm.conf /etc/slurm/slurm.conf
COPY cgroup.conf /etc/slurm/cgroup.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
