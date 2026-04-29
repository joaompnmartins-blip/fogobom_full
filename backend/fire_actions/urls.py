from django.urls import path
from . import views

app_name = 'fire_actions'

urlpatterns = [
    # Pré-Planos
    path('',                                views.preplan_list,         name='list'),
    path('novo/',                           views.preplan_create,       name='create'),
    path('<int:pk>/',                       views.preplan_detail,       name='detail'),
    path('<int:pk>/editar/',               views.preplan_edit,          name='edit'),
    path('<int:pk>/eliminar/',             views.preplan_delete,        name='delete'),

    # Planos de Queima
    path('burning/',                        views.burning_plan_list,    name='burning_plan_list'),
    path('burning/novo/',                   views.burning_plan_create,  name='burning_plan_create'),
    path('burning/novo/<int:preplan_pk>/',  views.burning_plan_create,  name='burning_plan_create_from'),
    path('burning/<int:pk>/',              views.burning_plan_detail,   name='burning_plan_detail'),
    path('burning/<int:pk>/editar/',       views.burning_plan_edit,     name='burning_plan_edit'),
    path('burning/<int:pk>/eliminar/',     views.burning_plan_delete,   name='burning_plan_delete'),
    path('burning/<int:pk>/relatorio/',    views.burning_plan_report,   name='burning_plan_report'),
]
