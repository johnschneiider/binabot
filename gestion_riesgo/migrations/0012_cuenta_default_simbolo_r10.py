from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0011_operacionderiv_spot_prices"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cuenta",
            name="simbolo",
            field=models.CharField(default="R_10", max_length=32),
        ),
    ]

