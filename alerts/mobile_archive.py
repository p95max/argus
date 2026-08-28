"""Compatibility alias for :mod:`alerts.views.mobile.archive`."""

import sys

from .views.mobile import archive as _module

sys.modules[__name__] = _module
