import json
from django import forms
from parcelas.models import FireParcel
from .models import (BurningPlan, CostLine, ExecutionMember, FireAction, ParcelExecution,
                     SafetyStrip, WeatherReading)


class UserChoiceField(forms.ModelChoiceField):
    """Users shown by their profile name and ICNF credential number, when known."""
    def label_from_instance(self, user):
        op = getattr(user, 'operative', None)
        name = op.name if op and op.name else (user.get_full_name() or user.get_username())
        return f'{name} (técnico n.º {op.credential_number})' if op and op.is_tecnico else name


class PrePlanForm(forms.ModelForm):
    """Burning action: announcement data, legal framework and parcels."""
    objectives = forms.MultipleChoiceField(label='Objetivos', choices=FireAction.OBJECTIVES, required=False,
                                           widget=forms.CheckboxSelectMultiple)
    meeting_lat = forms.FloatField(required=False, widget=forms.HiddenInput)
    meeting_lng = forms.FloatField(required=False, widget=forms.HiddenInput)

    class Meta:
        model  = FireAction
        fields = ['name', 'action_type', 'training', 'purpose', 'objectives', 'responsible_user',
                  'scheduled_date', 'alt_date_1', 'alt_date_2', 'start_time', 'meeting_notes', 'requirements',
                  'slots', 'probability_manual', 'legal_mode', 'legal_reference', 'legal_date', 'legal_document',
                  'accompaniment', 'pfc', 'pfc_reference', 'notes', 'parcels']
        labels = {'name': 'Nome da ação', 'scheduled_date': 'Data prevista', 'notes': 'Notas', 'parcels': 'Parcelas'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        self.fields['responsible_user'] = UserChoiceField(
            label='Técnico responsável', required=False,
            queryset=get_user_model().objects.filter(is_active=True).select_related('operative')
                     .order_by('operative__name', 'username'))
        self.fields['parcels'].required = False
        self.fields['parcels'].queryset = selectable_parcels(self.instance)
        self.fields['parcels'].error_messages['invalid_choice'] = \
            'Só podem ser usadas parcelas avaliadas como aptas.'
        self.fields['action_type'].required = False
        from pfc.models import PFC
        in_force = [p.pk for p in PFC.objects.all() if p.effective_approval_date and p.status != PFC.STATUS_SUSPENSO
                    and not p.is_expired]
        if self.instance.pfc_id:
            in_force.append(self.instance.pfc_id)
        self.fields['pfc'].queryset = PFC.objects.filter(pk__in=in_force)
        self.fields['pfc'].label = 'PFC aprovado'
        if self.instance.pk:
            self.initial['objectives'] = self.instance.objectives_list
            if self.instance.meeting_point:
                self.initial['meeting_lat'] = self.instance.meeting_point.y
                self.initial['meeting_lng'] = self.instance.meeting_point.x

    def clean_objectives(self):
        return ','.join(self.cleaned_data.get('objectives') or [])

    def clean_action_type(self):
        return self.cleaned_data.get('action_type') or FireAction.TYPE_QUEIMADA

    def clean(self):
        data = super().clean()
        for f in ('alt_date_1', 'alt_date_2'):
            if data.get(f) and data.get(f) == data.get('scheduled_date'):
                self.add_error(f, 'Tem de ser diferente da data prevista.')
        responsible = data.get('responsible_user')
        tecnico = bool(responsible and getattr(getattr(responsible, 'operative', None), 'is_tecnico', False))
        if data.get('action_type') == FireAction.TYPE_FOGO_CONTROLADO and responsible and not tecnico:
            self.add_error('responsible_user',
                           'O fogo controlado é executado sob responsabilidade de um técnico credenciado (validado).')
        if data.get('legal_mode') == 'comunicacao_previa' and responsible and not tecnico:
            self.add_error('legal_mode',
                           'A comunicação prévia só se aplica a queimadas com técnico credenciado; '
                           'caso contrário é necessária autorização do município.')
        pfc, d = data.get('pfc'), data.get('scheduled_date')
        if data.get('action_type') == FireAction.TYPE_FOGO_CONTROLADO and pfc:
            if d and not pfc.in_force_on(d):
                self.add_error('pfc', f'O PFC {pfc.number} não está em vigor nessa data.')
            outside = [p.name for p in data.get('parcels') or []
                       if not pfc.plan_parcels.filter(parcel=p).exists()]
            if outside:
                self.add_error('parcels', 'Parcelas que não fazem parte do PFC escolhido: ' + ', '.join(outside))
        lat, lng = data.get('meeting_lat'), data.get('meeting_lng')
        if (lat is None) != (lng is None):
            self.add_error(None, 'Ponto de encontro incompleto.')
        return data

    def save(self, commit=True):
        from django.contrib.gis.geos import Point
        lat, lng = self.cleaned_data.get('meeting_lat'), self.cleaned_data.get('meeting_lng')
        self.instance.meeting_point = Point(lng, lat, srid=4326) if lat is not None and lng is not None else None
        if self.instance.action_type != FireAction.TYPE_QUEIMADA:
            self.instance.purpose = ''
        return super().save(commit)


def selectable_parcels(action=None):
    """Parcels usable in an action: evaluated as apta (with or without conditions), plus any already linked."""
    from django.db.models import Q
    from parcelas.models import FireParcel
    q = Q(status__in=FireParcel.AVAILABLE_STATUSES)
    if action is not None and action.pk:
        q |= Q(pk__in=action.parcels.values('pk'))
    return FireParcel.objects.filter(q)


class BurningPlanForm(forms.ModelForm):
    """Header of the POQ-Execução of an action. `pre_plan` is only chosen on creation."""
    class Meta:
        model  = BurningPlan
        fields = ['pre_plan', 'execution_date', 'notes', 'incident', 'incident_date', 'incident_circumstances',
                  'incident_entities', 'incident_teams', 'incident_commander', 'incident_strategy',
                  'incident_area_ha', 'incident_damages']
        labels = {'pre_plan': 'Ação', 'execution_date': 'Data (1.º dia de execução)', 'notes': 'Observações gerais'}
        widgets = {'execution_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'incident_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   **{f: forms.Textarea(attrs={'rows': 2}) for f in (
                       'notes', 'incident_circumstances', 'incident_entities', 'incident_teams',
                       'incident_strategy', 'incident_damages')}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields['pre_plan']
        else:
            self.fields['pre_plan'].queryset = FireAction.objects.filter(burningplan__isnull=True) \
                .exclude(status=FireAction.STATUS_CANCELADA)
            self.fields['pre_plan'].error_messages['invalid_choice'] = \
                'Ação inválida ou já com execução registada.'

    def clean(self):
        data = super().clean()
        if data.get('incident') and not (data.get('incident_circumstances') or '').strip():
            self.add_error('incident_circumstances', 'Descreva as circunstâncias do incidente.')
        return data


TIME = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


class ParcelExecutionForm(forms.ModelForm):
    problems = forms.MultipleChoiceField(label='Problemas operacionais', choices=ParcelExecution.PROBLEMS,
                                         required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = ParcelExecution
        exclude = ['plan', 'parcel', 'date', 'created_at']
        widgets = {'start_time': TIME, 'end_time': TIME,
                   **{f: forms.Textarea(attrs={'rows': 2}) for f in (
                       'ignition_techniques', 'operation_notes', 'problems_description', 'rating_why')}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['problems'] = self.instance.problems_list

    def clean_problems(self):
        return ','.join(self.cleaned_data.get('problems') or [])

    def clean(self):
        data = super().clean()
        s, e = data.get('start_time'), data.get('end_time')
        if s and e and e <= s:
            self.add_error('end_time', 'O fim tem de ser depois do início.')
        for f in ('eff_veg_area_pct', 'eff_crowns_pct', 'eff_litter_area_pct', 'eff_litter_reduction_pct'):
            v = data.get(f)
            if v is not None and not 0 <= v <= 100:
                self.add_error(f, 'Valor entre 0 e 100.')
        return data


class NewParcelExecutionForm(forms.Form):
    parcel = forms.ModelChoiceField(label='Parcela', queryset=FireParcel.objects.none())
    date = forms.DateField(label='Data', widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan
        self.fields['parcel'].queryset = plan.pre_plan.parcels.all() if plan else FireParcel.objects.none()

    def clean(self):
        data = super().clean()
        if self.plan and data.get('parcel') and data.get('date') and \
                self.plan.executions.filter(parcel=data['parcel'], date=data['date']).exists():
            raise forms.ValidationError('Já existe a execução desta parcela nesta data.')
        return data


MemberFormSet = forms.inlineformset_factory(ParcelExecution, ExecutionMember, fields=['operative', 'function'],
                                           extra=2, can_delete=True)
ReadingFormSet = forms.inlineformset_factory(
    ParcelExecution, WeatherReading,
    fields=['time', 'temp', 'rh', 'weather', 'wind_bft', 'wind_kmh', 'wind_dir', 'conduct', 'conduct_other',
            'flame_length_m', 'flame_angle', 'spread_m_min'],
    widgets={'time': TIME}, extra=2, can_delete=True)
StripFormSet = forms.inlineformset_factory(ParcelExecution, SafetyStrip,
                                          fields=['side', 'means', 'width_m', 'time_spent'], extra=0, can_delete=False)
CostFormSet = forms.inlineformset_factory(ParcelExecution, CostLine,
                                         fields=['category', 'description', 'qty_burn', 'qty_extinction', 'unit_price'],
                                         extra=2, can_delete=True)
