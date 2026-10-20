from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('',              views.dashboard,    name='dashboard'),
    path('login/',        views.login_view,   name='login'),
    path('logout/',       views.logout_view,  name='logout'),
    path('password/recuperar/',          views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('password/recuperar/enviado/',
         auth_views.PasswordResetDoneView.as_view(template_name='core/password_reset_done.html'),
         name='password_reset_done'),
    path('password/repor/<uidb64>/<token>/', views.PasswordResetConfirm.as_view(), name='password_reset_confirm'),
    path('password/repor/concluido/',
         auth_views.PasswordResetCompleteView.as_view(template_name='core/password_reset_complete.html'),
         name='password_reset_complete'),
    path('calendario/',   views.calendario,   name='calendario'),
    path('meteorologia/',                       views.meteorologia,  name='meteorologia'),
    path('utilizadores/pendentes/',             views.pending_users, name='pending_users'),
    path('utilizadores/<int:user_id>/aprovar/', views.approve_user,  name='approve_user'),
    path('utilizadores/<int:user_id>/recusar/', views.decline_user,  name='decline_user'),
]
