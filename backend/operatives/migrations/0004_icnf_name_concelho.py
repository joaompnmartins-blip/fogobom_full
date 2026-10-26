from django.db import migrations, models


class Migration(migrations.Migration):
    """Split the ICNF list line into name and concelho (re-import the list to fill them)."""

    dependencies = [
        ('operatives', '0003_credentials'),
    ]

    operations = [
        migrations.RenameField(model_name='icnftechnician', old_name='text', new_name='name'),
        migrations.AlterField(
            model_name='icnftechnician',
            name='name',
            field=models.CharField(max_length=150, verbose_name='nome'),
        ),
        migrations.AddField(
            model_name='icnftechnician',
            name='concelho',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='concelho de residência'),
        ),
    ]
