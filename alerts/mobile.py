"""Compatibility alias for :mod:`alerts.views.mobile.dashboard`."""

import sys

from .views.mobile import dashboard as _module

sys.modules[__name__] = _module
