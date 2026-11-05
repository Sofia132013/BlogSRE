from django.contrib import admin
import mimetypes
import re
from urllib.parse import urlsplit

from django.urls import path, include, re_path
from django.contrib.flatpages import views
from django.conf.urls import handler404, handler500
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import DatabaseError, connections
from django.http import FileResponse, Http404, HttpResponse
from django_prometheus.exports import ExportToDjangoView



handler404 = "posts.views.page_not_found" # noqa
handler500 = "posts.views.server_error" # noqa


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def readyz(request):
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return HttpResponse("database unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def media_file(request, name):
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405)
    try:
        image = default_storage.open(name, "rb")
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return FileResponse(image, content_type=content_type)


urlpatterns = [
    path("metrics", ExportToDjangoView, name="prometheus-metrics"),
    path("healthz/", healthz, name="healthz"),
    path("readyz/", readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("", include("posts.urls")),
    path("auth/", include("users.urls")),
    path("auth/", include("django.contrib.auth.urls")),
    path("about/", include("django.contrib.flatpages.urls")),
]

urlpatterns += [
    path("about-us/", views.flatpage, {"url": "/about-us/"}, name="about"),
    path("terms/", views.flatpage, {"url": "/terms/"}, name="terms"),
    path("about-author/", views.flatpage, {"url": "/about-author/"}, name="author"),
    path("about-spec/", views.flatpage, {"url": "/about-spec/"}, name="spec"),
]
# The URL configuration must follow the startup app registry. Tests may
# temporarily toggle DEBUG without reinstalling apps.
if "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path("__debug__/",
                           include(debug_toolbar.urls)),
                  ] + urlpatterns

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)

media_prefix = urlsplit(settings.MEDIA_URL).path.lstrip("/")
urlpatterns.insert(0, re_path(
    r"^{}(?P<name>.+)$".format(re.escape(media_prefix)),
    media_file, name="media_file",
))
