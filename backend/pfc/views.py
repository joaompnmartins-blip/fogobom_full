from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import form_errors_to_messages
from parcelas.models import FireParcel
from .costs import default_inputs, pfc_estimate
from .forms import PFCForm, PFCParcelForm
from .models import PFC, PFCParcel


def _operative(user):
    return getattr(user, 'operative', None)


def _is_tecnico(user):
    op = _operative(user)
    return bool(op and op.is_tecnico)


def can_edit(user, pfc):
    return user.is_staff or pfc.technician_id == user.pk


def _deny(request, pfc):
    messages.error(request, 'Só o técnico que elaborou o PFC ou um administrador o podem alterar.')
    return redirect('pfc:detail', pk=pfc.pk)


@login_required
def pfc_list(request):
    pfcs = PFC.objects.select_related('technician', 'technician__operative').prefetch_related('plan_parcels__parcel')
    return render(request, 'pfc/list.html', {'pfcs': pfcs, 'can_create': _is_tecnico(request.user)})


@login_required
def pfc_create(request):
    if not _is_tecnico(request.user):
        messages.error(request, 'Um PFC é elaborado por um técnico credenciado (credenciação validada).')
        return redirect('pfc:list')
    cred = _operative(request.user).credential_number
    if request.method == 'POST':
        form = PFCForm(request.POST, credential_number=cred)
        if form.is_valid():
            pfc = form.save(commit=False)
            pfc.technician, pfc.credential_number = request.user, cred
            pfc.save()
            messages.success(request, f'PFC "{pfc.name}" criado. Acrescente agora as parcelas.')
            return redirect('pfc:detail', pk=pfc.pk)
        form_errors_to_messages(request, form)
    else:
        last = PFC.objects.filter(credential_number=cred).aggregate(m=Max('sequence'))['m'] or 0
        form = PFCForm(initial={'sequence': last + 1}, credential_number=cred)
    return render(request, 'pfc/form.html', {'form': form, 'pfc': None, 'credential_number': cred})


@login_required
def pfc_edit(request, pk):
    pfc = get_object_or_404(PFC, pk=pk)
    if not can_edit(request.user, pfc):
        return _deny(request, pfc)
    if request.method == 'POST':
        form = PFCForm(request.POST, instance=pfc)
        if form.is_valid():
            form.save()
            messages.success(request, 'PFC atualizado.')
            return redirect('pfc:detail', pk=pfc.pk)
        form_errors_to_messages(request, form)
    else:
        form = PFCForm(instance=pfc)
    return render(request, 'pfc/form.html', {'form': form, 'pfc': pfc, 'credential_number': pfc.credential_number})


@login_required
def pfc_detail(request, pk):
    pfc = get_object_or_404(PFC.objects.select_related('technician', 'technician__operative'), pk=pk)
    estimate = pfc_estimate(pfc)
    return render(request, 'pfc/detail.html', {
        'pfc': pfc,
        'estimate': estimate,
        'actions': pfc.actions.order_by('-scheduled_date'),
        'can_edit': can_edit(request.user, pfc),
        'today': timezone.localdate(),
        'map_parcels': [{'name': f'{pp.number} — {pp.parcel.name}', 'geojson': pp.parcel.geometry.json}
                        for pp in pfc.plan_parcels.select_related('parcel')],
    })


def _date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


@require_POST
@login_required
def pfc_status(request, pk):
    pfc = get_object_or_404(PFC, pk=pk)
    if not can_edit(request.user, pfc):
        return _deny(request, pfc)
    action = request.POST.get('action')
    d = _date(request.POST.get('date')) or timezone.localdate()
    notes = request.POST.get('notes', '').strip()
    if action == 'submeter':
        if pfc.missing_contents:
            messages.error(request, 'Complete o PFC antes de o enviar: ' + '; '.join(pfc.missing_contents))
            return redirect('pfc:detail', pk=pk)
        pfc.status, pfc.submitted_on = PFC.STATUS_SUBMETIDO, d
        msg = f'PFC enviado à comissão municipal em {d:%d/%m/%Y}. Sem decisão em 45 dias, considera-se aprovado.'
    elif action == 'aprovar':
        pfc.status, pfc.approved_on, pfc.tacit_approval = PFC.STATUS_APROVADO, d, False
        if request.POST.get('entity'):
            pfc.approval_entity = request.POST['entity'][:200]
        msg = f'Aprovação registada ({d:%d/%m/%Y}).'
    elif action == 'tacita' and pfc.status == PFC.STATUS_SUBMETIDO and pfc.effective_approval_date:
        pfc.status, pfc.approved_on, pfc.tacit_approval = PFC.STATUS_APROVADO, pfc.tacit_approval_date, True
        msg = f'Aprovação tácita registada ({pfc.approved_on:%d/%m/%Y}).'
    elif action == 'suspender':
        pfc.status, pfc.status_notes = PFC.STATUS_SUSPENSO, notes
        msg = 'PFC suspenso.'
    elif action == 'rever':
        pfc.status, pfc.status_notes = PFC.STATUS_REVISAO, notes
        msg = 'PFC em revisão — depois de alterado, volte a enviá-lo à comissão municipal.'
    elif action == 'concluir':
        pfc.status = PFC.STATUS_CONCLUIDO
        msg = 'PFC concluído.'
    elif action == 'reabrir':
        pfc.status = PFC.STATUS_APROVADO if pfc.approved_on else PFC.STATUS_PREPARACAO
        msg = 'PFC reaberto.'
    else:
        return redirect('pfc:detail', pk=pk)
    pfc.save()
    messages.success(request, msg)
    return redirect('pfc:detail', pk=pk)


def _parcel_initial(pfc, parcel):
    initial = dict(default_inputs(parcel))
    ev = parcel.evaluations.filter(completed_at__isnull=False).order_by('-completed_at').first()
    if ev:
        initial['occupation'] = '\n'.join(
            f'{v.cover_pct}% {v.species}' + (f' com {v.height_m:g} m' if v.height_m else '')
            + (f', {v.age_years} anos' if v.age_years else '') if v.cover_pct is not None else v.species
            for v in ev.vegetation.all())
        initial['objective'] = ev.objectives_display
    return initial


@login_required
def parcel_edit(request, pk, pp_pk=None):
    pfc = get_object_or_404(PFC, pk=pk)
    if not can_edit(request.user, pfc):
        return _deny(request, pfc)
    pp = get_object_or_404(PFCParcel, pk=pp_pk, pfc=pfc) if pp_pk else PFCParcel(pfc=pfc)
    if request.method == 'POST':
        form = PFCParcelForm(request.POST, instance=pp, pfc=pfc)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.pfc = pfc
            obj.save()
            messages.success(request, f'Parcela {obj.number} guardada.')
            return redirect('pfc:detail', pk=pfc.pk)
        form_errors_to_messages(request, form)
    else:
        initial = {}
        if not pp.pk:
            initial['number'] = (pfc.plan_parcels.aggregate(m=Max('number'))['m'] or 0) + 1
            chosen = FireParcel.objects.filter(pk=request.GET.get('parcel'),
                                               status__in=FireParcel.AVAILABLE_STATUSES).first()
            if chosen:
                initial.update(_parcel_initial(pfc, chosen), parcel=chosen.pk)
        form = PFCParcelForm(instance=pp, pfc=pfc, initial=initial)
    return render(request, 'pfc/parcel_form.html', {'form': form, 'pfc': pfc, 'pp': pp})


@require_POST
@login_required
def parcel_remove(request, pk, pp_pk):
    pfc = get_object_or_404(PFC, pk=pk)
    if not can_edit(request.user, pfc):
        return _deny(request, pfc)
    pp = get_object_or_404(PFCParcel, pk=pp_pk, pfc=pfc)
    pp.delete()
    messages.success(request, 'Parcela retirada do PFC.')
    return redirect('pfc:detail', pk=pfc.pk)


@login_required
def pfc_docx(request, pk):
    from .document import generate_pfc_docx
    pfc = get_object_or_404(PFC, pk=pk)
    data = generate_pfc_docx(pfc)
    response = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    safe = pfc.number.replace('/', '-').replace('—', 'x')
    response['Content-Disposition'] = f'attachment; filename="PFC_{safe}.docx"'
    return response
