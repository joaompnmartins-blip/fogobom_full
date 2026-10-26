from django import forms

from .models import Assessment, ParcelCriterion


class YesNoSelect(forms.NullBooleanSelect):
    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.choices = [('unknown', '—'), ('true', 'Sim'), ('false', 'Não')]


PERCENT_FIELDS = ['soil_exposed_pct', 'herb_resprout_pct', 'shrub_crown_consumed_pct', 'shrub_dead_crowns_pct',
                  'shrub_resprout_pct', 'tree_scorch_pct', 'tree_mortality_pct', 'soil_cover_pct',
                  'soil_organic_matter_pct', 'veg_cover_pct']


class AssessmentForm(forms.ModelForm):
    """Shows only the fields of the visit's phase (1.ª fase, 2.ª fase or annual)."""

    class Meta:
        model = Assessment
        exclude = ['execution', 'phase', 'year', 'observer', 'created_at']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   **{f: forms.Textarea(attrs={'rows': 2}) for f in ('soil_notes', 'veg_species', 'notes')}}

    def __init__(self, *args, phase, criteria=(), **kwargs):
        super().__init__(*args, **kwargs)
        keep = set(Assessment.fields_for(phase)) | {'date'}
        for name in list(self.fields):
            if name not in keep:
                del self.fields[name]
            elif isinstance(self.fields[name], forms.NullBooleanField):
                self.fields[name].widget = YesNoSelect()
        self.criteria = list(criteria)
        values = {}
        if self.instance.pk:
            values = {v.criterion_id: v.value for v in self.instance.criterion_values.all()}
        for c in self.criteria:
            self.fields[f'crit_{c.pk}'] = forms.CharField(label=str(c), required=False, max_length=200,
                                                          help_text=c.description, initial=values.get(c.pk, ''))

    def clean(self):
        data = super().clean()
        for f in PERCENT_FIELDS:
            v = data.get(f)
            if v is not None and not 0 <= v <= 100:
                self.add_error(f, 'Valor entre 0 e 100.')
        ph = data.get('soil_ph')
        if ph is not None and not 0 <= ph <= 14:
            self.add_error('soil_ph', 'pH entre 0 e 14.')
        lo, hi = data.get('tree_bole_min_m'), data.get('tree_bole_max_m')
        if lo is not None and hi is not None and lo > hi:
            self.add_error('tree_bole_max_m', 'O máximo não pode ser inferior ao mínimo.')
        return data

    def sections(self):
        """[(title, [bound fields])] for the fields present in this phase."""
        out = []
        for title, names in Assessment.SECTIONS:
            fields = [self[n] for n in names if n in self.fields]
            if fields:
                out.append((title, fields))
        if self.criteria:
            out.append(('Critérios específicos da parcela', [self[f'crit_{c.pk}'] for c in self.criteria]))
        return out

    def criterion_values(self):
        return {c: (self.cleaned_data.get(f'crit_{c.pk}') or '').strip() for c in self.criteria}


CriterionFormSet = forms.modelformset_factory(
    ParcelCriterion, fields=['name', 'unit', 'description', 'active'], extra=3, can_delete=True)
