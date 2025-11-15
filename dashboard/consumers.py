"""
Consumer WebSocket para actualizaciones en tiempo real del dashboard.
"""
import json
from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncWebsocketConsumer


class DashboardConsumer(AsyncWebsocketConsumer):
    """Consumer para actualizaciones del dashboard en tiempo real."""
    
    async def connect(self):
        """Conectar al grupo del dashboard."""
        self.group_name = "dashboard_updates"
        
        # Unirse al grupo
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Enviar mensaje de conexión exitosa
        await self.send(text_data=json.dumps({
            "tipo": "conexion",
            "mensaje": "Conectado al dashboard en tiempo real"
        }))
    
    async def disconnect(self, close_code):
        """Desconectar del grupo."""
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
    
    async def recibir_actualizacion(self, event):
        """Recibir actualización del grupo y enviarla al WebSocket."""
        await self.send(text_data=json.dumps(event["data"]))

