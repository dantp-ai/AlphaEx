#!/usr/bin/env bash
set -euo pipefail

# Munge runtime dirs (no systemd-tmpfiles to create these for us).
install -d -m 0755 -o munge -g munge /run/munge /var/log/munge /var/lib/munge

# Munge key (per-container; the two clusters are independent).
if [ ! -s /etc/munge/munge.key ]; then
    dd if=/dev/urandom bs=1 count=1024 of=/etc/munge/munge.key 2>/dev/null
fi
chown munge:munge /etc/munge/munge.key
chmod 0400 /etc/munge/munge.key

# Authorized key for the alphaex user (mounted in read-only from the host).
mkdir -p /home/alphaex/.ssh
if [ -f /etc/alphaex_authorized_keys ]; then
    cp /etc/alphaex_authorized_keys /home/alphaex/.ssh/authorized_keys
fi
chmod 700 /home/alphaex/.ssh
chmod 600 /home/alphaex/.ssh/authorized_keys 2>/dev/null || true
chown -R alphaex:alphaex /home/alphaex/.ssh

# Slurm daemons.
runuser -u munge -- /usr/sbin/munged
runuser -u slurm -- /usr/sbin/slurmctld
/usr/sbin/slurmd

# sshd in the foreground so it owns PID 1's signal lifecycle.
exec /usr/sbin/sshd -D -e
