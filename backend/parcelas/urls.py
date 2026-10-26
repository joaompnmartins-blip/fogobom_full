from django.urls import path
from . import views

app_name = 'parcelas'

urlpatterns = [
    path('',                    views.parcela_list,       name='list'),
    path('nova/',               views.parcela_create,     name='create'),
    path('<int:pk>/',           views.parcela_detail,     name='detail'),
    path('<int:pk>/editar/',    views.parcela_edit,       name='edit'),
    path('<int:pk>/eliminar/',  views.parcela_delete,     name='delete'),
    path('<int:pk>/avaliar/',   views.evaluation_start,   name='evaluation_start'),
    path('avaliacao/<int:pk>/', views.evaluation_edit,    name='evaluation'),
    path('api/geojson/',        views.parcelas_geojson,   name='geojson'),
    path('api/preview/',        views.parcela_preview,    name='preview'),
    path('api/centroids/',      views.parcelas_centroids, name='centroids'),
]
