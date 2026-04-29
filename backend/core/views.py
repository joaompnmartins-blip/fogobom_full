import json
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
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
                User.objects.create_user(username=username, email=email, password=pw)
                ctx['reg_ok'] = f'Conta criada! Faça login com "{username}".'

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
