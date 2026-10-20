from django import forms
from django.contrib.gis.geos import GEOSGeometry, Polygon, MultiPolygon
from .models import FireParcel


class FireParcelForm(forms.ModelForm):
    class Meta:
        model  = FireParcel
        fields = ['name', 'concelho', 'vegetation_type', 'infrastructure',
                  'owner_info', 'resp_name', 'resp_email']
        labels = {
            'name': 'Nome', 'concelho': 'Concelho', 'vegetation_type': 'Tipo de Vegetação',
            'infrastructure': 'Infraestrutura', 'owner_info': 'Proprietário identificado',
            'resp_name': 'Nome do Responsável', 'resp_email': 'Email do Responsável',
        }


def parse_polygon(geom_str):
    """Parse GeoJSON/WKT into a Polygon (largest part if multi). Returns (polygon, error)."""
    try:
        geom = GEOSGeometry(geom_str, srid=4326)
    except Exception:
        return None, 'Geometria inválida. Redesenhe ou importe novamente a parcela.'
    if isinstance(geom, MultiPolygon):
        geom = max(geom, key=lambda p: p.area)
    if not isinstance(geom, Polygon):
        return None, 'A geometria deve ser um polígono.'
    if not geom.valid:
        return None, 'O polígono é inválido (por exemplo, linhas que se cruzam).'
    return geom, None


def area_ha(geom):
    return round(geom.transform(3763, clone=True).area / 10000, 4)  # Portuguese TM06
