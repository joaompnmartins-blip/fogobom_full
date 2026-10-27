from django.urls import path
from . import views

app_name = 'registos'

urlpatterns = [
    path('prazos/',                                  views.deadlines_page, name='deadlines'),
    path('livro-de-campo/',                          views.my_fieldbook,   name='my_fieldbook'),
    path('livro-de-campo/<int:op_pk>/',              views.fieldbook,      name='fieldbook'),
    path('livro-de-campo/<int:op_pk>/icnf.xlsx',     views.fieldbook_xlsx, name='fieldbook_xlsx'),
    path('registos/envio/<int:plan_pk>/',            views.mark_sent,      name='mark_sent'),
    path('registos/equipa/<int:ex_pk>/validar/',     views.validate_team,  name='validate_team'),
]
