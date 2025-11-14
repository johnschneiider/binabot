from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simulacion", "0002_alter_resultadohorariosimulacion_managers"),
    ]

    operations = [
        migrations.AddField(
            model_name="resultadohorariosimulacion",
            name="activo",
            field=models.CharField(default="", max_length=80),
        ),
        migrations.AlterUniqueTogether(
            name="resultadohorariosimulacion",
            unique_together={("activo", "hora_inicio", "fecha_calculo")},
        ),
    ]


