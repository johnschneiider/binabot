"""
Comando para inicializar la base de datos PostgreSQL desde cero.
Obtiene todos los activos disponibles desde la API de Deriv y los crea.
"""
from decimal import Decimal
from typing import List, Dict, Any

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from core.models import ActivoPermitido, ConfiguracionBot
from integracion_deriv.client import obtener_simbolos_activos_sync


class Command(BaseCommand):
    help = "Inicializa la base de datos PostgreSQL desde cero con todos los activos disponibles de Deriv."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la inicialización sin preguntar",
        )
        parser.add_argument(
            "--solo-forex",
            action="store_true",
            help="Solo incluir activos de Forex",
        )
        parser.add_argument(
            "--excluir-mercados",
            nargs="*",
            help="Mercados a excluir (ej: commodities, indices)",
            default=[],
        )

    def _obtener_simbolos_desde_api(self) -> List[Dict[str, Any]]:
        """Obtiene todos los símbolos activos desde la API de Deriv."""
        try:
            self.stdout.write("Consultando API de Deriv para obtener símbolos activos...")
            respuesta = obtener_simbolos_activos_sync()
            
            # Debug: mostrar estructura de respuesta
            self.stdout.write(f"  Claves en respuesta: {list(respuesta.keys())[:10]}")
            
            # Verificar errores
            if "error" in respuesta:
                error_msg = respuesta.get("error", {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                # Mostrar respuesta completa para debugging
                self.stdout.write(
                    self.style.WARNING(f"Respuesta completa: {respuesta}")
                )
                raise CommandError(f"Error de API: {error_msg}")
            
            # La respuesta puede venir en diferentes formatos
            # Formato 1: {"active_symbols": [...]}
            # Formato 2: {"msg_type": "active_symbols", "active_symbols": [...]}
            active_symbols = respuesta.get("active_symbols", [])
            
            # Si no está en el nivel superior, buscar en otros lugares
            if not active_symbols:
                # Intentar buscar en diferentes estructuras posibles
                for key in ["symbols", "markets", "data"]:
                    if key in respuesta:
                        active_symbols = respuesta[key]
                        break
            
            if not active_symbols:
                # Mostrar la estructura de la respuesta para debugging
                self.stdout.write(
                    self.style.WARNING(
                        f"Estructura de respuesta recibida: {list(respuesta.keys())}"
                    )
                )
                raise CommandError("No se obtuvieron símbolos de la API de Deriv")
            
            if not isinstance(active_symbols, list):
                raise CommandError(f"Formato de respuesta inesperado: {type(active_symbols)}")
            
            return active_symbols
        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f"Error al consultar API de Deriv: {e}") from e

    def _filtrar_simbolos(
        self, 
        simbolos: List[Dict[str, Any]], 
        solo_forex: bool = False,
        excluir_mercados: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Filtra símbolos según los criterios especificados."""
        excluir_mercados = excluir_mercados or []
        
        simbolos_filtrados = []
        for simbolo in simbolos:
            mercado = simbolo.get("market", "").lower()
            tipo = simbolo.get("market_display_name", "").lower()
            
            # Filtrar por mercado
            if solo_forex:
                if mercado != "forex" and "forex" not in tipo:
                    continue
            
            # Excluir mercados
            if any(excluir.lower() in mercado or excluir.lower() in tipo for excluir in excluir_mercados):
                continue
            
            # Solo incluir símbolos que estén disponibles para trading
            if simbolo.get("is_trading_suspended", False):
                continue
            
            simbolos_filtrados.append(simbolo)
        
        return simbolos_filtrados

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

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Este comando consultará la API de Deriv para obtener todos los activos "
                    "disponibles y los creará en la base de datos."
                )
            )
            if options["solo_forex"]:
                self.stdout.write(self.style.WARNING("  → Solo se incluirán activos de Forex"))
            confirmacion = input("¿Deseas continuar? (sí/no): ")
            if confirmacion.lower() not in ["sí", "si", "yes", "y", "s"]:
                self.stdout.write(self.style.ERROR("Operación cancelada."))
                return

        # Obtener símbolos desde API
        self.stdout.write("")
        self.stdout.write("OBTENIENDO ACTIVOS DESDE API DE DERIV...")
        self.stdout.write("-" * 80)
        
        try:
            simbolos = self._obtener_simbolos_desde_api()
            self.stdout.write(self.style.SUCCESS(f"✓ Obtenidos {len(simbolos)} símbolos de la API"))
        except CommandError as e:
            self.stdout.write(self.style.ERROR(f"✗ {e}"))
            return

        # Filtrar símbolos
        simbolos_filtrados = self._filtrar_simbolos(
            simbolos,
            solo_forex=options["solo_forex"],
            excluir_mercados=options.get("excluir_mercados", [])
        )
        
        self.stdout.write(f"  Símbolos después de filtrar: {len(simbolos_filtrados)}")
        self.stdout.write("")

        # Crear activos
        self.stdout.write("CREANDO ACTIVOS PERMITIDOS...")
        self.stdout.write("-" * 80)

        activos_creados = 0
        activos_actualizados = 0
        activos_omitidos = 0
        errores = []

        for simbolo in simbolos_filtrados:
            simbolo_nombre = simbolo.get("symbol", "").strip()
            if not simbolo_nombre:
                continue

            try:
                # Obtener información del símbolo
                display_name = simbolo.get("display_name", simbolo_nombre)
                mercado = simbolo.get("market", "unknown")
                descripcion = f"{display_name} ({mercado})"
                
                # Verificar si el símbolo está disponible para trading
                if simbolo.get("is_trading_suspended", False):
                    activos_omitidos += 1
                    continue

                activo, creado = ActivoPermitido.objects.get_or_create(
                    nombre=simbolo_nombre,
                    defaults={
                        "descripcion": descripcion,
                        "habilitado": True,
                    },
                )
                
                if creado:
                    activos_creados += 1
                    if activos_creados % 10 == 0:
                        self.stdout.write(f"  ... {activos_creados} creados")
                else:
                    # Actualizar si ya existe pero estaba deshabilitado
                    if not activo.habilitado:
                        activo.habilitado = True
                        activo.descripcion = descripcion
                        activo.save()
                        activos_actualizados += 1
            except Exception as e:
                errores.append(f"{simbolo_nombre}: {str(e)}")
                if len(errores) <= 5:  # Solo mostrar los primeros 5 errores
                    self.stdout.write(
                        self.style.ERROR(f"  ✗ Error con {simbolo_nombre}: {e}")
                    )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Activos creados: {activos_creados}, "
                f"actualizados: {activos_actualizados}, "
                f"omitidos (suspendidos): {activos_omitidos}"
            )
        )
        
        if errores:
            self.stdout.write(
                self.style.WARNING(f"⚠️  Errores: {len(errores)} (primeros 5 mostrados arriba)")
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
