"""Gerenciador de conexões WebSocket com broadcast."""

import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Gerencia conexões WebSocket ativas e envia broadcasts."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Aceita e registra uma nova conexão WebSocket."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove uma conexão desconectada."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_json(self, websocket: WebSocket, data: dict[str, Any]) -> None:
        """Envia uma mensagem JSON para um cliente específico."""
        try:
            await websocket.send_json(data)
        except Exception:
            self.disconnect(websocket)

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Envia uma mensagem JSON para todos os clientes conectados."""
        disconnected: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    async def notifica_estado(self, estado: str) -> None:
        """Broadcast do estado do cardápio (Aberto/Fechado)."""
        await self.broadcast({"tipo": "estado", "dados": estado})

    async def notifica_cardapio(self, cardapio: Any) -> None:
        """Broadcast do cardápio atualizado."""
        await self.broadcast({"tipo": "cardapio", "dados": cardapio})

    async def notifica_pedidos(self, pedidos: list[Any]) -> None:
        """Broadcast da lista de pedidos atualizada."""
        await self.broadcast({"tipo": "pedidos", "dados": pedidos})


# Instância global do gerenciador
manager = ConnectionManager()
