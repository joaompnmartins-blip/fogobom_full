from django.db import migrations


def mark_existing_apta(apps, schema_editor):
    """Parcels created before the evaluation workflow were already in use: mark them as apta."""
    FireParcel = apps.get_model('parcelas', 'FireParcel')
    FireParcel.objects.all().update(status='apta')


class Migration(migrations.Migration):

    dependencies = [
        ('parcelas', '0004_parcel_proposal_evaluation'),
    ]

    operations = [
        migrations.RunPython(mark_existing_apta, migrations.RunPython.noop),
    ]
