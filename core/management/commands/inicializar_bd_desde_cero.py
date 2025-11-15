"""
Comando para inicializar la base de datos PostgreSQL desde cero.
Útil cuando se migra a PostgreSQL y se quiere empezar sin datos históricos.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from core.models import ActivoPermitido, ConfiguracionBot


class Command(BaseCommand):
    help = "Inicializa la base de datos PostgreSQL desde cero con datos mínimos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la inicialización sin preguntar",
        )
        parser.add_argument(
            "--activos",
            nargs="*",
            help="Lista de activos a crear (por defecto: R_10, R_25, R_50, R_75, R_100)",
            default=["R_10", "R_25", "R_50", "R_75", "R_100"],
        )

    def handle(self, *args, **options):
        # Verificar que estamos usando PostgreSQL
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            raise CommandError(
                "Este comando solo funciona cuando la base de datos actual es PostgreSQL."
            )

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("INICIALIZACIÓN DE BASE DE DATOS DESDE CERO"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        # Verificar estado actual
        activos_existentes = ActivoPermitido.objects.count()
        config_existente = ConfiguracionBot.objects.count()

        self.stdout.write("ESTADO ACTUAL:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"  Activos permitidos: {activos_existentes}")
        self.stdout.write(f"  Configuraciones: {config_existente}")
        self.stdout.write("")

        if activos_existentes > 0 or config_existente > 0:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Ya existen datos en la base de datos. "
                    "Este comando solo creará los datos faltantes."
                )
            )
            self.stdout.write("")

        # Activos a crear
        activos_a_crear = options["activos"]
        self.stdout.write("ACTIVOS A CREAR:")
        self.stdout.write("-" * 80)
        for activo in activos_a_crear:
            existe = ActivoPermitido.objects.filter(nombre=activo).exists()
            estado = "✓ ya existe" if existe else "→ crear"
            self.stdout.write(f"  {activo}: {estado}")
        self.stdout.write("")

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Este comando creará los activos permitidos y asegurará "
                    "que exista una configuración del bot."
                )
            )
            confirmacion = input("¿Deseas continuar? (sí/no): ")
            if confirmacion.lower() not in ["sí", "si", "yes", "y", "s"]:
                self.stdout.write(self.style.ERROR("Operación cancelada."))
                return

        # Crear activos
        self.stdout.write("")
        self.stdout.write("CREANDO ACTIVOS PERMITIDOS...")
        self.stdout.write("-" * 80)

        activos_creados = 0
        activos_existentes_count = 0

        for activo_nombre in activos_a_crear:
            activo, creado = ActivoPermitido.objects.get_or_create(
                nombre=activo_nombre,
                defaults={
                    "descripcion": f"Índice sintético {activo_nombre}",
                    "habilitado": True,
                },
            )
            if creado:
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Creado: {activo_nombre}")
                )
                activos_creados += 1
            else:
                self.stdout.write(f"  → Ya existe: {activo_nombre}")
                activos_existentes_count += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Activos creados: {activos_creados}, "
                f"ya existían: {activos_existentes_count}"
            )
        )

        # Asegurar que existe ConfiguracionBot
        self.stdout.write("")
        self.stdout.write("VERIFICANDO CONFIGURACIÓN DEL BOT...")
        self.stdout.write("-" * 80)

        config, creado = ConfiguracionBot.objects.get_or_create(
            pk=1,
            defaults={
                "balance_meta_base": Decimal("10000.00"),
                "balance_stop_loss_base": Decimal("10000.00"),
                "meta_actual": Decimal("100.00"),
                "stop_loss_actual": Decimal("200.00"),
            },
        )

        if creado:
            self.stdout.write(
                self.style.SUCCESS("  ✓ Configuración del bot creada")
            )
        else:
            self.stdout.write("  → Configuración del bot ya existe")

        # Resumen final
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("INICIALIZACIÓN COMPLETADA"))
        self.stdout.write("=" * 80)
        self.stdout.write("")

        # Verificar estado final
        activos_finales = ActivoPermitido.objects.filter(habilitado=True).count()
        self.stdout.write("ESTADO FINAL:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"  Activos permitidos totales: {ActivoPermitido.objects.count()}")
        self.stdout.write(f"  Activos habilitados: {activos_finales}")
        self.stdout.write(f"  Configuraciones: {ConfiguracionBot.objects.count()}")
        self.stdout.write("")

        if activos_finales > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ La base de datos está lista. Puedes iniciar los servicios del bot."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  No hay activos habilitados. Verifica la configuración."
                )
            )

