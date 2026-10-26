from django import forms

from parcelas.models import FireParcel
from .models import MAX_VALIDITY_YEARS, PFC, PFCParcel

DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
TEXT = lambda rows=4: forms.Textarea(attrs={'rows': rows})


class PFCForm(forms.ModelForm):
    class Meta:
        model = PFC
        fields = ['sequence', 'name', 'proponent', 'proponent_contact', 'management_unit', 'dcnf',
                  'military_map_sheets', 'validity_start', 'validity_end', 'approval_entity',
                  'characterization', 'fire_history', 'dfci_infrastructure', 'objectives', 'means',
                  'emergency_plan', 'other_elements']
        widgets = {'validity_start': DATE, 'validity_end': DATE,
                   **{f: TEXT() for f in ('characterization', 'fire_history', 'dfci_infrastructure', 'objectives',
                                          'means', 'emergency_plan', 'other_elements')}}

    def __init__(self, *args, credential_number=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.credential_number = credential_number or self.instance.credential_number

    def clean(self):
        data = super().clean()
        start, end = data.get('validity_start'), data.get('validity_end')
        if start and end:
            if end <= start:
                self.add_error('validity_end', 'Tem de ser posterior ao início.')
            else:
                try:
                    limit = start.replace(year=start.year + MAX_VALIDITY_YEARS)
                except ValueError:  # 29 February
                    limit = start.replace(year=start.year + MAX_VALIDITY_YEARS, day=28)
                if end > limit:
                    self.add_error('validity_end', f'O PFC é válido no máximo {MAX_VALIDITY_YEARS} anos (art. 12.º).')
        seq = data.get('sequence')
        if seq and self.credential_number and PFC.objects.filter(
                credential_number=self.credential_number, sequence=seq).exclude(pk=self.instance.pk).exists():
            self.add_error('sequence', 'Já existe um PFC deste técnico com este n.º sequencial.')
        return data


class PFCParcelForm(forms.ModelForm):
    class Meta:
        model = PFCParcel
        exclude = ['pfc']
        widgets = {'occupation': TEXT(3)}

    def __init__(self, *args, pfc=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pfc = pfc
        used = pfc.plan_parcels.exclude(pk=self.instance.pk).values('parcel') if pfc else []
        qs = FireParcel.objects.filter(status__in=FireParcel.AVAILABLE_STATUSES).exclude(pk__in=used)
        if self.instance.pk:
            qs = qs | FireParcel.objects.filter(pk=self.instance.parcel_id)
        self.fields['parcel'].queryset = qs.order_by('name')
        self.fields['parcel'].label = 'Parcela (só parcelas aptas)'
        seasons = pfc.seasons() if pfc else []
        self.fields['season'] = forms.ChoiceField(label='Época de queima (out.–mai.)', required=False,
                                                  choices=[('', '—')] + [(s, s) for s in seasons])

    def clean(self):
        data = super().clean()
        for a, b in [('dry_days_min', 'dry_days_max'), ('temp_min', 'temp_max'), ('rh_min', 'rh_max'),
                     ('litter_moisture_min', 'litter_moisture_max'), ('wind_min', 'wind_max'),
                     ('spread_min', 'spread_max'), ('flame_min', 'flame_max')]:
            if data.get(a) is not None and data.get(b) is not None and data[a] > data[b]:
                self.add_error(b, 'O máximo tem de ser maior ou igual ao mínimo.')
        number = data.get('number')
        if number and self.pfc and self.pfc.plan_parcels.filter(number=number).exclude(pk=self.instance.pk).exists():
            self.add_error('number', 'Já existe uma parcela com este número neste PFC.')
        return data
