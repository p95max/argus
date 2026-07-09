import hashlib
import ipaddress

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse


class AdminLoginRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_admin_login_post(request) and self._is_locked(request):
            return HttpResponse(
                "Too many failed login attempts. Try again later.",
                status=429,
            )

        response = self.get_response(request)

        if self._is_admin_login_post(request):
            if response.status_code == 302:
                self._reset(request)
            elif response.status_code == 200:
                self._increment(request)

        return response

    def _is_admin_login_post(self, request):
        admin_path = f"/{settings.DJANGO_ADMIN_URL}/login/"
        return request.method == "POST" and request.path == admin_path

    def _is_locked(self, request):
        return self._failures(request) >= settings.ADMIN_LOGIN_FAILURE_LIMIT

    def _increment(self, request):
        key = self._cache_key(request)
        failures = self._failures(request) + 1
        cache.set(key, failures, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)

    def _reset(self, request):
        cache.delete(self._cache_key(request))

    def _failures(self, request):
        return int(cache.get(self._cache_key(request), 0))

    def _cache_key(self, request):
        username = request.POST.get("username", "").strip().lower()
        ip_address = _client_ip(request)
        raw_key = f"{ip_address}:{username}".encode("utf-8")
        digest = hashlib.sha256(raw_key).hexdigest()
        return f"argus:admin-login-failures:{digest}"


def _client_ip(request):
    remote_addr = _clean_ip_value(request.META.get("REMOTE_ADDR", ""))
    trusted_proxies = getattr(settings, "ADMIN_LOGIN_TRUSTED_PROXY_IPS", [])
    if not _is_trusted_proxy(remote_addr, trusted_proxies):
        return remote_addr

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    forwarded_chain = [
        _clean_ip_value(item)
        for item in forwarded_for.split(",")
        if _clean_ip_value(item)
    ]
    for ip_address in reversed(forwarded_chain):
        if not _is_trusted_proxy(ip_address, trusted_proxies):
            return ip_address

    return remote_addr


def _clean_ip_value(value):
    return str(value or "").strip()


def _is_trusted_proxy(ip_address, trusted_proxies):
    if not ip_address or not trusted_proxies:
        return False

    try:
        parsed_ip = ipaddress.ip_address(ip_address)
    except ValueError:
        return False

    for proxy in trusted_proxies:
        try:
            trusted_network = ipaddress.ip_network(str(proxy).strip(), strict=False)
        except ValueError:
            continue
        if parsed_ip in trusted_network:
            return True

    return False
