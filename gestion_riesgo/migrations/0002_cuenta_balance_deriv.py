from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cuenta",
            name="balance_deriv",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="moneda_deriv",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]


