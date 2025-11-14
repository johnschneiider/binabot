from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_configuracionbot_ultima_simulacion"),
    ]

    operations = [
        migrations.AddField(
            model_name="activopermitido",
            name="hora_mejor_simulacion",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activopermitido",
            name="ultima_simulacion",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activopermitido",
            name="winrate_simulacion",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=5
            ),
        ),
    ]


