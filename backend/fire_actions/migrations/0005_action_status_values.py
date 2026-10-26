from django.db import migrations

OLD_TO_NEW = {'Pre-Plano': 'prevista', 'Executada': 'realizada'}


def forwards(apps, schema_editor):
    FireAction = apps.get_model('fire_actions', 'FireAction')
    for old, new in OLD_TO_NEW.items():
        FireAction.objects.filter(status=old).update(status=new)


def backwards(apps, schema_editor):
    FireAction = apps.get_model('fire_actions', 'FireAction')
    FireAction.objects.filter(status='realizada').update(status='Executada')
    FireAction.objects.exclude(status='Executada').update(status='Pre-Plano')


class Migration(migrations.Migration):
    """Pre-plans become burning actions: map the old status values. Existing ones are queimadas (field default)."""

    dependencies = [
        ('fire_actions', '0004_action_announcement'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
