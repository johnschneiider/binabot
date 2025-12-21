from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0003_operacion_deriv"),
    ]

    operations = [
        migrations.AddField(
            model_name="operacionderiv",
            name="creada_por_bot",
            field=models.BooleanField(default=False),
        ),
    ]


