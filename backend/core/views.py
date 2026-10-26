from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.password_validation import validate_password
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import staff_required
from .emails import send_async as _send_async

LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECONDS = 15 * 60


PASSWORD_RESET_MAX_PER_HOUR = 3


def login_fail_key(username):
    return f'login-fail:{username.lower()}'


# ── Password reset ────────────────────────────────────────────────────────────

class AsyncPasswordResetForm(PasswordResetForm):
    """Django's reset form (active users only, no account disclosure), sending in the background."""
    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        subject = ''.join(render_to_string(subject_template_name, context).splitlines())
        body = render_to_string(email_template_name, context)
        _send_async(subject, body, [to_email])


class PasswordResetRequestView(auth_views.PasswordResetView):
    form_class            = AsyncPasswordResetForm
    template_name         = 'core/password_reset_form.html'
    email_template_name   = 'core/password_reset_email.txt'
    subject_template_name = 'core/password_reset_subject.txt'
    success_url           = reverse_lazy('core:password_reset_done')

    def form_valid(self, form):
        key = f'pw-reset:{form.cleaned_data["email"].lower()}'
        cache.add(key, 0, 60 * 60)
        if cache.incr(key) > PASSWORD_RESET_MAX_PER_HOUR:
            # Same response as a normal request, so nothing is revealed
            return redirect(self.success_url)
        return super().form_valid(form)


class PasswordChange(auth_views.PasswordChangeView):
    """Logged-in users change their own password; the session stays valid."""
    template_name = 'core/password_change.html'
    success_url   = reverse_lazy('core:dashboard')

    def form_valid(self, form):
        messages.success(self.request, 'Password alterada com sucesso.')
        return super().form_valid(form)


class PasswordResetConfirm(auth_views.PasswordResetConfirmView):
    template_name = 'core/password_reset_confirm.html'
    success_url   = reverse_lazy('core:password_reset_complete')

    def form_valid(self, form):
        cache.delete(login_fail_key(form.user.get_username()))  # lift any login lockout
        return super().form_valid(form)


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
            fail_key = login_fail_key(username)
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
            from operatives.icnf import is_valid_number, normalize_number
            from operatives.models import Operative
            username  = request.POST.get('reg_username', '').strip()
            full_name = ' '.join(request.POST.get('reg_fullname', '').split())
            email     = request.POST.get('reg_email', '').strip()
            pw        = request.POST.get('reg_password', '')
            confirm   = request.POST.get('reg_confirm', '')
            cred_type = request.POST.get('reg_cred_type', Operative.CRED_NENHUMA)
            cred_num  = normalize_number(request.POST.get('reg_cred_number', ''))
            if cred_type not in dict(Operative.CREDENTIAL_TYPES):
                cred_type = Operative.CRED_NENHUMA
            is_tecnico = cred_type == Operative.CRED_TECNICO
            ctx['reg_values'] = {'username': username, 'fullname': full_name, 'email': email,
                                 'cred_type': cred_type, 'cred_number': cred_num}

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

            if not all([username, full_name, email, pw, confirm]):
                ctx['reg_error'] = 'Preencha todos os campos.'
            elif is_tecnico and not is_valid_number(cred_num):
                ctx['reg_error'] = 'Indique o n.º de credenciação ICNF no formato número-ano (ex.: 547-2026).'
            elif is_tecnico and Operative.objects.filter(credential_number=cred_num).exclude(
                    credential_status=Operative.STATUS_RECUSADA).exists():
                ctx['reg_error'] = 'Este n.º de credenciação já está associado a outra conta. Contacte o administrador.'
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
                with transaction.atomic():
                    user = User.objects.create_user(username=username, email=email, password=pw, is_active=False)
                    Operative.objects.create(
                        user=user, name=full_name, email=email, phone='', certification_level='',
                        credential_type=cred_type,
                        credential_number=cred_num if is_tecnico else '',
                        credential_status=Operative.STATUS_PENDENTE if is_tecnico else Operative.STATUS_NA,
                    )
                ctx['reg_ok'] = 'Registo submetido! Aguarde aprovação do administrador.'
                ctx.pop('reg_values')
                if settings.ADMIN_EMAIL:
                    cred = f'\nCredenciação declarada: técnico credenciado n.º {cred_num} (por validar).' if is_tecnico else ''
                    _send_async(
                        '[Fogo Bom] Novo utilizador aguarda aprovação',
                        f'O utilizador "{username}" — {full_name} ({email}) registou-se e aguarda aprovação.{cred}\n\n'
                        f'Aprove ou recuse em: {request.build_absolute_uri("/utilizadores/pendentes/")}',
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

    expiring = []
    if request.user.is_staff:
        expiring = [op for op in Operative.objects.filter(credential_status=Operative.STATUS_VALIDADA,
                                                          credential_lifetime=False,
                                                          credential_valid_until__isnull=False)
                    if op.credential_expiring or op.credential_expired]

    my_op = getattr(request.user, 'operative', None)
    to_evaluate = []
    if my_op and my_op.is_tecnico:
        to_evaluate = list(FireParcel.objects.filter(
            status__in=[FireParcel.STATUS_PROPOSTA, FireParcel.STATUS_AVALIACAO]).order_by('created_at')[:10])

    return render(request, 'core/dashboard.html', {
        'my_op':               my_op,
        'to_evaluate':         to_evaluate,
        'expiring_credentials': expiring,
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
    from operatives.icnf import match
    from operatives.models import IcnfTechnician, Operative
    pending = list(_pending_users().select_related('operative').order_by('date_joined'))
    credentials = list(Operative.objects.filter(credential_status=Operative.STATUS_PENDENTE)
                       .select_related('user').order_by('created_at'))
    for op in credentials:
        op.icnf = match(op.credential_number, op.name)
    return render(request, 'core/pending_users.html', {
        'pending':     pending,
        'credentials': credentials,
        'icnf_date':   IcnfTechnician.objects.values_list('list_date', flat=True).first(),
    })


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
    with transaction.atomic():
        from operatives.models import Operative
        Operative.objects.filter(user=user).delete()  # profile created at registration
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
    from parcelas.views import parcel_centroids
    return render(request, 'core/firedpt.html', {
        'parcelas':       parcel_centroids(),
        'firedpt_config': {'cartoKey': settings.CARTO_API_KEY, 'maptilerKey': settings.MAPTILER_API_KEY},
    })
