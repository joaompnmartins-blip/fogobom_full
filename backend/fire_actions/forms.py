import json
from django import forms
from .models import FireAction, BurningPlan


class PrePlanForm(forms.ModelForm):
    class Meta:
        model  = FireAction
        fields = ['name', 'responsible', 'scheduled_date', 'notes', 'parcels']
        labels = {
            'name': 'Nome da Ação', 'responsible': 'Responsável',
            'scheduled_date': 'Data Prevista', 'notes': 'Notas', 'parcels': 'Parcelas',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parcels'].required = False
        self.fields['parcels'].queryset = selectable_parcels(self.instance)
        self.fields['parcels'].error_messages['invalid_choice'] = \
            'Só podem ser usadas parcelas avaliadas como aptas.'


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
            'pre_plan': 'Pré-Plano', 'execution_date': 'Data de Execução', 'operatives': 'Operacionais',
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
                'Pré-plano inválido ou já com Plano de Queima.'

    def save(self, commit=True):
        self.instance.vehicles = json.dumps({
            'VFCI':  self.cleaned_data.get('vfci') or 0,
            'VFCM':  self.cleaned_data.get('vfcm') or 0,
            'Outro': self.cleaned_data.get('other_veh', ''),
        })
        return super().save(commit)
