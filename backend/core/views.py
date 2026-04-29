import json
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone


def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    ctx = {}
    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'login':
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                return redirect(request.GET.get('next', 'core:dashboard'))
            ctx['login_error'] = 'Credenciais inválidas.'

        elif form_type == 'register':
            username = request.POST.get('reg_username', '').strip()
            email    = request.POST.get('reg_email', '').strip()
            pw       = request.POST.get('reg_password', '')
            confirm  = request.POST.get('reg_confirm', '')

            if not all([username, email, pw, confirm]):
                ctx['reg_error'] = 'Preencha todos os campos.'
            elif pw != confirm:
                ctx['reg_error'] = 'As passwords não coincidem.'
            elif len(pw) < 6:
                ctx['reg_error'] = 'Password com mínimo 6 caracteres.'
            elif User.objects.filter(username=username).exists():
                ctx['reg_error'] = 'Utilizador já existe.'
            elif User.objects.filter(email=email).exists():
                ctx['reg_error'] = 'Email já registado.'
            else:
                User.objects.create_user(username=username, email=email, password=pw, is_active=False)
                ctx['reg_ok'] = 'Registo submetido! Aguarde aprovação do administrador.'
                if settings.ADMIN_EMAIL:
                    send_mail(
                        subject='[Fogo Bom] Novo utilizador aguarda aprovação',
                        message=f'O utilizador "{username}" ({email}) registou-se e aguarda aprovação.\n\nAprove ou recuse em: {request.build_absolute_uri("/utilizadores/pendentes/")}',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[settings.ADMIN_EMAIL],
                        fail_silently=True,
                    )

    return render(request, 'core/login.html', ctx)


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
    return render(request, 'core/calendario.html', {'events_json': json.dumps(events)})


@login_required
def pending_users(request):
    if not request.user.is_staff:
        return redirect('core:dashboard')
    pending = User.objects.filter(is_active=False).order_by('date_joined')
    return render(request, 'core/pending_users.html', {'pending': pending})


@login_required
def approve_user(request, user_id):
    if not request.user.is_staff:
        return redirect('core:dashboard')
    user = get_object_or_404(User, pk=user_id, is_active=False)
    user.is_active = True
    user.save()
    if user.email:
        send_mail(
            subject='[Fogo Bom] Acesso aprovado',
            message=f'Olá {user.username},\n\nO seu acesso à plataforma Fogo Bom Algarve foi aprovado. Já pode iniciar sessão.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    messages.success(request, f'Utilizador "{user.username}" aprovado.')
    return redirect('core:pending_users')


@login_required
def decline_user(request, user_id):
    if not request.user.is_staff:
        return redirect('core:dashboard')
    user = get_object_or_404(User, pk=user_id, is_active=False)
    email, username = user.email, user.username
    user.delete()
    if email:
        send_mail(
            subject='[Fogo Bom] Pedido de acesso recusado',
            message=f'Olá {username},\n\nO seu pedido de acesso à plataforma Fogo Bom Algarve foi recusado.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
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
    parcelas_json = json.dumps(parcelas, ensure_ascii=False)
    return render(request, 'core/firedpt.html', {'parcelas_json': parcelas_json})
