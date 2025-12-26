from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0008_cuenta_ciclos_y_motivo_riesgo"),
    ]

    operations = [
        migrations.CreateModel(
            name="BalanceDerivSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.FloatField()),
                ("moneda", models.CharField(blank=True, default="", max_length=16)),
                ("epoch", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "cuenta",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="balance_snapshots",
                        to="gestion_riesgo.cuenta",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["cuenta", "-created_at"], name="gestion_rie_cuenta__6f6a9f_idx"),
                    models.Index(fields=["-created_at"], name="gestion_rie_created_7d1f9a_idx"),
                ],
            },
        ),
    ]


