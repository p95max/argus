# Argus systemd timers

These unit files mirror the production VPS timers. Keep them in the repository as deploy templates, then install them into `/etc/systemd/system`.

Install or update on the server:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

Check all Argus timers:

```bash
systemctl list-timers --all | grep argus
```

The health monitor service expects `/usr/local/bin/argus-health-notify.py` to exist on the server. The backup helper is installed as `/usr/local/bin/argus-backup-db.sh`.
