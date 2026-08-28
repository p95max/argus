"""Compatibility alias for :mod:`alerts.views.mobile.service_log`."""

import sys

from .views.mobile import service_log as _module

sys.modules[__name__] = _module
