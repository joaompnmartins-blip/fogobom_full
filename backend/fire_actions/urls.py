from django.urls import path
from . import views

app_name = 'fire_actions'

urlpatterns = [
    # Ações
    path('',                                views.preplan_list,         name='list'),
    path('proximas/',                       views.announcements,        name='announcements'),
    path('<int:pk>/estado/',               views.action_status,         name='status'),
    path('<int:pk>/participar/',           views.participate,           name='participate'),
    path('<int:pk>/participantes/<int:part_pk>/', views.participant_decision, name='participant_decision'),
    path('<int:pk>/comunicacao/',          views.action_communication,  name='communication'),
    path('<int:pk>/calendario.ics',        views.action_ics,            name='ics'),
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
