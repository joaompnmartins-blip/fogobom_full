from django import forms
from .icnf import is_valid_number, normalize_number
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


class ProfileForm(forms.ModelForm):
    """A user's own data. Credential changes go back to 'Por validar'."""
    class Meta:
        model  = Operative
        fields = ['name', 'phone', 'nif', 'credential_type', 'credential_number', 'field_book_number']
        labels = {'name': 'Nome completo', 'phone': 'Telefone', 'nif': 'NIF',
                  'credential_type': 'Tipo de credenciação', 'credential_number': 'N.º de credenciação ICNF',
                  'field_book_number': 'N.º do livro de campo'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = False

    def clean(self):
        data = super().clean()
        if data.get('credential_type') == Operative.CRED_TECNICO:
            number = normalize_number(data.get('credential_number', ''))
            if not is_valid_number(number):
                self.add_error('credential_number', 'Indique o n.º no formato número-ano (ex.: 547-2026).')
            elif (Operative.objects.filter(credential_number=number)
                  .exclude(pk=self.instance.pk).exclude(credential_status=Operative.STATUS_RECUSADA).exists()):
                self.add_error('credential_number', 'Este n.º já está associado a outra pessoa.')
            data['credential_number'] = number
        else:
            data['credential_number'] = ''
        return data
