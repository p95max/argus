# Argus systemd operations

These unit files mirror the production VPS services and timers. Keep them in the repository as deploy templates, then install them into `/etc/systemd/system`.

Install or update on the server:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

The installer copies `deploy/scripts/argus-*` into `/usr/local/bin`, reloads systemd, enables the web and Telegram bot services, and enables all Argus timers.

Check all Argus timers:

```bash
systemctl list-timers --all | grep argus
```

Run the operational doctor:

```bash
/usr/local/bin/argus-doctor.sh
```

Expected managed helper scripts:

```text
/usr/local/bin/argus-auto-deploy.sh
/usr/local/bin/argus-backup-db.sh
/usr/local/bin/argus-health-notify.py
/usr/local/bin/argus-doctor.sh
```

Database restore instructions live in `deploy/ops-restore.md`.
