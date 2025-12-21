from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0005_cuenta_max_balance_deriv_historico"),
    ]

    operations = [
        migrations.AddField(
            model_name="cuenta",
            name="senal_decision",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="senal_top_contribuciones",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="senal_valor",
            field=models.FloatField(blank=True, null=True),
        ),
    ]


