# Argus systemd timers

These unit files mirror the production VPS timers. Keep them in the repository as deploy templates, then install them into `/etc/systemd/system`.

Install or update on the server:

```bash
cd /opt/argus
sudo cp deploy/systemd/argus-*.service deploy/systemd/argus-*.timer /etc/systemd/system/
sudo cp deploy/scripts/argus-* /usr/local/bin/
sudo chmod +x /usr/local/bin/argus-*
sudo systemctl daemon-reload
sudo systemctl enable --now \
  argus-check-gmail.timer \
  argus-unread-reminders.timer \
  argus-cleanup-old-leads.timer \
  argus-auto-deploy.timer \
  argus-health-monitor.timer
```

Check all Argus timers:

```bash
systemctl list-timers --all | grep argus
```

The health monitor service expects `/usr/local/bin/argus-health-notify.py` to exist on the server. The backup helper is installed as `/usr/local/bin/argus-backup-db.sh`.
