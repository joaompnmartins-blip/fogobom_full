from django.urls import path
from . import views

app_name = 'monitorizacao'

urlpatterns = [
    path('',                                 views.monitoring_list,   name='list'),
    path('nova/<int:ex_pk>/',                views.assessment_create, name='create'),
    path('dispensar/<int:ex_pk>/',          views.visit_waive,       name='waive'),
    path('<int:pk>/',                        views.assessment_detail, name='detail'),
    path('<int:pk>/editar/',                 views.assessment_edit,   name='edit'),
    path('<int:pk>/eliminar/',               views.assessment_delete, name='delete'),
    path('parcela/<int:parcel_pk>/criterios/', views.criteria_edit,   name='criteria'),
    path('poq-impacto/<int:plan_pk>/',       views.poq_impacto,       name='poq_impacto'),
]
