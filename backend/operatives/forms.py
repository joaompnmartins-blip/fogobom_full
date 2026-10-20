from django import forms
from .models import Operative


class OperativeForm(forms.ModelForm):
    class Meta:
        model  = Operative
        fields = ['name', 'nif', 'email', 'phone', 'certification_level', 'notes']
        labels = {
            'name': 'Nome', 'nif': 'NIF', 'email': 'Email', 'phone': 'Telefone',
            'certification_level': 'Nível de Certificação', 'notes': 'Notas',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional in the UI, as before (model stores empty strings)
        for f in ('email', 'phone', 'certification_level'):
            self.fields[f].required = False
