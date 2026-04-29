from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('',              views.dashboard,    name='dashboard'),
    path('login/',        views.login_view,   name='login'),
    path('logout/',       views.logout_view,  name='logout'),
    path('calendario/',   views.calendario,   name='calendario'),
    path('meteorologia/',                       views.meteorologia,  name='meteorologia'),
    path('utilizadores/pendentes/',             views.pending_users, name='pending_users'),
    path('utilizadores/<int:user_id>/aprovar/', views.approve_user,  name='approve_user'),
    path('utilizadores/<int:user_id>/recusar/', views.decline_user,  name='decline_user'),
]
