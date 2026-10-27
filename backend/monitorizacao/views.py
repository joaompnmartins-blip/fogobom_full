import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from core.decorators import staff_required
from core.forms import clean_photos, form_errors_to_messages
from fire_actions.models import BurningPlan, ParcelExecution
from fire_actions.views import can_manage
from parcelas.models import FireParcel
from parcelas.views import is_tecnico
from .context_processors import CACHE_KEY
from .forms import AssessmentForm, CriterionFormSet
from .models import Assessment, AssessmentPhoto, CriterionValue, ParcelCriterion, VisitWaiver
from .schedule import UPCOMING_DAYS, all_visits, expected_visits

logger = logging.getLogger(__name__)


@login_required
def monitoring_list(request):
    today = timezone.localdate()
    visits = all_visits(today)
    status = request.GET.get('estado', 'pendentes')
    if status == 'pendentes':
        shown = [v for v in visits if v['status'] in ('atrasada', 'em_curso')
                 or (v['status'] == 'futura' and (v['due'] - today).days <= UPCOMING_DAYS)]
    elif status == 'todas':
        shown = visits
    else:
        shown = [v for v in visits if v['status'] == status]
    order = {'atrasada': 0, 'em_curso': 1, 'futura': 2, 'feita': 3, 'dispensada': 4}
    shown.sort(key=lambda v: (order[v['status']], v['due'] if order[v['status']] < 3 else -v['due'].toordinal()))
    counts = {k: sum(1 for v in visits if v['status'] == k) for k in order}
    return render(request, 'monitorizacao/list.html', {'visits': shown, 'estado': status, 'counts': counts})


def _first_execution(ex):
    """Visits are recorded on the first day the parcel was burned within the execution."""
    return (ParcelExecution.objects.filter(plan_id=ex.plan_id, parcel_id=ex.parcel_id)
            .order_by('date').first()) or ex


def _criteria(parcel, assessment=None):
    used = set(assessment.criterion_values.values_list('criterion_id', flat=True)) if assessment else set()
    return [c for c in parcel.monitoring_criteria.all() if c.active or c.pk in used]


def _save(request, form, ex, assessment):
    photos, photo_errors = clean_photos(request.FILES.getlist('photos'))
    if form.is_valid() and not photo_errors:
        with transaction.atomic():
            a = form.save(commit=False)
            if assessment is None:
                a.execution, a.phase, a.year = ex, form.phase, form.year
                a.observer = request.user
            a.save()
            if assessment is None:   # done after all: the waiver no longer applies
                VisitWaiver.objects.filter(execution=ex, phase=a.phase, year=a.year).delete()
            for criterion, value in form.criterion_values().items():
                if value:
                    CriterionValue.objects.update_or_create(assessment=a, criterion=criterion,
                                                            defaults={'value': value})
                else:
                    CriterionValue.objects.filter(assessment=a, criterion=criterion).delete()
            caption = request.POST.get('photo_caption', '')[:200]
            for photo in photos:
                AssessmentPhoto.objects.create(assessment=a, image=photo, caption=caption)
        cache.delete(CACHE_KEY)
        messages.success(request, f'{a.label} de {ex.parcel.name} guardada.')
        return a
    form_errors_to_messages(request, form)
    for err in photo_errors:
        messages.error(request, f'Fotografias: {err}')
    return None


def _render_form(request, form, ex, assessment, visit=None):
    return render(request, 'monitorizacao/form.html', {
        'form': form, 'ex': ex, 'a': assessment, 'visit': visit, 'action': ex.plan.pre_plan,
        'label': assessment.label if assessment else (visit or {}).get('label', ''),
    })


def _visit_key(request):
    """(phase, year) from ?fase=…&ano=…; year is 0 except for annual visits (≥ 1)."""
    phase = request.GET.get('fase', Assessment.PHASE_IMEDIATA)
    if phase not in dict(Assessment.PHASES):
        phase = Assessment.PHASE_IMEDIATA
    if phase != Assessment.PHASE_ANUAL:
        return phase, 0
    try:
        return phase, max(int(request.GET.get('ano', 1)), 1)
    except ValueError:
        return phase, 1


def _managed_execution(request, ex_pk):
    """First execution day of the parcel, or None (with a message) when the user cannot manage the action."""
    ex = _first_execution(get_object_or_404(ParcelExecution.objects.select_related('plan__pre_plan', 'parcel'),
                                            pk=ex_pk))
    if not can_manage(request.user, ex.plan.pre_plan):
        messages.error(request, 'Só o técnico responsável, técnicos credenciados ou administradores registam '
                                'a monitorização.')
        return None, ex
    return ex, ex


@login_required
def assessment_create(request, ex_pk):
    ex, any_ex = _managed_execution(request, ex_pk)
    if ex is None:
        return redirect('fire_actions:burning_plan_detail', pk=any_ex.plan_id)
    phase, year = _visit_key(request)
    existing = ex.assessments.filter(phase=phase, year=year).first()
    if existing:
        return redirect('monitorizacao:edit', pk=existing.pk)
    visit = next((v for v in expected_visits(ex) if (v['phase'], v['year']) == (phase, year)), None) or \
        {'label': f'Monitorização — ano {year}' if year else dict(Assessment.PHASES)[phase]}
    criteria = _criteria(ex.parcel)
    if request.method == 'POST':
        form = AssessmentForm(request.POST, request.FILES, phase=phase, criteria=criteria)
        form.phase, form.year = phase, year
        a = _save(request, form, ex, None)
        if a:
            return redirect('monitorizacao:detail', pk=a.pk)
    else:
        last = ex.assessments.order_by('-date').first()
        initial = {'date': timezone.localdate()}
        if last:   # carry over the slowly changing values
            initial.update({f: getattr(last, f) for f in ('soil_ph', 'soil_organic_matter_pct')})
        form = AssessmentForm(phase=phase, criteria=criteria, initial=initial)
    return _render_form(request, form, ex, None, visit)


def _safe_next(request, value):
    ok = value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure())
    return value if ok else ''


@login_required
def visit_waive(request, ex_pk):
    ex, any_ex = _managed_execution(request, ex_pk)
    if ex is None:
        return redirect('fire_actions:burning_plan_detail', pk=any_ex.plan_id)
    phase, year = _visit_key(request)
    if ex.assessments.filter(phase=phase, year=year).exists():
        messages.error(request, 'Esta visita já foi registada; não pode ser dispensada.')
        return redirect('fire_actions:burning_plan_detail', pk=ex.plan_id)
    waiver = ex.waivers.filter(phase=phase, year=year).first()
    visit = next((v for v in expected_visits(ex) if (v['phase'], v['year']) == (phase, year)), None)
    label = waiver.label if waiver else visit['label'] if visit else VisitWaiver(phase=phase, year=year).label
    reason = waiver.reason if waiver else ''
    nxt = _safe_next(request, request.POST.get('next') or request.GET.get('next', ''))
    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if request.POST.get('undo') and waiver:
            waiver.delete()
            cache.delete(CACHE_KEY)
            messages.success(request, f'{label} de {ex.parcel.name} volta a estar por fazer.')
            return redirect(nxt or 'monitorizacao:list')
        if not reason:
            messages.error(request, 'Indique o motivo da dispensa.')
        else:
            VisitWaiver.objects.update_or_create(execution=ex, phase=phase, year=year,
                                                 defaults={'reason': reason, 'waived_by': request.user})
            cache.delete(CACHE_KEY)
            messages.success(request, f'{label} de {ex.parcel.name} dispensada.')
            return redirect(nxt or 'monitorizacao:list')
    return render(request, 'monitorizacao/waive.html', {
        'ex': ex, 'action': ex.plan.pre_plan, 'label': label, 'visit': visit, 'waiver': waiver, 'reason': reason,
        'next': nxt,
    })


@login_required
def assessment_edit(request, pk):
    a = get_object_or_404(Assessment.objects.select_related('execution__plan__pre_plan', 'execution__parcel'), pk=pk)
    ex = a.execution
    if not can_manage(request.user, ex.plan.pre_plan):
        return redirect('monitorizacao:detail', pk=pk)
    criteria = _criteria(ex.parcel, a)
    if request.method == 'POST':
        form = AssessmentForm(request.POST, request.FILES, instance=a, phase=a.phase, criteria=criteria)
        if _save(request, form, ex, a):
            return redirect('monitorizacao:detail', pk=pk)
    else:
        form = AssessmentForm(instance=a, phase=a.phase, criteria=criteria)
    return _render_form(request, form, ex, a)


@login_required
def assessment_detail(request, pk):
    a = get_object_or_404(Assessment.objects.select_related('execution__plan__pre_plan', 'execution__parcel',
                                                            'observer'), pk=pk)
    present = set(Assessment.fields_for(a.phase))
    sections = []
    for title, names in Assessment.SECTIONS:
        rows = []
        for n in names:
            if n not in present:
                continue
            field = Assessment._meta.get_field(n)
            value = getattr(a, n)
            if field.choices:
                value = getattr(a, f'get_{n}_display')()
            elif value is True:
                value = 'Sim'
            elif value is False:
                value = 'Não'
            if value not in (None, ''):
                rows.append((field.verbose_name, value, n == 'soil_report'))
        if rows:
            sections.append((title, rows))
    return render(request, 'monitorizacao/detail.html', {
        'a': a, 'ex': a.execution, 'action': a.execution.plan.pre_plan, 'sections': sections,
        'criteria': a.criterion_values.select_related('criterion'), 'photos': a.photos.all(),
        'can_manage': can_manage(request.user, a.execution.plan.pre_plan),
    })


@staff_required
def assessment_delete(request, pk):
    a = get_object_or_404(Assessment, pk=pk)
    if request.method == 'POST':
        plan_pk = a.execution.plan_id
        files = [p.image for p in a.photos.all()] + ([a.soil_report] if a.soil_report else [])
        a.delete()
        cache.delete(CACHE_KEY)
        for f in files:
            try:
                f.delete(save=False)
            except Exception:
                logger.warning('Não foi possível apagar o ficheiro %s', f.name, exc_info=True)
        messages.success(request, 'Avaliação eliminada.')
        return redirect('fire_actions:burning_plan_detail', pk=plan_pk)
    return render(request, 'fire_actions/confirm_delete.html', {'obj': a, 'tipo': 'Avaliação'})


@login_required
def criteria_edit(request, parcel_pk):
    parcel = get_object_or_404(FireParcel, pk=parcel_pk)
    if not (request.user.is_staff or is_tecnico(request.user)):
        messages.error(request, 'Só técnicos credenciados ou administradores definem os critérios de monitorização.')
        return redirect('parcelas:detail', pk=parcel.pk)
    qs = parcel.monitoring_criteria.all()
    if request.method == 'POST':
        formset = CriterionFormSet(request.POST, queryset=qs)
        if formset.is_valid():
            with transaction.atomic():
                for obj in formset.save(commit=False):
                    obj.parcel = parcel
                    obj.save()
                for obj in formset.deleted_objects:
                    if obj.values.exists():   # keep history: deactivate instead
                        obj.active = False
                        obj.save(update_fields=['active'])
                    else:
                        obj.delete()
            messages.success(request, 'Critérios de monitorização guardados.')
            return redirect('parcelas:detail', pk=parcel.pk)
        for i, errs in enumerate(formset.errors):
            for msgs in errs.values():
                messages.error(request, f'Linha {i + 1}: {"; ".join(msgs)}')
    else:
        formset = CriterionFormSet(queryset=qs)
    return render(request, 'monitorizacao/criteria.html', {'parcela': parcel, 'formset': formset})


@login_required
def poq_impacto(request, plan_pk):
    plan = get_object_or_404(BurningPlan.objects.select_related('pre_plan', 'pre_plan__pfc'), pk=plan_pk)
    try:
        from .document import generate_poq_impacto
        content = generate_poq_impacto(plan)
    except Exception:
        logger.exception('Erro ao gerar o POQ-Impacto %s', plan_pk)
        messages.error(request, 'Erro ao gerar o documento. O problema foi registado.')
        return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
    ref = plan.pre_plan.pfc.number.replace('/', '-') if plan.pre_plan.pfc_id else plan.pre_plan.name[:40]
    response = HttpResponse(content,
                            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="POQ-Impacto_{ref}_{plan.execution_date:%Y}.docx"'
    return response
