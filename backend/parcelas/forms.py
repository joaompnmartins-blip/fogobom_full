from django import forms
from django.contrib.gis.geos import GEOSGeometry, Polygon, MultiPolygon
from .geo import area_ha  # noqa: F401  (re-exported for views)
from .models import FireParcel, ParcelEvaluation


class FireParcelForm(forms.ModelForm):
    """Parcel proposal: simple data only; location and area are computed."""
    class Meta:
        model  = FireParcel
        fields = ['name', 'vegetation_type', 'infrastructure', 'owner_info', 'resp_name', 'resp_email', 'notes']
        labels = {
            'name': 'Nome / referência', 'vegetation_type': 'Tipologia', 'infrastructure': 'Infraestruturas',
            'owner_info': 'Existem dados do proprietário', 'resp_name': 'Responsável de contacto',
            'resp_email': 'Email de contacto', 'notes': 'Observações',
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


class EvaluationForm(forms.ModelForm):
    """Technical evaluation. Decision fields are only required when concluding."""
    objectives = forms.MultipleChoiceField(label='Objetivos', choices=ParcelEvaluation.OBJECTIVES, required=False,
                                           widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = ParcelEvaluation
        exclude = ['parcel', 'evaluator', 'started_at', 'completed_at', 'terrain_source']
        widgets = {
            'visit_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            **{f: forms.Textarea(attrs={'rows': 2}) for f in (
                'justification', 'conditions', 'access', 'water_points', 'existing_strips',
                'constraints_notes', 'prescription_notes')},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['objectives'] = self.instance.objectives_list
        for f in ('rocks_pct',):
            self.fields[f].max_value = 100
        self.concluding = False

    def clean_objectives(self):
        return ','.join(self.cleaned_data.get('objectives') or [])

    def clean(self):
        data = super().clean()
        for f in ('rocks_pct',):
            v = data.get(f)
            if v is not None and v > 100:
                self.add_error(f, 'Valor entre 0 e 100.')
        if self.concluding:
            if not data.get('visit_date'):
                self.add_error('visit_date', 'Obrigatória para concluir a avaliação (a avaliação exige visita ao terreno).')
            if not data.get('decision'):
                self.add_error('decision', 'Escolha a decisão.')
            if not (data.get('justification') or '').strip():
                self.add_error('justification', 'A justificação é obrigatória.')
            if data.get('decision') == 'apta_condicionantes' and not (data.get('conditions') or '').strip():
                self.add_error('conditions', 'Descreva as condicionantes.')
        return data
