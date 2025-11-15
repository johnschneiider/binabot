"""
Comando para migrar datos faltantes desde SQLite a PostgreSQL.
Útil cuando la migración inicial no migró todos los datos correctamente.
"""
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from dotenv import load_dotenv


class Command(BaseCommand):
    help = "Migra datos faltantes desde SQLite a PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--modelo",
            type=str,
            help="Migrar solo un modelo específico (ej: core.ActivoPermitido, historial.Operacion)",
        )
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la migración sin preguntar",
        )

    def handle(self, *args, **options):
        # Verificar que estamos usando PostgreSQL
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            raise CommandError(
                "Este comando solo funciona cuando la base de datos actual es PostgreSQL."
            )

        # Cargar variables de entorno
        env_path = Path(settings.BASE_DIR) / ".env"
        if not env_path.exists():
            env_path = Path(settings.BASE_DIR).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("MIGRACIÓN DE DATOS FALTANTES"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        # Buscar backup de SQLite
        sqlite_path = Path(settings.BASE_DIR) / "db.sqlite3"
        if not sqlite_path.exists():
            # Buscar backups
            backups = list(Path(settings.BASE_DIR).glob("db.sqlite3.backup_*"))
            if backups:
                sqlite_path = sorted(backups)[-1]  # Usar el más reciente
                self.stdout.write(
                    self.style.WARNING(
                        f"Usando backup de SQLite: {sqlite_path.name}"
                    )
                )
            else:
                raise CommandError(
                    "No se encontró db.sqlite3 ni backups. No se pueden migrar datos."
                )

        self.stdout.write(f"SQLite fuente: {sqlite_path}")
        self.stdout.write("")

        # Verificar qué hay en PostgreSQL actualmente
        self.stdout.write("DATOS ACTUALES EN POSTGRESQL:")
        self.stdout.write("-" * 80)
        try:
            from core.models import ConfiguracionBot, ActivoPermitido
            from historial.models import Operacion

            config_count = ConfiguracionBot.objects.count()
            activos_count = ActivoPermitido.objects.count()
            operaciones_count = Operacion.objects.count()

            self.stdout.write(f"  Configuraciones: {config_count}")
            self.stdout.write(f"  Activos permitidos: {activos_count}")
            self.stdout.write(f"  Operaciones: {operaciones_count}")
            self.stdout.write("")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error al verificar datos: {e}"))
            return

        # Determinar qué migrar
        modelos_a_migrar = []
        if options["modelo"]:
            modelos_a_migrar = [options["modelo"]]
        else:
            if activos_count == 0:
                modelos_a_migrar.append("core.ActivoPermitido")
            if operaciones_count == 0:
                modelos_a_migrar.append("historial.Operacion")

        if not modelos_a_migrar:
            self.stdout.write(
                self.style.SUCCESS("✓ No hay datos faltantes aparentes.")
            )
            return

        self.stdout.write("MODELOS A MIGRAR:")
        self.stdout.write("-" * 80)
        for modelo in modelos_a_migrar:
            self.stdout.write(f"  - {modelo}")
        self.stdout.write("")

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Esta operación exportará datos desde SQLite e importará a PostgreSQL."
                )
            )
            confirmacion = input("¿Deseas continuar? (sí/no): ")
            if confirmacion.lower() not in ["sí", "si", "yes", "y", "s"]:
                self.stdout.write(self.style.ERROR("Operación cancelada."))
                return

        # Cambiar temporalmente a SQLite para exportar
        original_db = settings.DATABASES["default"].copy()
        settings.DATABASES["default"] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": sqlite_path,
        }
        connection.close()

        import tempfile

        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        temp_file_path = temp_file.name
        temp_file.close()

        try:
            # Exportar desde SQLite
            self.stdout.write("EXPORTANDO DESDE SQLITE...")
            self.stdout.write("-" * 80)

            dump_args = ["dumpdata", "--natural-foreign", "--natural-primary"]
            for modelo in modelos_a_migrar:
                dump_args.append(modelo)

            dump_args.extend(["--output", temp_file_path])
            call_command(*dump_args, verbosity=1)

            # Verificar archivo
            if not Path(temp_file_path).exists():
                raise CommandError("El archivo de exportación no se creó")

            file_size = Path(temp_file_path).stat().st_size
            if file_size == 0:
                raise CommandError("El archivo de exportación está vacío")

            self.stdout.write(
                self.style.SUCCESS(f"✓ Datos exportados ({file_size / 1024:.2f} KB)")
            )

        except Exception as e:
            Path(temp_file_path).unlink(missing_ok=True)
            # Restaurar configuración
            settings.DATABASES["default"] = original_db
            connection.close()
            raise CommandError(f"ERROR al exportar: {e}")

        # Cambiar de vuelta a PostgreSQL
        settings.DATABASES["default"] = original_db
        connection.close()

        # Importar a PostgreSQL
        self.stdout.write("")
        self.stdout.write("IMPORTANDO A POSTGRESQL...")
        self.stdout.write("-" * 80)

        try:
            call_command("loaddata", temp_file_path, verbosity=2)
            self.stdout.write(self.style.SUCCESS("✓ Datos importados"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"✗ Error al importar: {e}")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"El archivo de exportación se guardó en: {temp_file_path}"
                )
            )
            raise CommandError(f"ERROR al importar: {e}")
        finally:
            # Limpiar archivo temporal
            Path(temp_file_path).unlink(missing_ok=True)

        # Verificar resultados
        self.stdout.write("")
        self.stdout.write("VERIFICACIÓN FINAL:")
        self.stdout.write("-" * 80)

        try:
            activos_nuevos = ActivoPermitido.objects.count()
            operaciones_nuevas = Operacion.objects.count()

            self.stdout.write(f"  Activos permitidos: {activos_nuevos}")
            self.stdout.write(f"  Operaciones: {operaciones_nuevas}")

            if activos_nuevos > 0 and operaciones_nuevas > 0:
                self.stdout.write(
                    self.style.SUCCESS("✓ Migración de datos completada")
                )
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️  Algunos datos pueden no haberse migrado")
                )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"⚠️  Error al verificar: {e}")
            )

