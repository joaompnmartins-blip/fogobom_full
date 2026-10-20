from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('parcelas', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='fireparcel',
            name='last_burned_date',
        ),
    ]
