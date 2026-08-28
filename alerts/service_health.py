"""Compatibility alias for :mod:`alerts.services.service_health`."""

import sys

from .services import service_health as _module

sys.modules[__name__] = _module
