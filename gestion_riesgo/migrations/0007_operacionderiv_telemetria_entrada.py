from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0006_cuenta_senal"),
    ]

    operations = [
        migrations.AddField(
            model_name="operacionderiv",
            name="senal_valor",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="operacionderiv",
            name="umbral_usado",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="operacionderiv",
            name="pesos_usados",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="operacionderiv",
            name="senal_top_contribuciones",
            field=models.JSONField(blank=True, null=True),
        ),
    ]


