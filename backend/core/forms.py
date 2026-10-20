from django import forms
from django.contrib import messages

MAX_PHOTO_MB = 15


def form_errors_to_messages(request, form):
    """Show each form error as a flash message, prefixed by the field label.

    Also copies the raw submitted text of invalid text fields back onto
    form.instance, since the templates re-fill inputs from the instance.
    """
    text_fields = (forms.CharField, forms.IntegerField)
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else ''
        for err in errors:
            messages.error(request, f'{label}: {err}' if label else err)
        if isinstance(form.fields.get(field), text_fields) and hasattr(form.instance, field):
            setattr(form.instance, field, form.data.get(field, ''))


def clean_photos(files):
    """Validate uploaded photos; returns (valid_files, error_messages)."""
    field = forms.ImageField()
    valid, errors = [], []
    for f in files:
        if f.size > MAX_PHOTO_MB * 1024 * 1024:
            errors.append(f'"{f.name}" excede {MAX_PHOTO_MB} MB.')
            continue
        try:
            valid.append(field.clean(f))
        except forms.ValidationError:
            errors.append(f'"{f.name}" não é uma imagem válida.')
    return valid, errors
