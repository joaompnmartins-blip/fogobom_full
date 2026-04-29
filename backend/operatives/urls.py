from django.urls import path
from . import views

app_name = 'operatives'

urlpatterns = [
    path('',                   views.operative_list,   name='list'),
    path('novo/',              views.operative_create, name='create'),
    path('<int:pk>/editar/',   views.operative_edit,   name='edit'),
    path('<int:pk>/eliminar/', views.operative_delete, name='delete'),
]
