from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Cuenta",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("simbolo", models.CharField(default="R_100", max_length=32)),
                ("capital_inicial", models.FloatField(default=100.0)),
                ("capital_actual", models.FloatField(default=100.0)),
                ("max_capital_historico", models.FloatField(default=100.0)),
                ("bloqueado", models.BooleanField(default=False)),
                ("ultimo_tick_epoch", models.BigIntegerField(default=0)),
                ("ultimo_precio", models.FloatField(default=0.0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Operacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("simbolo", models.CharField(max_length=32)),
                ("estado", models.CharField(choices=[("ABIERTA", "ABIERTA"), ("CERRADA", "CERRADA")], default="ABIERTA", max_length=16)),
                ("direccion", models.CharField(choices=[("LARGO", "LARGO"), ("CORTO", "CORTO")], max_length=16)),
                ("precio_entrada", models.FloatField()),
                ("precio_salida", models.FloatField(blank=True, null=True)),
                ("tamanio", models.FloatField()),
                ("stop_distancia", models.FloatField()),
                ("pnl_realizado", models.FloatField(blank=True, null=True)),
                ("motivo_cierre", models.CharField(blank=True, default="", max_length=64)),
                ("opened_epoch", models.BigIntegerField(default=0)),
                ("closed_epoch", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("cuenta", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operaciones", to="gestion_riesgo.cuenta")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["simbolo", "-created_at"], name="gestion_rie_simbolo_5d0c29_idx"),
                    models.Index(fields=["estado", "-created_at"], name="gestion_rie_estado_ee4a34_idx"),
                ],
            },
        ),
    ]


