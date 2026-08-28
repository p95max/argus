"""Compatibility alias for :mod:`alerts.services.attention`."""

import sys

from .services import attention as _module

sys.modules[__name__] = _module
