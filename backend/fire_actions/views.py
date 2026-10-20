import json
import logging
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from core.decorators import staff_required
from core.forms import form_errors_to_messages, clean_photos
from django.contrib import messages
from django.http import HttpResponse
from .forms import PrePlanForm, BurningPlanForm
from .models import FireAction, BurningPlan, BurningPlanPhoto
from parcelas.models import FireParcel
from operatives.models import Operative

logger = logging.getLogger(__name__)


def _int_list(values):
    return [int(v) for v in values if str(v).isdigit()]


# ── Pré-Planos ────────────────────────────────────────────────────────────────

@login_required
def preplan_list(request):
    actions = FireAction.objects.prefetch_related('parcels').all()
    return render(request, 'fire_actions/preplan_list.html', {'actions': actions})


def _save_preplan(request, instance):
    is_new = instance.pk is None
    form = PrePlanForm(request.POST, instance=instance)
    if form.is_valid():
        action = form.save()
        verb = 'criado' if is_new else 'atualizado'
        messages.success(request, f'Pré-Plano "{action.name}" {verb}.')
        return redirect('fire_actions:list')
    form_errors_to_messages(request, form)
    return render(request, 'fire_actions/preplan_form.html', {
        'parcelas':         FireParcel.objects.all(),
        'action_obj':       form.instance,
        'selected_parcels': _int_list(request.POST.getlist('parcels')),
    })


@login_required
def preplan_create(request):
    if request.method == 'POST':
        return _save_preplan(request, FireAction())
    return render(request, 'fire_actions/preplan_form.html', {
        'parcelas':   FireParcel.objects.all(),
        'action_obj': None,
    })


@login_required
def preplan_edit(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    if request.method == 'POST':
        return _save_preplan(request, action)
    return render(request, 'fire_actions/preplan_form.html', {
        'parcelas':         FireParcel.objects.all(),
        'action_obj':       action,
        'selected_parcels': list(action.parcels.values_list('pk', flat=True)),
    })


@staff_required
def preplan_delete(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    if hasattr(action, 'burningplan'):
        messages.error(request, 'Este pré-plano tem um Plano de Queima associado. Elimine primeiro o Plano de Queima.')
        return redirect('fire_actions:detail', pk=pk)
    if request.method == 'POST':
        name = action.name
        action.delete()
        messages.success(request, f'Pré-Plano "{name}" eliminado.')
        return redirect('fire_actions:list')
    return render(request, 'fire_actions/confirm_delete.html', {'obj': action, 'tipo': 'Pré-Plano'})


@login_required
def preplan_detail(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    has_bp = hasattr(action, 'burningplan')
    return render(request, 'fire_actions/preplan_detail.html', {
        'action': action,
        'has_bp': has_bp,
    })


# ── Planos de Queima ──────────────────────────────────────────────────────────

def _load_vehicles(bp):
    try:
        return json.loads(bp.vehicles or '{}')
    except (TypeError, ValueError):
        return {}


def _parcels_geom(preplan):
    if not preplan:
        return []
    return [{'name': p.name, 'geojson': p.geometry.json}
            for p in preplan.parcels.all() if p.geometry]


def _bp_form_response(request, bp, preplan, bound=False):
    """Render bp_form.html; when `bound`, re-fill choices from the submitted POST."""
    if bound:
        vehicles = {'VFCI': request.POST.get('vfci', 0), 'VFCM': request.POST.get('vfcm', 0),
                    'Outro': request.POST.get('other_veh', '')}
        selected = _int_list(request.POST.getlist('operatives'))
    else:
        vehicles = _load_vehicles(bp) if bp else {}
        selected = list(bp.operatives.values_list('pk', flat=True)) if bp else []
    return render(request, 'fire_actions/bp_form.html', {
        'bp':                  bp,
        'operatives':          Operative.objects.all(),
        'preplan':             preplan,
        'preplans_without_bp': FireAction.objects.filter(burningplan__isnull=True),
        'vehicles':            vehicles,
        'selected_operatives': selected,
        'parcels_geom':        _parcels_geom(preplan),
    })


def _save_burning_plan(request, instance, preplan):
    is_new = instance.pk is None
    form = BurningPlanForm(request.POST, instance=instance)
    photos, photo_errors = clean_photos(request.FILES.getlist('photos'))

    if form.is_valid() and not photo_errors:
        with transaction.atomic():
            bp = form.save()
            for photo in photos:
                bp.photos.add(BurningPlanPhoto.objects.create(image=photo))
            # Keep the pre-plan in sync with its burning plan
            pp = bp.pre_plan
            pp.status = 'Executada'
            pp.execution_date = bp.execution_date
            pp.save()
        messages.success(request, 'Plano de Queima criado com sucesso.' if is_new else 'Plano de Queima atualizado.')
        return redirect('fire_actions:burning_plan_detail', pk=bp.pk)

    form_errors_to_messages(request, form)
    for err in photo_errors:
        messages.error(request, f'Fotografias: {err}')
    if is_new:
        preplan = preplan or form.cleaned_data.get('pre_plan')
    return _bp_form_response(request, form.instance, preplan, bound=True)


@login_required
def burning_plan_list(request):
    plans = BurningPlan.objects.select_related('pre_plan').all()
    return render(request, 'fire_actions/bp_list.html', {'plans': plans})


@login_required
def burning_plan_create(request, preplan_pk=None):
    preplan = get_object_or_404(FireAction, pk=preplan_pk) if preplan_pk else None

    # Guard: already has a burning plan
    if preplan and hasattr(preplan, 'burningplan'):
        messages.warning(request, 'Este pré-plano já tem um Plano de Queima.')
        return redirect('fire_actions:burning_plan_detail', pk=preplan.burningplan.pk)

    if request.method == 'POST':
        return _save_burning_plan(request, BurningPlan(), preplan)
    return _bp_form_response(request, None, preplan)


@login_required
def burning_plan_detail(request, pk):
    bp = get_object_or_404(BurningPlan.objects.select_related('pre_plan')
                           .prefetch_related('operatives', 'photos', 'pre_plan__parcels'), pk=pk)
    schema_url = bp.tactical_schema.url if bp.tactical_schema else None
    return render(request, 'fire_actions/bp_detail.html',
                  {'bp': bp, 'vehicles': _load_vehicles(bp), 'schema_url': schema_url})


@login_required
def burning_plan_edit(request, pk):
    bp = get_object_or_404(BurningPlan.objects.select_related('pre_plan'), pk=pk)
    if request.method == 'POST':
        return _save_burning_plan(request, bp, bp.pre_plan)
    return _bp_form_response(request, bp, bp.pre_plan)


@staff_required
def burning_plan_delete(request, pk):
    bp = get_object_or_404(BurningPlan, pk=pk)
    if request.method == 'POST':
        pp = bp.pre_plan
        photos = list(bp.photos.all())
        files = [p.image for p in photos] + ([bp.tactical_schema] if bp.tactical_schema else [])
        with transaction.atomic():
            bp.delete()
            for p in photos:
                p.delete()
            pp.status = 'Pre-Plano'
            pp.execution_date = None
            pp.save()
        # Remove stored files only after the DB changes are committed
        for f in files:
            try:
                f.delete(save=False)
            except Exception:
                logger.warning('Não foi possível apagar o ficheiro %s', f.name, exc_info=True)
        messages.success(request, 'Plano de Queima eliminado.')
        return redirect('fire_actions:burning_plan_list')
    return render(request, 'fire_actions/confirm_delete.html', {'obj': bp, 'tipo': 'Plano de Queima'})


@login_required
def burning_plan_report(request, pk):
    """Generate and return the Word (.docx) report."""
    bp = get_object_or_404(
        BurningPlan.objects.select_related('pre_plan')
                           .prefetch_related('operatives', 'photos', 'pre_plan__parcels'),
        pk=pk
    )
    try:
        from .report import generate_bp_docx
        docx_bytes = generate_bp_docx(bp)
    except Exception:
        logger.exception('Erro ao gerar relatório do plano %s', pk)
        messages.error(request, 'Erro ao gerar o relatório. O problema foi registado.')
        return redirect('fire_actions:burning_plan_detail', pk=pk)
    filename = f"PlanoQueima_{bp.pk}_{bp.execution_date}.docx"
    response = HttpResponse(
        docx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
