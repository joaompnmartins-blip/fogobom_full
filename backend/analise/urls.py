from django.urls import path
from . import views

app_name = 'analise'

urlpatterns = [
    path('estatisticas/',                            views.stats_page,     name='stats'),
    path('estatisticas/execucoes.csv',               views.executions_csv, name='executions_csv'),
    path('gis/',                                     views.gis_page,       name='gis'),
    path('gis/parcelas.<str:fmt>',                   views.gis_parcels,    name='gis_parcels'),
    path('gis/areas-tratadas.<str:fmt>',             views.gis_executions, name='gis_executions'),
    path('gis/execucao/<int:plan_pk>.<str:fmt>',     views.gis_plan,       name='gis_plan'),
    path('gis/pfc/<int:pfc_pk>.<str:fmt>',           views.gis_pfc,        name='gis_pfc'),
]
