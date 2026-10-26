import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.gis.db.models.functions import Centroid
from django.core.serializers import serialize
from django.db import transaction
from django.db.models import Count, Max
from django.forms import inlineformset_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import staff_required
from core.emails import send_async
from core.forms import clean_photos, form_errors_to_messages
from .forms import EvaluationForm, FireParcelForm, parse_polygon
from .geo import admin_location, apply_location, area_ha, overlapping_parcels, terrain
from .models import EvaluationVegetation, FireParcel, ParcelEvaluation, ParcelPhoto

try:
    from fire_actions.models import BurningPlan
    HAS_BP = True
except ImportError:
    HAS_BP = False

VegetationFormSet = inlineformset_factory(
    ParcelEvaluation, EvaluationVegetation, fields=['species', 'cover_pct', 'height_m', 'age_years'],
    extra=3, can_delete=True)


# ── Permissions ──────────────────────────────────────────────────────────────

def is_tecnico(user):
    op = getattr(user, 'operative', None)
    return bool(op and op.is_tecnico)


def can_edit(user, parcel):
    """Proposer while still a proposal; técnicos and staff always."""
    if user.is_staff or is_tecnico(user):
        return True
    return parcel.pk is None or (parcel.proposed_by_id == user.pk and parcel.status == FireParcel.STATUS_PROPOSTA)


def _tecnico_emails():
    from operatives.models import Operative
    return [op.user.email for op in Operative.objects.filter(
        credential_type=Operative.CRED_TECNICO, credential_status=Operative.STATUS_VALIDADA,
        user__is_active=True).select_related('user') if op.is_tecnico and op.user.email]


# ── Helpers ──────────────────────────────────────────────────────────────────

def last_burn_date_for_parcela(parcela):
    """Return the most recent BurningPlan execution_date for this parcela, or None."""
    if not HAS_BP:
        return None
    return (BurningPlan.objects
            .filter(pre_plan__parcels=parcela)
            .order_by('-execution_date')
            .values_list('execution_date', flat=True)
            .first())


def parcel_centroids():
    """Parcel centroids (computed in PostGIS) as dicts for the weather/FiredPT map."""
    qs = FireParcel.objects.annotate(centroid=Centroid('geometry')).only('id', 'name')
    return [{'id': str(p.id), 'name': p.name,
             'lat': round(p.centroid.y, 6), 'lng': round(p.centroid.x, 6)}
            for p in qs if p.centroid]


# ── List / detail ────────────────────────────────────────────────────────────

@login_required
def parcela_list(request):
    qs = FireParcel.objects.annotate(last_burn=Max('fire_actions__burningplan__execution_date'))
    filters = {k: request.GET.get(k, '') for k in ('status', 'tipologia', 'concelho')}
    if filters['status']:
        qs = qs.filter(status=filters['status'])
    if filters['tipologia']:
        qs = qs.filter(vegetation_type=filters['tipologia'])
    if filters['concelho']:
        qs = qs.filter(concelho=filters['concelho'])
    parcelas = list(qs)
    counts = dict(FireParcel.objects.values_list('status').annotate(n=Count('id')))
    return render(request, 'parcelas/list.html', {
        'parcelas': parcelas,
        'total':    len(parcelas),
        'filters':  filters,
        'statuses': [(code, label, counts.get(code, 0)) for code, label in FireParcel.STATUS_CHOICES],
        'tipologias': FireParcel._meta.get_field('vegetation_type').choices,
        'concelhos': FireParcel.objects.exclude(concelho='').order_by('concelho')
                                       .values_list('concelho', flat=True).distinct(),
    })


@login_required
def parcela_detail(request, pk):
    parcela = get_object_or_404(FireParcel.objects.select_related('proposed_by'), pk=pk)
    evaluations = list(parcela.evaluations.select_related('evaluator').prefetch_related('vegetation', 'photos'))
    open_eval = next((e for e in evaluations if not e.is_complete), None)
    return render(request, 'parcelas/detail.html', {
        'parcela':     parcela,
        'geom_json':   parcela.geometry.json if parcela.geometry else '',
        'last_burn':   last_burn_date_for_parcela(parcela),
        'last_eval':   next((e for e in evaluations if e.is_complete), None),
        'open_eval':   open_eval,
        'evaluations': [e for e in evaluations if e.is_complete],
        'proposal_photos': parcela.photos.filter(stage='proposta'),
        'can_edit':    can_edit(request.user, parcela),
        'can_evaluate': is_tecnico(request.user),
    })


# ── Proposal (create / edit) ─────────────────────────────────────────────────

def _save_parcela(request, instance, action):
    """Shared create/edit handler. On edit, an empty geometry keeps the current one."""
    is_new = instance.pk is None
    form = FireParcelForm(request.POST, instance=instance)
    geom_str = request.POST.get('geometry', '')
    geom = geom_error = None
    if geom_str:
        geom, geom_error = parse_polygon(geom_str)
    elif is_new:
        geom_error = 'Geometria em falta. Desenhe a parcela no mapa.'
    photos, photo_errors = clean_photos(request.FILES.getlist('photos'))

    overlaps = []
    if form.is_valid() and not geom_error and not photo_errors:
        if geom and not request.POST.get('confirm_overlap'):
            overlaps = overlapping_parcels(geom, exclude_pk=instance.pk)
        if not overlaps:
            with transaction.atomic():
                parcela = form.save(commit=False)
                if is_new:
                    parcela.proposed_by = request.user
                    parcela.status = FireParcel.STATUS_PROPOSTA
                if geom:
                    parcela.geometry = geom
                    parcela.area_ha = area_ha(geom)
                    apply_location(parcela)
                parcela.save()
                for photo in photos:
                    ParcelPhoto.objects.create(parcel=parcela, image=photo, stage='proposta',
                                               uploaded_by=request.user)
            if is_new:
                _notify_new_proposal(request, parcela)
                messages.success(request, f'Parcela "{parcela.name}" proposta. Um técnico credenciado vai avaliá-la.')
            else:
                messages.success(request, f'Parcela "{parcela.name}" atualizada.')
            return redirect('parcelas:detail', pk=parcela.pk)
        messages.warning(request, 'A geometria sobrepõe-se a parcelas existentes. Confirme que não é uma parcela repetida.')
    else:
        form_errors_to_messages(request, form)
        if geom_error:
            messages.error(request, geom_error)
        for err in photo_errors:
            messages.error(request, f'Fotografias: {err}')
    if not geom_str and form.instance.geometry:
        geom_str = form.instance.geometry.json
    return render(request, 'parcelas/form.html', {
        'parcela':   form.instance,
        'geom_json': geom_str,
        'action':    action,
        'overlaps':  overlaps,
    })


def _notify_new_proposal(request, parcela):
    emails = _tecnico_emails()
    if emails:
        url = request.build_absolute_uri(reverse('parcelas:detail', args=[parcela.pk]))
        send_async('[Fogo Bom] Nova parcela proposta para avaliação',
                   f'Foi proposta a parcela "{parcela.name}" ({parcela.concelho or "concelho por determinar"}, '
                   f'{parcela.area_ha} ha) por {request.user.get_username()}.\n\nAvaliar em: {url}',
                   emails)


@login_required
def parcela_create(request):
    if request.method == 'POST':
        return _save_parcela(request, FireParcel(), 'Propor Parcela')
    return render(request, 'parcelas/form.html', {'action': 'Propor Parcela'})


@login_required
def parcela_edit(request, pk):
    parcela = get_object_or_404(FireParcel, pk=pk)
    if not can_edit(request.user, parcela):
        messages.error(request, 'Só o proponente (enquanto a parcela não é avaliada) ou um técnico podem editar esta parcela.')
        return redirect('parcelas:detail', pk=pk)
    if request.method == 'POST':
        return _save_parcela(request, parcela, 'Editar Parcela')
    return render(request, 'parcelas/form.html', {
        'parcela':   parcela,
        'geom_json': parcela.geometry.json if parcela.geometry else '',
        'action':    'Editar Parcela',
    })


@staff_required
def parcela_delete(request, pk):
    parcela = get_object_or_404(FireParcel, pk=pk)
    if request.method == 'POST':
        name = parcela.name
        parcela.delete()
        messages.success(request, f'Parcela "{name}" eliminada.')
        return redirect('parcelas:list')
    return render(request, 'parcelas/confirm_delete.html', {'parcela': parcela})


# ── Technical evaluation ─────────────────────────────────────────────────────

def _tecnico_required(request):
    if not is_tecnico(request.user):
        messages.error(request, 'A avaliação de parcelas é reservada a técnicos credenciados (credenciação validada).')
        return False
    return True


@require_POST
@login_required
def evaluation_start(request, pk):
    parcela = get_object_or_404(FireParcel, pk=pk)
    if not _tecnico_required(request):
        return redirect('parcelas:detail', pk=pk)
    open_eval = parcela.evaluations.filter(completed_at__isnull=True).first()
    if open_eval:
        return redirect('parcelas:evaluation', pk=open_eval.pk)
    ev = ParcelEvaluation(parcel=parcela, evaluator=request.user)
    _fill_terrain(ev)
    previous = parcela.latest_evaluation
    if previous:  # re-evaluation starts from the previous data
        for f in ParcelEvaluation._meta.concrete_fields:
            if f.name not in ('id', 'parcel', 'evaluator', 'started_at', 'completed_at', 'visit_date',
                              'decision', 'justification', 'altitude_m', 'slope_pct', 'aspect', 'terrain_source'):
                setattr(ev, f.attname, getattr(previous, f.attname))
    with transaction.atomic():
        ev.save()
        if previous:
            for v in previous.vegetation.all():
                EvaluationVegetation.objects.create(evaluation=ev, species=v.species, cover_pct=v.cover_pct,
                                                    height_m=v.height_m, age_years=v.age_years)
        if parcela.status == FireParcel.STATUS_PROPOSTA:
            parcela.status = FireParcel.STATUS_AVALIACAO
            parcela.save(update_fields=['status'])
    return redirect('parcelas:evaluation', pk=ev.pk)


def _fill_terrain(ev):
    t = terrain(ev.parcel.geometry)
    if t:
        ev.altitude_m, ev.slope_pct, ev.aspect, ev.terrain_source = (
            t['altitude_m'], t['slope_pct'], t['aspect'], t['source'])
    return t


@login_required
def evaluation_edit(request, pk):
    ev = get_object_or_404(ParcelEvaluation.objects.select_related('parcel', 'evaluator'), pk=pk)
    parcela = ev.parcel
    if ev.is_complete:
        return redirect('parcelas:detail', pk=parcela.pk)
    if not _tecnico_required(request):
        return redirect('parcelas:detail', pk=parcela.pk)

    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action == 'cancel':
            with transaction.atomic():
                ev.delete()
                if parcela.status == FireParcel.STATUS_AVALIACAO:
                    parcela.status = FireParcel.STATUS_PROPOSTA
                    parcela.save(update_fields=['status'])
            messages.info(request, 'Avaliação cancelada.')
            return redirect('parcelas:detail', pk=parcela.pk)
        if action == 'terrain':
            if _fill_terrain(ev):
                ev.save(update_fields=['altitude_m', 'slope_pct', 'aspect', 'terrain_source'])
                messages.success(request, 'Relevo recalculado.')
            else:
                messages.error(request, 'Não foi possível calcular o relevo automaticamente. Preencha à mão.')
            return redirect('parcelas:evaluation', pk=ev.pk)

        form = EvaluationForm(request.POST, instance=ev)
        form.concluding = action == 'conclude'
        formset = VegetationFormSet(request.POST, instance=ev, prefix='veg')
        photos, photo_errors = clean_photos(request.FILES.getlist('photos'))
        if form.is_valid() and formset.is_valid() and not photo_errors:
            with transaction.atomic():
                ev = form.save()
                formset.save()
                for photo in photos:
                    ParcelPhoto.objects.create(parcel=parcela, evaluation=ev, image=photo, stage='avaliacao',
                                               uploaded_by=request.user)
                if form.concluding:
                    ev.completed_at = timezone.now()
                    ev.evaluator = request.user
                    ev.save(update_fields=['completed_at', 'evaluator'])
                    parcela.status = ev.decision
                    parcela.save(update_fields=['status'])
            if form.concluding:
                _notify_decision(request, parcela, ev)
                messages.success(request, f'Avaliação concluída: parcela {ev.get_decision_display().lower()}.')
                return redirect('parcelas:detail', pk=parcela.pk)
            messages.success(request, 'Avaliação guardada (rascunho).')
            return redirect('parcelas:evaluation', pk=ev.pk)
        form_errors_to_messages(request, form)
        for i, errs in enumerate(formset.errors):
            for field, msgs in errs.items():
                messages.error(request, f'Vegetação, linha {i + 1}: {"; ".join(msgs)}')
        for err in photo_errors:
            messages.error(request, f'Fotografias: {err}')
    else:
        form = EvaluationForm(instance=ev)
        formset = VegetationFormSet(instance=ev, prefix='veg')

    return render(request, 'parcelas/evaluation_form.html', {
        'ev': ev, 'parcela': parcela, 'form': form, 'formset': formset,
        'geom_json': parcela.geometry.json,
        'sections': [(title, [(form[n], n in WIDE_FIELDS) for n in names]) for title, names in EVALUATION_SECTIONS],
        'decision_fields': [form[n] for n in ('visit_date', 'decision', 'justification', 'conditions')],
        'difficulty_fields': [form[f] for f, _, _ in ParcelEvaluation.DIFFICULTY_ELEMENTS],
    })


EVALUATION_SECTIONS = [
    ('Caracterização física', ['altitude_m', 'slope_pct', 'aspect', 'topography', 'rocks_pct', 'terraces']),
    ('Combustível', ['fuel_load', 'litter_cm']),
    ('Condicionantes', ['access', 'water_points', 'existing_strips', 'new_strips_needed', 'buildings_nearby',
                        'smoke_sensitive', 'protected_area', 'constraints_notes']),
    ('Tratamento proposto', ['recommended_type', 'objectives', 'queimada_purpose', 'prescription_notes',
                             'include_in_pfc']),
]


WIDE_FIELDS = {'access', 'water_points', 'existing_strips', 'constraints_notes', 'objectives',
               'prescription_notes'}


def _notify_decision(request, parcela, ev):
    if parcela.proposed_by and parcela.proposed_by.email and parcela.proposed_by != request.user:
        url = request.build_absolute_uri(reverse('parcelas:detail', args=[parcela.pk]))
        extra = f'\nCondicionantes: {ev.conditions}' if ev.conditions else ''
        send_async(f'[Fogo Bom] Parcela "{parcela.name}" avaliada',
                   f'A parcela "{parcela.name}" que propôs foi avaliada por {request.user.get_username()}.\n\n'
                   f'Decisão: {ev.get_decision_display()}\nJustificação: {ev.justification}{extra}\n\n{url}',
                   [parcela.proposed_by.email])


# ── API endpoints ─────────────────────────────────────────────────────────────

@login_required
def parcelas_geojson(request):
    """Returns all parcelas as GeoJSON for map consumption."""
    parcelas = FireParcel.objects.all()
    geojson  = serialize('geojson', parcelas, geometry_field='geometry',
                         fields=['name', 'concelho', 'vegetation_type', 'infrastructure', 'area_ha',
                                 'owner_info', 'status'])
    return HttpResponse(geojson, content_type='application/json')


@login_required
def parcelas_centroids(request):
    """Returns parcela centroids as JSON for FiredPT."""
    return JsonResponse(parcel_centroids(), safe=False)


@require_POST
@login_required
def parcela_preview(request):
    """Live preview while drawing: area, CAOP location and overlaps for a GeoJSON geometry."""
    try:
        body = json.loads(request.body or '{}')
        geom, err = parse_polygon(json.dumps(body.get('geometry')))
    except ValueError:
        geom, err = None, 'Pedido inválido.'
    if err:
        return JsonResponse({'error': err}, status=400)
    overlaps = overlapping_parcels(geom, exclude_pk=body.get('exclude'))
    return JsonResponse({
        'area_ha': area_ha(geom),
        'location': admin_location(geom),
        'overlaps': [{'name': p.name, 'pk': p.pk, 'ha': ha} for p, ha in overlaps],
    })
