"""
Comando seguro para migrar de SQLite a PostgreSQL.
Realiza backup, verifica conexión, migra datos y valida integridad.
"""
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from dotenv import load_dotenv


class Command(BaseCommand):
    help = "Migra la base de datos de SQLite a PostgreSQL de forma segura."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la migración sin preguntar",
        )
        parser.add_argument(
            "--sin-backup",
            action="store_true",
            help="No crear backup de SQLite (no recomendado)",
        )

    def handle(self, *args, **options):
        # Verificar que estamos usando SQLite actualmente
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError(
                "Este comando solo funciona cuando la base de datos actual es SQLite."
            )

        # Cargar variables de entorno desde .env
        env_path = Path(settings.BASE_DIR) / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            # Intentar cargar desde el directorio padre (donde suele estar .env)
            env_path = Path(settings.BASE_DIR).parent / ".env"
            if env_path.exists():
                load_dotenv(env_path)

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("MIGRACIÓN DE SQLITE A POSTGRESQL"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        # 1. Verificar variables de entorno de PostgreSQL
        self.stdout.write("PASO 1: Verificando configuración de PostgreSQL...")
        self.stdout.write("-" * 80)
        
        # Leer variables de entorno (ahora cargadas desde .env)
        db_name = os.getenv("DB_NAME", "binabot")
        db_user = os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DB_PASSWORD", "")
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        
        if not db_password:
            raise CommandError(
                "ERROR: DB_PASSWORD no está configurado en el archivo .env\n"
                "Agrega DB_PASSWORD=tu_password en tu archivo .env"
            )
        
        db_config = {
            "NAME": db_name,
            "USER": db_user,
            "PASSWORD": db_password,
            "HOST": db_host,
            "PORT": db_port,
        }
        
        self.stdout.write(f"Base de datos: {db_config['NAME']}")
        self.stdout.write(f"Host: {db_config['HOST']}")
        self.stdout.write(f"Puerto: {db_config['PORT']}")
        self.stdout.write(f"Usuario: {db_config['USER']}")
        self.stdout.write("")

        # 2. Verificar conexión a PostgreSQL
        self.stdout.write("PASO 2: Verificando conexión a PostgreSQL...")
        self.stdout.write("-" * 80)
        
        try:
            import psycopg2
            conn = psycopg2.connect(
                dbname=db_config["NAME"],
                user=db_config["USER"],
                password=db_config["PASSWORD"],
                host=db_config["HOST"],
                port=db_config["PORT"],
                connect_timeout=10,
            )
            conn.close()
            self.stdout.write(self.style.SUCCESS("✓ Conexión a PostgreSQL exitosa"))
        except ImportError:
            raise CommandError(
                "ERROR: psycopg2-binary no está instalado. Ejecuta: pip install psycopg2-binary"
            )
        except Exception as e:
            raise CommandError(f"ERROR: No se pudo conectar a PostgreSQL: {e}")

        self.stdout.write("")

        # 3. Crear backup de SQLite
        if not options["sin_backup"]:
            self.stdout.write("PASO 3: Creando backup de SQLite...")
            self.stdout.write("-" * 80)
            
            sqlite_path = Path(settings.BASE_DIR) / "db.sqlite3"
            if not sqlite_path.exists():
                raise CommandError(f"ERROR: No se encontró {sqlite_path}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = sqlite_path.parent / f"db.sqlite3.backup_{timestamp}"
            
            try:
                shutil.copy2(sqlite_path, backup_path)
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Backup creado: {backup_path}")
                )
            except Exception as e:
                raise CommandError(f"ERROR al crear backup: {e}")
        else:
            self.stdout.write(
                self.style.WARNING("⚠️  Saltando creación de backup (--sin-backup)")
            )
            backup_path = None

        self.stdout.write("")

        # 4. Confirmación
        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Esta operación:\n"
                    "   1. Creará todas las tablas en PostgreSQL\n"
                    "   2. Migrará todos los datos desde SQLite\n"
                    "   3. NO eliminará el archivo SQLite (se mantiene como backup)\n"
                    "   4. Cambiará la configuración para usar PostgreSQL"
                )
            )
            self.stdout.write("")
            confirmacion = input("¿Deseas continuar? (sí/no): ")
            if confirmacion.lower() not in ["sí", "si", "yes", "y", "s"]:
                self.stdout.write(self.style.ERROR("Migración cancelada."))
                return

        self.stdout.write("")

        # 5. Exportar datos de SQLite
        self.stdout.write("PASO 4: Exportando datos de SQLite...")
        self.stdout.write("-" * 80)
        
        import tempfile
        import json
        
        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        temp_file_path = temp_file.name
        temp_file.close()

        try:
            # Leer datos de SQLite (aún estamos usando SQLite)
            self.stdout.write("  - Exportando datos...")
            self.stdout.write("    (Esto puede tardar varios minutos si hay muchos datos)")
            
            # Verificar tamaño de la BD antes de exportar
            sqlite_path = Path(settings.BASE_DIR) / "db.sqlite3"
            if sqlite_path.exists():
                size_mb = sqlite_path.stat().st_size / (1024 * 1024)
                self.stdout.write(f"    Tamaño de SQLite: {size_mb:.2f} MB")
            
            # Excluir Ticks si hay muchos (pueden causar problemas)
            # Los Ticks se pueden regenerar después
            from historial.models import Tick
            tick_count = Tick.objects.count()
            if tick_count > 100000:
                self.stdout.write(
                    self.style.WARNING(
                        f"    ⚠️  Detectados {tick_count:,} Ticks. "
                        "Se excluirán de la migración (se pueden regenerar después)."
                    )
                )
                exclude_ticks = "--exclude=historial.Tick"
            else:
                exclude_ticks = ""
            
            # Construir comando dumpdata
            dump_args = [
                "dumpdata",
                "--natural-foreign",
                "--natural-primary",
                "--exclude=contenttypes",
                "--exclude=auth.Permission",
            ]
            if exclude_ticks:
                dump_args.append("--exclude=historial.Tick")
            
            dump_args.extend(["--output", temp_file_path])
            
            call_command(*dump_args, verbosity=1)
            
            # Verificar que el archivo se creó y tiene contenido
            if not Path(temp_file_path).exists():
                raise CommandError("ERROR: El archivo de exportación no se creó")
            
            file_size = Path(temp_file_path).stat().st_size
            if file_size == 0:
                raise CommandError("ERROR: El archivo de exportación está vacío")
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Datos exportados ({file_size / (1024 * 1024):.2f} MB)"
                )
            )
            
        except KeyboardInterrupt:
            Path(temp_file_path).unlink(missing_ok=True)
            raise CommandError("Migración cancelada por el usuario")
        except Exception as e:
            Path(temp_file_path).unlink(missing_ok=True)
            raise CommandError(f"ERROR al exportar datos: {e}")

        self.stdout.write("")

        # 6. Cambiar a PostgreSQL y crear esquema
        self.stdout.write("PASO 5: Configurando PostgreSQL...")
        self.stdout.write("-" * 80)
        
        # Actualizar settings para usar PostgreSQL
        settings.DATABASES["default"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_config["NAME"],
            "USER": db_config["USER"],
            "PASSWORD": db_config["PASSWORD"],
            "HOST": db_config["HOST"],
            "PORT": db_config["PORT"],
            "OPTIONS": db_config.get("OPTIONS", {}),
            "CONN_MAX_AGE": db_config.get("CONN_MAX_AGE", 600),
        }
        
        # Cerrar conexión anterior
        connection.close()

        # 7. Crear tablas en PostgreSQL
        self.stdout.write("PASO 6: Creando esquema en PostgreSQL...")
        self.stdout.write("-" * 80)
        
        try:
            call_command("migrate", verbosity=1, interactive=False)
            self.stdout.write(self.style.SUCCESS("✓ Esquema creado en PostgreSQL"))
        except Exception as e:
            Path(temp_file_path).unlink(missing_ok=True)
            raise CommandError(f"ERROR al crear esquema: {e}")

        self.stdout.write("")

        # 8. Importar datos a PostgreSQL
        self.stdout.write("PASO 7: Importando datos a PostgreSQL...")
        self.stdout.write("-" * 80)
        
        try:
            # Validar que el JSON es válido antes de importar
            self.stdout.write("  - Validando formato JSON...")
            import json
            with open(temp_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.stdout.write(f"    ✓ JSON válido ({len(data)} objetos)")
            
            # Importar con más verbosidad para ver errores
            self.stdout.write("  - Importando datos...")
            call_command("loaddata", temp_file_path, verbosity=2)
            self.stdout.write(self.style.SUCCESS("  ✓ Datos importados"))
        except json.JSONDecodeError as e:
            Path(temp_file_path).unlink(missing_ok=True)
            raise CommandError(f"ERROR: El archivo JSON no es válido: {e}")
        except Exception as e:
            # No eliminar el archivo temporal si hay error, para debugging
            error_msg = str(e)
            self.stdout.write(
                self.style.ERROR(f"  ✗ Error al importar: {error_msg}")
            )
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"El archivo de exportación se guardó en: {temp_file_path}\n"
                    "Puedes revisarlo para identificar el problema."
                )
            )
            raise CommandError(f"ERROR al importar datos: {e}")
        finally:
            # Solo limpiar si todo fue exitoso
            # Si hay error, dejamos el archivo para debugging
            pass

        self.stdout.write("")

        # 9. Verificar integridad
        self.stdout.write("PASO 8: Verificando integridad de datos...")
        self.stdout.write("-" * 80)
        
        try:
            from core.models import ConfiguracionBot, ActivoPermitido
            from historial.models import Operacion, Tick
            
            config_count = ConfiguracionBot.objects.count()
            activos_count = ActivoPermitido.objects.count()
            activos_habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
            operaciones_count = Operacion.objects.count()
            operaciones_reales = Operacion.objetos.reales().exclude(
                resultado=Operacion.Resultado.PENDIENTE
            ).count()
            ticks_count = Tick.objects.count()
            
            self.stdout.write(f"  Configuraciones: {config_count}")
            self.stdout.write(f"  Activos permitidos: {activos_count} ({activos_habilitados} habilitados)")
            self.stdout.write(f"  Operaciones: {operaciones_count} ({operaciones_reales} reales finalizadas)")
            self.stdout.write(f"  Ticks: {ticks_count}")
            
            if config_count == 0:
                self.stdout.write(
                    self.style.WARNING("  ⚠️  No se encontraron configuraciones")
                )
            elif activos_count == 0:
                self.stdout.write(
                    self.style.WARNING("  ⚠️  No se encontraron activos permitidos")
                )
                self.stdout.write(
                    self.style.WARNING("    El servicio de ticks fallará sin activos habilitados")
                )
            else:
                self.stdout.write(self.style.SUCCESS("  ✓ Datos verificados"))
                
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"  ⚠️  Error al verificar: {e}")
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("MIGRACIÓN COMPLETADA"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")
        self.stdout.write("PRÓXIMOS PASOS:")
        self.stdout.write("-" * 80)
        self.stdout.write("1. Asegúrate de tener DB_ENGINE=postgresql en tu archivo .env")
        self.stdout.write("2. Reinicia todos los servicios:")
        self.stdout.write("   systemctl restart binabot-loop.service")
        self.stdout.write("   systemctl restart binabot-ticks.service")
        self.stdout.write("   systemctl restart binabot.service")
        self.stdout.write("3. Verifica que todo funciona correctamente")
        if backup_path:
            self.stdout.write(f"4. El backup de SQLite está en: {backup_path}")
            self.stdout.write("   (Puedes eliminarlo después de verificar que todo funciona)")

