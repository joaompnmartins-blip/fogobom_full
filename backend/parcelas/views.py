from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from core.decorators import staff_required
from core.forms import form_errors_to_messages
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.serializers import serialize
from django.contrib.gis.db.models.functions import Centroid
from django.db.models import Max
from .forms import FireParcelForm, parse_polygon, area_ha
from .models import FireParcel
try:
    from fire_actions.models import BurningPlan
    HAS_BP = True
except ImportError:
    HAS_BP = False


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


@login_required
def parcela_list(request):
    # Most recent burning plan execution date per parcela, in a single query
    parcelas = list(FireParcel.objects.annotate(
        last_burn=Max('fire_actions__burningplan__execution_date')))
    return render(request, 'parcelas/list.html', {
        'parcelas': parcelas,
        'total':    len(parcelas),
    })


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

    if form.is_valid() and not geom_error:
        parcela = form.save(commit=False)
        if geom:
            parcela.geometry = geom
            parcela.area_ha  = area_ha(geom)
        parcela.save()
        verb = 'criada com sucesso' if is_new else 'atualizada'
        messages.success(request, f'Parcela "{parcela.name}" {verb}.')
        return redirect('parcelas:list')

    form_errors_to_messages(request, form)
    if geom_error:
        messages.error(request, geom_error)
    if not geom_str and form.instance.geometry:
        geom_str = form.instance.geometry.json
    return render(request, 'parcelas/form.html', {
        'parcela':   form.instance,
        'geom_json': geom_str,
        'action':    action,
    })


@login_required
def parcela_create(request):
    if request.method == 'POST':
        return _save_parcela(request, FireParcel(), 'Nova Parcela')
    return render(request, 'parcelas/form.html', {'action': 'Nova Parcela'})


@login_required
def parcela_edit(request, pk):
    parcela = get_object_or_404(FireParcel, pk=pk)
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


@login_required
def parcela_detail(request, pk):
    parcela  = get_object_or_404(FireParcel, pk=pk)
    geom_json = parcela.geometry.json if parcela.geometry else ''
    last_burn = last_burn_date_for_parcela(parcela)
    return render(request, 'parcelas/detail.html', {
        'parcela':   parcela,
        'geom_json': geom_json,
        'last_burn': last_burn,
    })


# ── API endpoints ─────────────────────────────────────────────────────────────

@login_required
def parcelas_geojson(request):
    """Returns all parcelas as GeoJSON for map consumption."""
    parcelas = FireParcel.objects.all()
    geojson  = serialize('geojson', parcelas, geometry_field='geometry',
                         fields=['name','concelho','vegetation_type','infrastructure','area_ha','owner_info'])
    return HttpResponse(geojson, content_type='application/json')


@login_required
def parcelas_centroids(request):
    """Returns parcela centroids as JSON for FiredPT."""
    return JsonResponse(parcel_centroids(), safe=False)
