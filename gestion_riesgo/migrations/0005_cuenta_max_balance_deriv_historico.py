from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0004_operacionderiv_creada_por_bot"),
    ]

    operations = [
        migrations.AddField(
            model_name="cuenta",
            name="max_balance_deriv_historico",
            field=models.FloatField(blank=True, null=True),
        ),
    ]


