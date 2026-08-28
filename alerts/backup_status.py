"""Compatibility alias for :mod:`alerts.monitoring.backup_status`."""

import sys

from .monitoring import backup_status as _module

sys.modules[__name__] = _module
