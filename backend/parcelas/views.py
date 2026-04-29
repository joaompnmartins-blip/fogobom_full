import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.serializers import serialize
from django.contrib.gis.geos import GEOSGeometry, Polygon, MultiPolygon
from .models import FireParcel
try:
    from fire_actions.models import BurningPlan
    HAS_BP = True
except ImportError:
    HAS_BP = False


def coerce_to_polygon(geom):
    """Accept Polygon or MultiPolygon; returns a Polygon (largest part if multi)."""
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom, key=lambda p: p.area)
    return None


def last_burn_date_for_parcela(parcela):
    """Return the most recent BurningPlan execution_date for this parcela, or None."""
    if not HAS_BP:
        return None
    return (BurningPlan.objects
            .filter(pre_plan__parcels=parcela)
            .order_by('-execution_date')
            .values_list('execution_date', flat=True)
            .first())


@login_required
def parcela_list(request):
    parcelas = FireParcel.objects.all()
    geojson  = serialize('geojson', parcelas, geometry_field='geometry',
                         fields=['name','concelho','vegetation_type','infrastructure','area_ha','owner_info','id'])
    # Attach last_burn directly on each parcela for easy template access
    parcelas = list(parcelas)
    for p in parcelas:
        p.last_burn = last_burn_date_for_parcela(p)
    return render(request, 'parcelas/list.html', {
        'parcelas':      parcelas,
        'geojson':       geojson,
        'total':         len(parcelas),
    })


@login_required
def parcela_create(request):
    if request.method == 'POST':
        try:
            geom_str = request.POST.get('geometry', '')
            if not geom_str:
                messages.error(request, 'Geometria em falta. Desenhe a parcela no mapa.')
                return render(request, 'parcelas/form.html', {'form_data': request.POST})

            geom = coerce_to_polygon(GEOSGeometry(geom_str, srid=4326))
            if geom is None:
                messages.error(request, 'A geometria deve ser um polígono.')
                return render(request, 'parcelas/form.html', {'form_data': request.POST})

            geom_proj = geom.transform(3763, clone=True)  # Portuguese TM06
            area_ha = round(geom_proj.area / 10000, 4)

            FireParcel.objects.create(
                name             = request.POST['name'],
                concelho         = request.POST.get('concelho', ''),
                vegetation_type  = request.POST.get('vegetation_type', 'matos'),
                infrastructure   = request.POST.get('infrastructure', 'no_info'),
                owner_info       = request.POST.get('owner_info', 'no'),
                resp_name        = request.POST.get('resp_name') or None,
                resp_email       = request.POST.get('resp_email') or None,
                geometry         = geom,
                area_ha          = area_ha,
            )
            messages.success(request, f'Parcela "{request.POST["name"]}" criada com sucesso.')
            return redirect('parcelas:list')

        except Exception as e:
            messages.error(request, f'Erro ao criar parcela: {e}')

    return render(request, 'parcelas/form.html', {'action': 'Nova Parcela'})


@login_required
def parcela_edit(request, pk):
    parcela = get_object_or_404(FireParcel, pk=pk)

    if request.method == 'POST':
        try:
            geom_str = request.POST.get('geometry', '')
            geom_raw = GEOSGeometry(geom_str, srid=4326) if geom_str else parcela.geometry
            geom = coerce_to_polygon(geom_raw) if geom_str else geom_raw
            if geom_str and geom is None:
                messages.error(request, 'A geometria deve ser um polígono.')
                return render(request, 'parcelas/form.html', {'parcela': parcela, 'geom_json': geom_str, 'action': 'Editar Parcela'})
            if geom_str:
                geom_proj = geom.transform(3763, clone=True)
                parcela.area_ha = round(geom_proj.area / 10000, 4)
                parcela.geometry = geom

            parcela.name             = request.POST['name']
            parcela.concelho         = request.POST.get('concelho', '')
            parcela.vegetation_type  = request.POST.get('vegetation_type', 'matos')
            parcela.infrastructure   = request.POST.get('infrastructure', 'no_info')
            parcela.owner_info       = request.POST.get('owner_info', 'no')
            parcela.resp_name        = request.POST.get('resp_name') or None
            parcela.resp_email       = request.POST.get('resp_email') or None
            parcela.save()

            messages.success(request, f'Parcela "{parcela.name}" atualizada.')
            return redirect('parcelas:list')

        except Exception as e:
            messages.error(request, f'Erro ao atualizar: {e}')

    geom_json = parcela.geometry.json if parcela.geometry else ''
    return render(request, 'parcelas/form.html', {
        'parcela':   parcela,
        'geom_json': geom_json,
        'action':    'Editar Parcela',
    })


@login_required
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
    parcelas = []
    for p in FireParcel.objects.all():
        try:
            c = p.geometry.centroid
            parcelas.append({'id': str(p.id), 'name': p.name,
                             'lat': round(c.y, 6), 'lng': round(c.x, 6)})
        except Exception:
            continue
    return JsonResponse(parcelas, safe=False)
