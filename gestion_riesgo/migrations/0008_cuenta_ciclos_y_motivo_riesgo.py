from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0007_operacionderiv_telemetria_entrada"),
    ]

    operations = [
        migrations.AddField(
            model_name="cuenta",
            name="riesgo_motivo",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="ciclo_balance_inicio",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="ciclo_inicio_epoch",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="ciclo_pausa_hasta_epoch",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenta",
            name="ciclo_ultimo_evento",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]


