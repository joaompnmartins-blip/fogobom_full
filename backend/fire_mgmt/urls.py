from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/',        admin.site.urls),
    path('',              include('core.urls',         namespace='core')),
    path('parcelas/',     include('parcelas.urls',     namespace='parcelas')),
    path('operacionais/', include('operatives.urls',   namespace='operatives')),
    path('acoes/',        include('fire_actions.urls', namespace='fire_actions')),
    path('pfc/',          include('pfc.urls',          namespace='pfc')),
    path('monitorizacao/', include('monitorizacao.urls', namespace='monitorizacao')),
    path('',              include('registos.urls',     namespace='registos')),
    path('',              include('analise.urls',      namespace='analise')),
    # Old URLs (/preplan/...) keep working
    re_path(r'^preplan/(?P<rest>.*)$', lambda request, rest: redirect(f'/acoes/{rest}', permanent=True)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
