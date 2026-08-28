"""Compatibility alias for :mod:`alerts.views.mobile.listings`."""

import sys

from .views.mobile import listings as _module

sys.modules[__name__] = _module
