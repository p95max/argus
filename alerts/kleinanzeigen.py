"""Compatibility alias for :mod:`alerts.services.kleinanzeigen`."""

import sys

from .services import kleinanzeigen as _module

sys.modules[__name__] = _module
