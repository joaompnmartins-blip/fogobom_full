from django.urls import path
from . import views

app_name = 'pfc'

urlpatterns = [
    path('',                                   views.pfc_list,      name='list'),
    path('novo/',                              views.pfc_create,    name='create'),
    path('<int:pk>/',                          views.pfc_detail,    name='detail'),
    path('<int:pk>/editar/',                   views.pfc_edit,      name='edit'),
    path('<int:pk>/estado/',                   views.pfc_status,    name='status'),
    path('<int:pk>/documento.docx',            views.pfc_docx,      name='docx'),
    path('<int:pk>/parcelas/nova/',            views.parcel_edit,   name='parcel_add'),
    path('<int:pk>/parcelas/<int:pp_pk>/',     views.parcel_edit,   name='parcel_edit'),
    path('<int:pk>/parcelas/<int:pp_pk>/retirar/', views.parcel_remove, name='parcel_remove'),
]
