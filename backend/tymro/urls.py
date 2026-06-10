from django.contrib import admin
from django.urls import include, path, re_path
from django.conf import settings
from django.views.generic import TemplateView
from django.views.static import serve as static_serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
]

# Media: servida por Django también en producción (Railway monta un Volume en
# MEDIA_ROOT). Se registra explícitamente porque django.conf.urls.static.static()
# solo devuelve patrones cuando DEBUG=True.
urlpatterns += [
    re_path(
        r'^media/(?P<path>.*)$',
        static_serve,
        {'document_root': settings.MEDIA_ROOT},
    ),
]

# Catch-all del SPA: cualquier ruta que NO sea api/, admin/, static/ o media/
# devuelve index.html para que React Router resuelva el ruteo en el cliente.
# (Los estáticos —/static/ y /assets/— los intercepta WhiteNoise antes de llegar aquí.)
urlpatterns += [
    re_path(
        r'^(?!api/|admin/|static/|media/).*$',
        TemplateView.as_view(template_name='index.html'),
        name='spa',
    ),
]
