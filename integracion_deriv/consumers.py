from channels.generic.websocket import AsyncJsonWebsocketConsumer


class DerivStatusConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("deriv_estado", self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard("deriv_estado", self.channel_name)

    async def recibir_evento_deriv(self, event):
        await self.send_json(event["data"])

