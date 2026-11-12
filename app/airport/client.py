"""Airport Streamable HTTP adapter."""

from __future__ import annotations

import base64
import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class AirportUnavailable(RuntimeError):
    pass


class AirportToolError(RuntimeError):
    pass


class McpAirportClient:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("CREATE_JUNIOR_AIRPORT_MCP_URL", "http://127.0.0.1:8765/mcp")

    def is_reachable(self) -> bool:
        parsed = urlparse(self.url)
        if not parsed.hostname:
            return False
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.2)
        try:
            return probe.connect_ex((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))) == 0
        finally:
            probe.close()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        parsed = urlparse(self.url)
        if parsed.hostname:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.2)
            result = probe.connect_ex((parsed.hostname, port))
            probe.close()
            if result != 0:
                exc = OSError(result, "connection refused")
                raise AirportUnavailable(f"Airport MCP unavailable at {self.url}: {exc}") from exc
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=1.0), follow_redirects=False)
        stream_context = streamable_http_client(self.url, http_client=http_client)
        session_context = None
        stream_entered = False
        session_entered = False
        try:
            read, write, _ = await asyncio.wait_for(stream_context.__aenter__(), timeout=3.0)
            stream_entered = True
            session_context = ClientSession(read, write)
            session = await asyncio.wait_for(session_context.__aenter__(), timeout=3.0)
            session_entered = True
            await asyncio.wait_for(session.initialize(), timeout=3.0)
        except Exception as exc:  # transport implementations expose different exception types
            if session_context is not None and session_entered:
                await session_context.__aexit__(type(exc), exc, exc.__traceback__)
            if stream_entered:
                await stream_context.__aexit__(type(exc), exc, exc.__traceback__)
            await http_client.aclose()
            raise AirportUnavailable(f"Airport MCP unavailable at {self.url}: {exc}") from exc
        try:
            yield session
        finally:
            if session_entered:
                await session_context.__aexit__(None, None, None)
            if stream_entered:
                await stream_context.__aexit__(None, None, None)
            await http_client.aclose()

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
            if "create_status" in tools:
                return self._payload(await session.call_tool("create_status", {}))
            if "create_get_capabilities" in tools:
                capabilities = self._payload(await session.call_tool("create_get_capabilities", {}))
                return {
                    "status": "legacy",
                    "tool_count": len(tools),
                    "has_typed_geometry": "create_geometry_scene_import_topology_plan" in tools,
                    "capability_keys": sorted(capabilities)[:20],
                }
            return {
                "status": "limited",
                "tool_count": len(tools),
                "has_typed_geometry": "create_geometry_scene_import_topology_plan" in tools,
            }

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
