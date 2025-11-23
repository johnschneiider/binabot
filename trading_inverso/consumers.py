"""
Consumer WebSocket para actualizaciones en tiempo real del bot inverso.
"""
import json
from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncWebsocketConsumer


class BotInversoConsumer(AsyncWebsocketConsumer):
    """Consumer para actualizaciones del bot inverso en tiempo real."""
    
    async def connect(self):
        """Conectar al grupo del bot inverso."""
        self.group_name = "deriv_estado_inverso"
        
        # Unirse al grupo
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Enviar mensaje de conexión exitosa
        await self.send(text_data=json.dumps({
            "tipo": "conexion",
            "mensaje": "Conectado al bot inverso en tiempo real"
        }))
    
    async def disconnect(self, close_code):
        """Desconectar del grupo."""
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
    
    async def recibir_evento_deriv_inverso(self, event):
        """Recibir evento del grupo y enviarlo al WebSocket."""
        await self.send(text_data=json.dumps(event["data"]))

