from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/',        admin.site.urls),
    path('',              include('core.urls',         namespace='core')),
    path('parcelas/',     include('parcelas.urls',     namespace='parcelas')),
    path('operacionais/', include('operatives.urls',   namespace='operatives')),
    path('preplan/',      include('fire_actions.urls', namespace='fire_actions')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
