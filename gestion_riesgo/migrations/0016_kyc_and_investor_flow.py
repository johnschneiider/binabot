from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("gestion_riesgo", "0015_add_inversionista_models"),
    ]

    operations = [
        # ---- KYC: agregar campos a Inversionista ----
        migrations.AddField(
            model_name="inversionista",
            name="fecha_nacimiento",
            field=models.DateField(blank=True, null=True, verbose_name="Fecha de nacimiento"),
        ),
        migrations.AddField(
            model_name="inversionista",
            name="nacionalidad",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Nacionalidad"),
        ),
        migrations.AddField(
            model_name="inversionista",
            name="genero",
            field=models.CharField(
                blank=True,
                choices=[("M", "Masculino"), ("F", "Femenino"), ("O", "Otro"), ("N", "Prefiero no decir")],
                default="N",
                max_length=1,
                verbose_name="Género",
            ),
        ),
        migrations.AddField(
            model_name="inversionista",
            name="documento_identidad",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Documento de identidad"),
        ),
        migrations.AddField(
            model_name="inversionista",
            name="capital_objetivo",
            field=models.FloatField(
                blank=True,
                default=0.0,
                verbose_name="Capital objetivo a invertir",
            ),
        ),
        migrations.AddField(
            model_name="inversionista",
            name="como_se_entero",
            field=models.CharField(
                blank=True,
                default="",
                max_length=128,
                verbose_name="¿Cómo se enteró de nosotros?",
            ),
        ),
        # ---- Limpiar tokens Deriv (ya no los necesitamos) ----
        migrations.RemoveField(model_name="inversionista", name="deriv_api_token"),
        migrations.RemoveField(model_name="inversionista", name="deriv_account_id"),
        migrations.RemoveField(model_name="inversionista", name="deriv_app_id"),

        # ---- Renombrar ganancia_diaria → ganancia_mes (track mensual) ----
        migrations.RenameField(
            model_name="inversionista",
            old_name="ganancia_diaria",
            new_name="ganancia_mes",
        ),

        # ---- Nuevo modelo: Deposito ----
        migrations.CreateModel(
            name="Deposito",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "inversionista",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="depositos",
                        to="gestion_riesgo.inversionista",
                    ),
                ),
                ("monto", models.FloatField(default=0.0, verbose_name="Monto depositado (USD)")),
                (
                    "referencia",
                    models.CharField(blank=True, default="", max_length=64, verbose_name="Referencia Bold"),
                ),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("PENDIENTE", "Pendiente"),
                            ("CONFIRMADO", "Confirmado"),
                            ("RECHAZADO", "Rechazado"),
                            ("CANCELADO", "Cancelado"),
                        ],
                        default="PENDIENTE",
                        max_length=16,
                        verbose_name="Estado",
                    ),
                ),
                (
                    "metodo",
                    models.CharField(
                        blank=True, default="BOLD", max_length=32, verbose_name="Método de pago"
                    ),
                ),
                ("notas", models.TextField(blank=True, default="", verbose_name="Notas internas")),
                ("fecha_creado", models.DateTimeField(auto_now_add=True)),
                ("fecha_confirmado", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Depósito",
                "verbose_name_plural": "Depósitos",
                "indexes": [
                    models.Index(fields=["inversionista", "-fecha_creado"], name="deposito_inv_fecha_idx"),
                    models.Index(fields=["referencia"], name="deposito_ref_idx"),
                    models.Index(fields=["estado"], name="deposito_estado_idx"),
                ],
                "ordering": ["-fecha_creado"],
            },
        ),

        # ---- Nuevo modelo: Retiro ----
        migrations.CreateModel(
            name="Retiro",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "inversionista",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="retiros",
                        to="gestion_riesgo.inversionista",
                    ),
                ),
                ("monto", models.FloatField(default=0.0, verbose_name="Monto a retirar (USD)")),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("SOLICITADO", "Solicitado"),
                            ("EN_PROCESO", "En proceso"),
                            ("COMPLETADO", "Completado"),
                            ("RECHAZADO", "Rechazado"),
                        ],
                        default="SOLICITADO",
                        max_length=16,
                        verbose_name="Estado",
                    ),
                ),
                (
                    "destino",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=256,
                        verbose_name="Datos destino (banco/crypto)",
                    ),
                ),
                ("notas", models.TextField(blank=True, default="")),
                ("notas_admin", models.TextField(blank=True, default="", verbose_name="Notas admin")),
                ("fecha_solicitud", models.DateTimeField(auto_now_add=True)),
                ("fecha_proceso", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Retiro",
                "verbose_name_plural": "Retiros",
                "indexes": [
                    models.Index(fields=["inversionista", "-fecha_solicitud"], name="retiro_inv_fecha_idx"),
                    models.Index(fields=["estado"], name="retiro_estado_idx"),
                ],
                "ordering": ["-fecha_solicitud"],
            },
        ),

        # ---- Nuevo modelo: RendimientoFondo (rendimiento mensual real del fondo) ----
        migrations.CreateModel(
            name="RendimientoFondo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("anno", models.IntegerField(verbose_name="Año")),
                ("mes", models.IntegerField(verbose_name="Mes (1-12)")),
                ("balance_inicio", models.FloatField(default=0.0)),
                ("balance_fin", models.FloatField(default=0.0)),
                ("ganancia", models.FloatField(default=0.0, verbose_name="Ganancia/Pérdida del mes")),
                ("rendimiento_pct", models.FloatField(default=0.0, verbose_name="Rendimiento % del mes")),
                ("trades_count", models.IntegerField(default=0)),
                ("trades_wins", models.IntegerField(default=0)),
                ("trades_losses", models.IntegerField(default=0)),
                ("winrate", models.FloatField(default=0.0)),
                ("observaciones", models.TextField(blank=True, default="")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Rendimiento del Fondo",
                "verbose_name_plural": "Rendimientos del Fondo",
                "indexes": [
                    models.Index(fields=["-anno", "-mes"], name="rendf_anno_mes_idx"),
                ],
                "unique_together": {("anno", "mes")},
                "ordering": ["-anno", "-mes"],
            },
        ),
    ]
