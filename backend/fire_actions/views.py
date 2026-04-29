import json
import os
import tempfile
import base64
from io import BytesIO
from datetime import date
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, HttpResponse
from .models import FireAction, BurningPlan, BurningPlanPhoto, PrePlanPhoto
from parcelas.models import FireParcel
from operatives.models import Operative



def save_tactical_schema(bp, b64_data):
    """Decode base64 PNG and save to bp.tactical_schema."""
    if not b64_data:
        return
    try:
        # strip data URI prefix if present
        if ',' in b64_data:
            b64_data = b64_data.split(',', 1)[1]
        img_bytes = base64.b64decode(b64_data)
        fname = f"schema_bp{bp.pk}_{bp.execution_date}.png"
        bp.tactical_schema.save(fname, ContentFile(img_bytes), save=True)
    except Exception as e:
        pass  # non-critical — don't break the save


# ── Pré-Planos ────────────────────────────────────────────────────────────────

@login_required
def preplan_list(request):
    actions = FireAction.objects.prefetch_related('parcels').all()
    return render(request, 'fire_actions/preplan_list.html', {'actions': actions})


@login_required
def preplan_create(request):
    parcelas   = FireParcel.objects.all()
    operatives = Operative.objects.all()

    if request.method == 'POST':
        try:
            action = FireAction.objects.create(
                name           = request.POST['name'],
                responsible    = request.POST.get('responsible', ''),
                scheduled_date = request.POST['scheduled_date'],
                notes          = request.POST.get('notes', ''),
            )
            parcel_ids = request.POST.getlist('parcels')
            if parcel_ids:
                action.parcels.set(FireParcel.objects.filter(pk__in=parcel_ids))

            # Photos
            for photo in request.FILES.getlist('photos'):
                pp = PrePlanPhoto.objects.create(image=photo)
                # attach via related name after BurningPlan is created if needed

            messages.success(request, f'Pré-Plano "{action.name}" criado.')
            return redirect('fire_actions:list')
        except Exception as e:
            messages.error(request, f'Erro: {e}')

    return render(request, 'fire_actions/preplan_form.html', {
        'parcelas':   parcelas,
        'operatives': operatives,
        'action_obj': None,
    })


@login_required
def preplan_edit(request, pk):
    action     = get_object_or_404(FireAction, pk=pk)
    parcelas   = FireParcel.objects.all()
    operatives = Operative.objects.all()

    if request.method == 'POST':
        try:
            action.name           = request.POST['name']
            action.responsible    = request.POST.get('responsible', '')
            action.scheduled_date = request.POST['scheduled_date']
            action.notes          = request.POST.get('notes', '')
            action.save()

            parcel_ids = request.POST.getlist('parcels')
            action.parcels.set(FireParcel.objects.filter(pk__in=parcel_ids))

            messages.success(request, f'Pré-Plano "{action.name}" atualizado.')
            return redirect('fire_actions:list')
        except Exception as e:
            messages.error(request, f'Erro: {e}')

    return render(request, 'fire_actions/preplan_form.html', {
        'parcelas':        parcelas,
        'operatives':      operatives,
        'action_obj':      action,
        'selected_parcels': list(action.parcels.values_list('pk', flat=True)),
    })


@login_required
def preplan_delete(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
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

@login_required
def burning_plan_list(request):
    plans = BurningPlan.objects.select_related('pre_plan').all()
    return render(request, 'fire_actions/bp_list.html', {'plans': plans})


@login_required
def burning_plan_create(request, preplan_pk=None):
    operatives = Operative.objects.all()
    preplan    = get_object_or_404(FireAction, pk=preplan_pk) if preplan_pk else None

    # Guard: already has a burning plan
    if preplan and hasattr(preplan, 'burningplan'):
        messages.warning(request, 'Este pré-plano já tem um Plano de Queima.')
        return redirect('fire_actions:burning_plan_detail', pk=preplan.burningplan.pk)

    if request.method == 'POST':
        try:
            pp_id = request.POST.get('pre_plan')
            pp    = get_object_or_404(FireAction, pk=pp_id)

            vehicles = json.dumps({
                'VFCI':  int(request.POST.get('vfci', 0) or 0),
                'VFCM':  int(request.POST.get('vfcm', 0) or 0),
                'Outro': request.POST.get('other_veh', ''),
            })

            bp = BurningPlan.objects.create(
                pre_plan            = pp,
                execution_date      = request.POST['execution_date'],
                num_men             = request.POST.get('num_men') or None,
                vehicles            = vehicles,
                problems            = request.POST.get('problems', ''),
                fuel_superficial    = request.POST.get('fuel_superficial', ''),
                fuel_manta_f        = request.POST.get('fuel_manta_f', ''),
                fuel_manta_h        = request.POST.get('fuel_manta_h', ''),
                weather_state       = request.POST.get('weather_state', ''),
                wind_speed_beaufort = request.POST.get('wind_speed_beaufort', ''),
                wind_speed_kmh      = request.POST.get('wind_speed_kmh', ''),
                wind_direction      = request.POST.get('wind_direction', ''),
                fire_conduct        = request.POST.get('fire_conduct', ''),
                fire_conduct_other  = request.POST.get('fire_conduct_other', ''),
                burn_effects        = request.POST.get('burn_effects', ''),
                burn_efficiency     = request.POST.get('burn_efficiency', ''),
                notes               = request.POST.get('notes', ''),
            )

            op_ids = request.POST.getlist('operatives')
            if op_ids:
                bp.operatives.set(Operative.objects.filter(pk__in=op_ids))

            # Photos
            for photo in request.FILES.getlist('photos'):
                p = BurningPlanPhoto.objects.create(image=photo)
                bp.photos.add(p)

            # Tactical schema
            schema_b64 = request.POST.get('tactical_schema_b64', '')
            if schema_b64:
                save_tactical_schema(bp, schema_b64)

            # Mark pre-plan as executed
            pp.status = 'Executada'
            pp.execution_date = bp.execution_date
            pp.save()

            messages.success(request, 'Plano de Queima criado com sucesso.')
            return redirect('fire_actions:burning_plan_detail', pk=bp.pk)
        except Exception as e:
            messages.error(request, f'Erro: {e}')

    preplans_without_bp = FireAction.objects.filter(burningplan__isnull=True)
    parcels_geom = []
    if preplan:
        for p in preplan.parcels.all():
            if p.geometry:
                parcels_geom.append({'name': p.name, 'geojson': p.geometry.json})
    return render(request, 'fire_actions/bp_form.html', {
        'operatives':          operatives,
        'preplan':             preplan,
        'preplans_without_bp': preplans_without_bp,
        'bp':                  None,
        'parcels_geom_json':   json.dumps(parcels_geom),
    })


@login_required
def burning_plan_detail(request, pk):
    bp = get_object_or_404(BurningPlan.objects.select_related('pre_plan')
                           .prefetch_related('operatives', 'photos', 'pre_plan__parcels'), pk=pk)
    try:
        vehicles = json.loads(bp.vehicles or '{}')
    except Exception:
        vehicles = {}
    schema_url = bp.tactical_schema.url if bp.tactical_schema else None
    return render(request, 'fire_actions/bp_detail.html', {'bp': bp, 'vehicles': vehicles, 'schema_url': schema_url})


@login_required
def burning_plan_edit(request, pk):
    bp         = get_object_or_404(BurningPlan, pk=pk)
    operatives = Operative.objects.all()

    if request.method == 'POST':
        try:
            vehicles = json.dumps({
                'VFCI':  int(request.POST.get('vfci', 0) or 0),
                'VFCM':  int(request.POST.get('vfcm', 0) or 0),
                'Outro': request.POST.get('other_veh', ''),
            })
            bp.execution_date      = request.POST['execution_date']
            bp.num_men             = request.POST.get('num_men') or None
            bp.vehicles            = vehicles
            bp.problems            = request.POST.get('problems', '')
            bp.fuel_superficial    = request.POST.get('fuel_superficial', '')
            bp.fuel_manta_f        = request.POST.get('fuel_manta_f', '')
            bp.fuel_manta_h        = request.POST.get('fuel_manta_h', '')
            bp.weather_state       = request.POST.get('weather_state', '')
            bp.wind_speed_beaufort = request.POST.get('wind_speed_beaufort', '')
            bp.wind_speed_kmh      = request.POST.get('wind_speed_kmh', '')
            bp.wind_direction      = request.POST.get('wind_direction', '')
            bp.fire_conduct        = request.POST.get('fire_conduct', '')
            bp.fire_conduct_other  = request.POST.get('fire_conduct_other', '')
            bp.burn_effects        = request.POST.get('burn_effects', '')
            bp.burn_efficiency     = request.POST.get('burn_efficiency', '')
            bp.notes               = request.POST.get('notes', '')
            bp.save()

            op_ids = request.POST.getlist('operatives')
            bp.operatives.set(Operative.objects.filter(pk__in=op_ids))

            for photo in request.FILES.getlist('photos'):
                p = BurningPlanPhoto.objects.create(image=photo)
                bp.photos.add(p)

            # Tactical schema
            schema_b64 = request.POST.get('tactical_schema_b64', '')
            if schema_b64:
                save_tactical_schema(bp, schema_b64)

            messages.success(request, 'Plano de Queima atualizado.')
            return redirect('fire_actions:burning_plan_detail', pk=bp.pk)
        except Exception as e:
            messages.error(request, f'Erro: {e}')

    try:
        vehicles = json.loads(bp.vehicles or '{}')
    except Exception:
        vehicles = {}

    schema_url = bp.tactical_schema.url if bp.tactical_schema else None
    # Serialise parcela geometries for the tactical map
    parcels_geom = []
    for p in bp.pre_plan.parcels.all():
        if p.geometry:
            parcels_geom.append({'name': p.name, 'geojson': p.geometry.json})
    return render(request, 'fire_actions/bp_form.html', {
        'bp':                  bp,
        'operatives':          operatives,
        'preplan':             bp.pre_plan,
        'vehicles':            vehicles,
        'selected_operatives': list(bp.operatives.values_list('pk', flat=True)),
        'schema_url':          schema_url,
        'parcels_geom_json':   json.dumps(parcels_geom),
    })


@login_required
def burning_plan_delete(request, pk):
    bp = get_object_or_404(BurningPlan, pk=pk)
    if request.method == 'POST':
        pp = bp.pre_plan
        bp.delete()
        pp.status = 'Pre-Plano'
        pp.execution_date = None
        pp.save()
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
        filename   = f"PlanoQueima_{bp.pk}_{bp.execution_date}.docx"
        response   = HttpResponse(
            docx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        messages.error(request, f'Erro ao gerar relatório: {e}')
        return redirect('fire_actions:burning_plan_detail', pk=pk)
