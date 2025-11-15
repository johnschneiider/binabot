"""
Comando para habilitar WAL (Write-Ahead Logging) en SQLite.
WAL mejora significativamente la concurrencia y reduce bloqueos.
"""
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Habilita WAL mode en la base de datos SQLite para mejorar la concurrencia."

    def handle(self, *args, **options):
        db_path = Path(settings.DATABASES["default"]["NAME"])
        
        if not db_path.exists():
            self.stdout.write(
                self.style.ERROR(f"La base de datos no existe en: {db_path}")
            )
            return

        try:
            # Conectar y habilitar WAL
            conn = sqlite3.connect(str(db_path), timeout=30.0)
            cursor = conn.cursor()
            
            # Verificar modo actual
            cursor.execute("PRAGMA journal_mode;")
            modo_actual = cursor.fetchone()[0]
            
            self.stdout.write(f"Modo actual de journal: {modo_actual}")
            
            if modo_actual.upper() == "WAL":
                self.stdout.write(
                    self.style.SUCCESS("✓ WAL ya está habilitado.")
                )
            else:
                # Habilitar WAL
                cursor.execute("PRAGMA journal_mode=WAL;")
                nuevo_modo = cursor.fetchone()[0]
                
                if nuevo_modo.upper() == "WAL":
                    self.stdout.write(
                        self.style.SUCCESS("✓ WAL habilitado exitosamente.")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  No se pudo habilitar WAL. Modo actual: {nuevo_modo}"
                        )
                    )
            
            # Configuraciones adicionales para mejorar concurrencia
            cursor.execute("PRAGMA busy_timeout=30000;")  # 30 segundos timeout
            cursor.execute("PRAGMA synchronous=NORMAL;")  # Balance entre seguridad y velocidad
            cursor.execute("PRAGMA wal_autocheckpoint=1000;")  # Auto-checkpoint cada 1000 páginas
            
            conn.commit()
            conn.close()
            
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS("Configuraciones aplicadas:")
            )
            self.stdout.write("  - journal_mode: WAL")
            self.stdout.write("  - busy_timeout: 30000ms")
            self.stdout.write("  - synchronous: NORMAL")
            self.stdout.write("  - wal_autocheckpoint: 1000")
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ La base de datos ahora debería manejar mejor la concurrencia."
                )
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error al configurar WAL: {e}")
            )

