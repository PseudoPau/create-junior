"""Airport Streamable HTTP adapter."""

from __future__ import annotations

import base64
import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class AirportUnavailable(RuntimeError):
    pass


class AirportToolError(RuntimeError):
    pass


class McpAirportClient:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("CREATE_JUNIOR_AIRPORT_MCP_URL", "http://127.0.0.1:8765/mcp")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        try:
            async with streamable_http_client(self.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        except Exception as exc:  # transport implementations expose different exception types
            raise AirportUnavailable(f"Airport MCP unavailable at {self.url}: {exc}") from exc

    @staticmethod
    def _payload(reply: Any) -> dict[str, Any]:
        if reply.isError:
            details = ""
            if reply.content:
                details = getattr(reply.content[0], "text", "")
            raise AirportToolError(details or "Airport MCP tool failed")
        payload = reply.structuredContent or {}
        if not payload and reply.content:
            text = getattr(reply.content[0], "text", "")
            if text:
                payload = json.loads(text)
        if payload.get("ok") is False:
            error = payload.get("error") or {}
            raise AirportToolError(error.get("message", "Airport MCP tool failed"))
        return payload.get("data", payload)

    async def list_tools(self) -> set[str]:
        async with self._session() as session:
            catalog = await session.list_tools()
            return {tool.name for tool in catalog.tools}

    async def status(self) -> dict[str, Any]:
        async with self._session() as session:
            tools = {tool.name for tool in (await session.list_tools()).tools}
            if "create_status" not in tools:
                raise AirportToolError("Airport typed MCP does not expose create_status")
            return self._payload(await session.call_tool("create_status", {}))

    async def get_project(self) -> dict[str, Any]:
        async with self._session() as session:
            return self._payload(await session.call_tool("create_project_get", {}))

    async def import_topology_plan(self, request: dict[str, Any], context_id: str) -> dict[str, Any]:
        async with self._session() as session:
            return self._payload(
                await session.call_tool(
                    "create_geometry_scene_import_topology_plan",
                    {"request": request, "context_id": context_id},
                )
            )

    async def preview(self, objects: list[str], context_id: str, view: str = "perspective", size: int = 512) -> dict[str, Any]:
        async with self._session() as session:
            reply = await session.call_tool(
                "create_geometry_scene_preview",
                {"request": {"objects": objects, "view": view, "size": size}, "context_id": context_id},
            )
            result = self._payload(reply)
            image = next((item.data for item in reply.content if getattr(item, "type", None) == "image"), None)
            if image:
                result["image_base64"] = image
            return result

    async def verify(self, objects: list[str], conditions: list[dict[str, Any]], context_id: str) -> dict[str, Any]:
        async with self._session() as session:
            return self._payload(
                await session.call_tool(
                    "create_scene_verify",
                    {"request": {"objects": objects, "conditions": conditions}, "context_id": context_id},
                )
            )
