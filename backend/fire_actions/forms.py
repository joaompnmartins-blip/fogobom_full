import json
from django import forms
from .models import FireAction, BurningPlan


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
    """Burning plan form. `pre_plan` is only editable on creation."""
    num_men   = forms.IntegerField(label='Nº de Homens', required=False, min_value=0)
    vfci      = forms.IntegerField(label='VFCI', required=False, min_value=0)
    vfcm      = forms.IntegerField(label='VFCM', required=False, min_value=0)
    other_veh = forms.CharField(label='Outros veículos', required=False)

    class Meta:
        model  = BurningPlan
        fields = ['pre_plan', 'execution_date', 'num_men', 'operatives', 'problems',
                  'fuel_superficial', 'fuel_manta_f', 'fuel_manta_h',
                  'weather_state', 'wind_speed_beaufort', 'wind_speed_kmh', 'wind_direction',
                  'fire_conduct', 'fire_conduct_other', 'burn_effects', 'burn_efficiency', 'notes']
        labels = {
            'pre_plan': 'Ação', 'execution_date': 'Data de Execução', 'operatives': 'Operacionais',
            'problems': 'Problemas identificados', 'fuel_superficial': 'Humidade superficial',
            'fuel_manta_f': 'Humidade manta morta F', 'fuel_manta_h': 'Humidade manta morta H',
            'weather_state': 'Estado do tempo', 'wind_speed_beaufort': 'Vel. vento (Beaufort)',
            'wind_speed_kmh': 'Vel. vento (km/h)', 'wind_direction': 'Direção do vento',
            'fire_conduct': 'Condução do fogo', 'fire_conduct_other': 'Descrição (se "Outro")',
            'burn_effects': 'Efeitos da queima', 'burn_efficiency': 'Eficácia da ação',
            'notes': 'Notas adicionais',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields['pre_plan']
        else:
            self.fields['pre_plan'].queryset = FireAction.objects.filter(burningplan__isnull=True)
            self.fields['pre_plan'].error_messages['invalid_choice'] = \
                'Ação inválida ou já com Plano de Queima.'

    def save(self, commit=True):
        self.instance.vehicles = json.dumps({
            'VFCI':  self.cleaned_data.get('vfci') or 0,
            'VFCM':  self.cleaned_data.get('vfcm') or 0,
            'Outro': self.cleaned_data.get('other_veh', ''),
        })
        return super().save(commit)
