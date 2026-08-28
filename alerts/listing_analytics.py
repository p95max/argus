"""Compatibility alias for :mod:`alerts.services.listing_analytics`."""

import sys

from .services import listing_analytics as _module

sys.modules[__name__] = _module
