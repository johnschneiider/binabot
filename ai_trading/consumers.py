"""
Consumer WebSocket para actualizaciones en tiempo real del entrenamiento de IA.
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class EntrenamientoIAConsumer(AsyncWebsocketConsumer):
    """Consumer para actualizaciones del entrenamiento de IA en tiempo real."""
    
    async def connect(self):
        """Conectar al grupo del entrenamiento de IA."""
        self.group_name = "entrenamiento_ia_updates"
        
        # Unirse al grupo
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Enviar mensaje de conexión exitosa
        await self.send(text_data=json.dumps({
            "tipo": "conexion",
            "mensaje": "Conectado al entrenamiento de IA en tiempo real"
        }))
    
    async def disconnect(self, close_code):
        """Desconectar del grupo."""
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
    
    async def recibir_actualizacion_entrenamiento(self, event):
        """Recibir actualización del grupo y enviarla al WebSocket."""
        await self.send(text_data=json.dumps(event["data"]))

