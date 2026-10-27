from datetime import datetime

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.decorators import staff_required
from core.emails import send_async
from django.contrib import messages
from core.forms import form_errors_to_messages
from .forms import OperativeForm, ProfileForm
from .icnf import import_list, match
from .models import IcnfTechnician, Operative


@login_required
def operative_list(request):
    operatives = Operative.objects.all()
    return render(request, 'operatives/list.html', {'operatives': operatives})


@login_required
def operative_create(request):
    if request.method == 'POST':
        form = OperativeForm(request.POST)
        if form.is_valid():
            op = form.save()
            messages.success(request, f'Operacional "{op.name}" criado.')
            return redirect('operatives:list')
        form_errors_to_messages(request, form)
        return render(request, 'operatives/form.html', {'op': form.instance, 'action': 'Novo Operacional'})
    return render(request, 'operatives/form.html', {'action': 'Novo Operacional'})


@login_required
def operative_edit(request, pk):
    op = get_object_or_404(Operative, pk=pk)
    if request.method == 'POST':
        form = OperativeForm(request.POST, instance=op)
        if form.is_valid():
            form.save()
            messages.success(request, f'Operacional "{op.name}" atualizado.')
            return redirect('operatives:list')
        form_errors_to_messages(request, form)
    return render(request, 'operatives/form.html', {'op': op, 'action': 'Editar Operacional'})


@staff_required
def operative_delete(request, pk):
    op = get_object_or_404(Operative, pk=pk)
    if request.method == 'POST':
        name = op.name
        op.delete()
        messages.success(request, f'Operacional "{name}" eliminado.')
        return redirect('operatives:list')
    return render(request, 'operatives/confirm_delete.html', {'op': op})


# ── Profile & credentials ─────────────────────────────────────────────────────

def _profile_for(user):
    op = getattr(user, 'operative', None)
    if op is None:
        op = Operative(user=user, name=user.get_full_name() or user.get_username(), email=user.email,
                       phone='', certification_level='')
    return op


@login_required
def profile(request):
    from core.models import UserPreferences
    op = _profile_for(request.user)
    prefs = UserPreferences.for_user(request.user)
    if request.method == 'POST':
        for f in PREF_FIELDS:
            setattr(prefs, f, bool(request.POST.get(f)))
        prefs.save()
        before = (op.credential_type, op.credential_number) if op.pk else None
        form = ProfileForm(request.POST, instance=op)
        if form.is_valid():
            op = form.save(commit=False)
            op.email = request.user.email
            changed = before != (op.credential_type, op.credential_number)
            if op.credential_type != Operative.CRED_TECNICO:
                op.credential_status = Operative.STATUS_NA
            elif changed or op.credential_status in (Operative.STATUS_NA, Operative.STATUS_RECUSADA):
                op.credential_status = Operative.STATUS_PENDENTE
                op.credential_reviewed_by = op.credential_reviewed_at = None
                op.credential_rejection_reason = ''
            op.save()
            if op.credential_status == Operative.STATUS_PENDENTE and changed and settings.ADMIN_EMAIL:
                send_async('[Fogo Bom] Credenciação por validar',
                           f'{op.name} ({request.user.get_username()}) indicou a credenciação ICNF n.º '
                           f'{op.credential_number}.\n\nValide em: '
                           f'{request.build_absolute_uri("/utilizadores/pendentes/")}',
                           [settings.ADMIN_EMAIL])
            messages.success(request, 'Perfil atualizado.' + (
                ' A credenciação aguarda validação do administrador.'
                if op.credential_status == Operative.STATUS_PENDENTE and changed else ''))
            return redirect('core:profile')
        form_errors_to_messages(request, form)
        op = form.instance
    return render(request, 'operatives/profile.html', {
        'op': op,
        'types': Operative.CREDENTIAL_TYPES,
        'participations': op.execution_roles.count() if op.pk else 0,
        'prefs': [(f, prefs._meta.get_field(f).verbose_name, getattr(prefs, f)) for f in PREF_FIELDS],
    })


PREF_FIELDS = ['email_new_actions', 'email_action_updates', 'email_reminders', 'email_deadlines']


@require_POST
@staff_required
def credential_review(request, pk):
    op = get_object_or_404(Operative, pk=pk, credential_status=Operative.STATUS_PENDENTE)
    decision = request.POST.get('decision')
    if decision == 'validar':
        record = match(op.credential_number, op.name)['record']
        manual_date = request.POST.get('valid_until', '').strip()
        if record:
            op.credential_lifetime, op.credential_valid_until = record.lifetime, record.valid_until
        elif manual_date:
            try:
                op.credential_valid_until = datetime.strptime(manual_date, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Data de validade inválida.')
                return redirect('core:pending_users')
        op.credential_status = Operative.STATUS_VALIDADA
        op.credential_rejection_reason = ''
        subject, body = ('[Fogo Bom] Credenciação validada',
                         f'Olá {op.name},\n\nA sua credenciação ICNF n.º {op.credential_number} foi validada. '
                         f'Tem agora acesso às funções de técnico na plataforma Fogo Bom Algarve.')
    elif decision == 'recusar':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'Indique o motivo da recusa.')
            return redirect('core:pending_users')
        op.credential_status = Operative.STATUS_RECUSADA
        op.credential_rejection_reason = reason
        subject, body = ('[Fogo Bom] Credenciação não validada',
                         f'Olá {op.name},\n\nNão foi possível validar a credenciação ICNF n.º '
                         f'{op.credential_number}.\nMotivo: {reason}\n\n'
                         f'Pode corrigir os dados na página "O meu perfil".')
    else:
        return redirect('core:pending_users')
    op.credential_reviewed_by = request.user
    op.credential_reviewed_at = timezone.now()
    op.save()
    email = op.user.email if op.user else op.email
    if email:
        send_async(subject, body, [email])
    messages.success(request, f'Credenciação de "{op.name}" {"validada" if decision == "validar" else "recusada"}.')
    return redirect('core:pending_users')


@staff_required
def icnf_list(request):
    if request.method == 'POST' and request.FILES.get('lista'):
        try:
            list_date, count = import_list(request.FILES['lista'])
        except Exception as exc:
            messages.error(request, f'Não foi possível ler a lista: {exc}')
        else:
            synced = _sync_validities()
            messages.success(request, f'Lista importada: {count} técnicos'
                             + (f' (atualização de {list_date:%d/%m/%Y})' if list_date else '')
                             + (f'. Validade atualizada em {synced} perfil(s).' if synced else '.'))
        return redirect('core:icnf_list')
    q = request.GET.get('q', '').strip()
    rows = IcnfTechnician.objects.all()
    if q:
        rows = rows.filter(Q(number__icontains=q) | Q(name__icontains=q) | Q(concelho__icontains=q))
    linked = dict(Operative.objects.exclude(credential_number='').values_list('credential_number', 'name'))
    return render(request, 'operatives/icnf_list.html', {
        'rows': [(r, linked.get(r.number)) for r in rows], 'q': q,
        'total': IcnfTechnician.objects.count(),
        'list_date': IcnfTechnician.objects.values_list('list_date', flat=True).first(),
    })


def _sync_validities():
    """After importing a new list, copy the official validity to validated technicians."""
    n = 0
    for op in Operative.objects.filter(credential_status=Operative.STATUS_VALIDADA).exclude(credential_number=''):
        rec = IcnfTechnician.objects.filter(number=op.credential_number).first()
        if rec and (op.credential_lifetime, op.credential_valid_until) != (rec.lifetime, rec.valid_until):
            op.credential_lifetime, op.credential_valid_until = rec.lifetime, rec.valid_until
            op.save(update_fields=['credential_lifetime', 'credential_valid_until'])
            n += 1
    return n
