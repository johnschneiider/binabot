from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_riesgo", "0002_cuenta_balance_deriv"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperacionDeriv",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("simbolo", models.CharField(max_length=32)),
                ("contract_id", models.BigIntegerField(unique=True)),
                ("transaction_id", models.BigIntegerField(blank=True, null=True)),
                ("contract_type", models.CharField(blank=True, default="", max_length=16)),
                ("longcode", models.TextField(blank=True, default="")),
                ("shortcode", models.CharField(blank=True, default="", max_length=128)),
                ("estado", models.CharField(choices=[("ABIERTA", "ABIERTA"), ("CERRADA", "CERRADA")], default="ABIERTA", max_length=16)),
                ("moneda", models.CharField(blank=True, default="", max_length=16)),
                ("buy_price", models.FloatField(blank=True, null=True)),
                ("sell_price", models.FloatField(blank=True, null=True)),
                ("payout", models.FloatField(blank=True, null=True)),
                ("profit", models.FloatField(blank=True, null=True)),
                ("opened_epoch", models.BigIntegerField(blank=True, null=True)),
                ("closed_epoch", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("cuenta", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operaciones_deriv", to="gestion_riesgo.cuenta")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["simbolo", "-created_at"], name="gestion_rie_simbolo_f86a5c_idx"),
                    models.Index(fields=["estado", "-created_at"], name="gestion_rie_estado_6c0a7a_idx"),
                    models.Index(fields=["-updated_at"], name="gestion_rie_updated__2b2a8c_idx"),
                ],
            },
        ),
    ]


