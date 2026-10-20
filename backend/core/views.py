import logging
import threading
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.conf import settings
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import staff_required

logger = logging.getLogger(__name__)

LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECONDS = 15 * 60


def _send_mail_logged(subject, message, recipient_list):
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
    except Exception:
        logger.exception('Falha ao enviar email "%s" para %s', subject, recipient_list)


def _send_async(subject, message, recipient_list):
    threading.Thread(
        target=_send_mail_logged,
        args=(subject, message, recipient_list),
        daemon=True,
    ).start()


def _pending_users():
    """Self-registered accounts awaiting approval (never logged in, not active)."""
    return User.objects.filter(is_active=False, last_login__isnull=True)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    ctx = {}
    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'login':
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            fail_key = f'login-fail:{username.lower()}'
            if cache.get(fail_key, 0) >= LOGIN_MAX_FAILURES:
                ctx['login_error'] = 'Demasiadas tentativas falhadas. Tente novamente dentro de 15 minutos.'
                return render(request, 'core/login.html', ctx)

            user = authenticate(request, username=username, password=password)
            if user:
                cache.delete(fail_key)
                login(request, user)
                next_url = request.GET.get('next', '')
                if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect('core:dashboard')

            cache.add(fail_key, 0, LOGIN_LOCKOUT_SECONDS)
            cache.incr(fail_key)
            pending = _pending_users().filter(username=username).first()
            if pending and pending.check_password(password):
                ctx['login_error'] = 'A sua conta ainda aguarda aprovação do administrador.'
            else:
                ctx['login_error'] = 'Credenciais inválidas.'

        elif form_type == 'register':
            username = request.POST.get('reg_username', '').strip()
            email    = request.POST.get('reg_email', '').strip()
            pw       = request.POST.get('reg_password', '')
            confirm  = request.POST.get('reg_confirm', '')

            try:
                validate_email(email)
                email_ok = True
            except ValidationError:
                email_ok = False
            pw_errors = []
            if pw:
                try:
                    validate_password(pw, user=User(username=username, email=email))
                except ValidationError as e:
                    pw_errors = e.messages

            if not all([username, email, pw, confirm]):
                ctx['reg_error'] = 'Preencha todos os campos.'
            elif not email_ok:
                ctx['reg_error'] = 'Email inválido.'
            elif pw != confirm:
                ctx['reg_error'] = 'As passwords não coincidem.'
            elif pw_errors:
                ctx['reg_error'] = ' '.join(pw_errors)
            elif User.objects.filter(username__iexact=username).exists():
                ctx['reg_error'] = 'Utilizador já existe.'
            elif User.objects.filter(email__iexact=email).exists():
                ctx['reg_error'] = 'Email já registado.'
            else:
                User.objects.create_user(username=username, email=email, password=pw, is_active=False)
                ctx['reg_ok'] = 'Registo submetido! Aguarde aprovação do administrador.'
                if settings.ADMIN_EMAIL:
                    _send_async(
                        '[Fogo Bom] Novo utilizador aguarda aprovação',
                        f'O utilizador "{username}" ({email}) registou-se e aguarda aprovação.\n\nAprove ou recuse em: {request.build_absolute_uri("/utilizadores/pendentes/")}',
                        [settings.ADMIN_EMAIL],
                    )

    return render(request, 'core/login.html', ctx)


@require_POST
def logout_view(request):
    logout(request)
    return redirect('core:login')


@login_required
def dashboard(request):
    from parcelas.models import FireParcel
    from operatives.models import Operative
    from fire_actions.models import FireAction, BurningPlan

    today    = timezone.localdate()
    upcoming = FireAction.objects.filter(
        scheduled_date__gte=today,
        scheduled_date__lte=today + timedelta(days=30),
        status='Pre-Plano'
    ).order_by('scheduled_date')[:8]

    recent_plans = BurningPlan.objects.select_related('pre_plan').order_by('-created_at')[:8]

    return render(request, 'core/dashboard.html', {
        'today':               today,
        'total_parcelas':      FireParcel.objects.count(),
        'total_preplans':      FireAction.objects.filter(status='Pre-Plano').count(),
        'total_burning_plans': BurningPlan.objects.count(),
        'total_operatives':    Operative.objects.count(),
        'upcoming':            upcoming,
        'recent_plans':        recent_plans,
    })


@login_required
def calendario(request):
    from fire_actions.models import FireAction
    events = []
    for a in FireAction.objects.all():
        events.append({
            'title': a.name,
            'start': str(a.scheduled_date),
            'color': '#e8541a' if a.status == 'Pre-Plano' else '#3a8c50',
            'url':   f'/preplan/{a.pk}/',
        })
    return render(request, 'core/calendario.html', {'events': events})


@staff_required
def pending_users(request):
    pending = _pending_users().order_by('date_joined')
    return render(request, 'core/pending_users.html', {'pending': pending})


@require_POST
@staff_required
def approve_user(request, user_id):
    user = get_object_or_404(_pending_users(), pk=user_id)
    user.is_active = True
    user.save()
    if user.email:
        _send_async(
            '[Fogo Bom] Acesso aprovado',
            f'Olá {user.username},\n\nO seu acesso à plataforma Fogo Bom Algarve foi aprovado. Já pode iniciar sessão.',
            [user.email],
        )
    messages.success(request, f'Utilizador "{user.username}" aprovado.')
    return redirect('core:pending_users')


@require_POST
@staff_required
def decline_user(request, user_id):
    user = get_object_or_404(_pending_users(), pk=user_id)
    email, username = user.email, user.username
    user.delete()
    if email:
        _send_async(
            '[Fogo Bom] Pedido de acesso recusado',
            f'Olá {username},\n\nO seu pedido de acesso à plataforma Fogo Bom Algarve foi recusado.',
            [email],
        )
    messages.success(request, f'Utilizador "{username}" recusado e removido.')
    return redirect('core:pending_users')


@login_required
def meteorologia(request):
    from parcelas.models import FireParcel
    parcelas = []
    for p in FireParcel.objects.all():
        try:
            c = p.geometry.centroid
            parcelas.append({'id': str(p.id), 'name': p.name,
                             'lat': round(c.y, 6), 'lng': round(c.x, 6)})
        except Exception:
            continue
    return render(request, 'core/firedpt.html', {'parcelas': parcelas})
