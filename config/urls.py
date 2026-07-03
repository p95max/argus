from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from django.conf import settings


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('health/', health_check, name='health'),
    path(f'{settings.DJANGO_ADMIN_URL}/', admin.site.urls),
]
