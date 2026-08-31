"""Bound response bodies before the hosted MCP SDK can materialize them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, Final

import httpx

# Tool discovery can legitimately include up to 128 schemas of 64 KiB each.
# Keep the transport ceiling above that policy envelope while still bounding any
# single JSON or SSE response before the MCP SDK parses it.
MAX_HOSTED_MCP_RESPONSE_BYTES: Final = 16 * 1024 * 1024


class HostedMcpTransportError(httpx.TransportError):
    """A content-free transport failure with only the provider status retained."""

    def __init__(self, message: str, *, request: httpx.Request, status_code: int) -> None:
        super().__init__(message, request=request)
        self.status_code = status_code


class HostedMcpResponseTooLarge(HostedMcpTransportError):
    """A provider response exceeded Rally's transport-level byte ceiling."""


class HostedMcpResponseEncodingError(HostedMcpTransportError):
    """A provider used an encoding whose decoded size cannot be bounded here."""


def _too_large(request: httpx.Request, status_code: int) -> HostedMcpResponseTooLarge:
    return HostedMcpResponseTooLarge(
        "hosted MCP response exceeded the byte limit",
        request=request,
        status_code=status_code,
    )


async def _close_quietly(value: Any) -> None:
    with suppress(Exception):
        await value.aclose()


class CappedAsyncByteStream(httpx.AsyncByteStream):
    """Stop yielding a response as soon as its streamed bytes exceed a cap."""

    def __init__(
        self,
        stream: httpx.AsyncByteStream,
        *,
        maximum_bytes: int,
        request: httpx.Request,
        status_code: int,
    ) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._request = request
        self._status_code = status_code
        self._received = 0
        self._closed = False

    async def __aiter__(self):
        async for chunk in self._stream:
            self._received += len(chunk)
            if self._received > self._maximum_bytes:
                error = _too_large(self._request, self._status_code)
                await _close_quietly(self)
                raise error
            yield chunk

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._stream.aclose()


class CappedAsyncTransport(httpx.AsyncBaseTransport):
    """Wrap an HTTPX transport with declared and streamed response limits."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport,
        *,
        maximum_bytes: int,
    ) -> None:
        if (
            isinstance(maximum_bytes, bool)
            or not isinstance(maximum_bytes, int)
            or maximum_bytes < 1
        ):
            raise ValueError("maximum_bytes must be a positive integer")
        self._transport = transport
        self.maximum_bytes = maximum_bytes

    async def __aenter__(self):
        await self._transport.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self._transport.__aexit__(exc_type, exc_value, traceback)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # A raw-stream cap cannot bound decompressed output. Request identity and
        # reject a server that ignores it before any encoded body is consumed.
        request.headers["Accept-Encoding"] = "identity"
        response = await self._transport.handle_async_request(request)

        content_encoding = response.headers.get("content-encoding")
        if content_encoding and any(
            encoding.strip().casefold() != "identity" for encoding in content_encoding.split(",")
        ):
            error = HostedMcpResponseEncodingError(
                "hosted MCP response encoding cannot be safely bounded",
                request=request,
                status_code=response.status_code,
            )
            await _close_quietly(response)
            raise error

        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                declared_bytes = int(declared)
            except ValueError:
                declared_bytes = None
            if declared_bytes is not None and declared_bytes > self.maximum_bytes:
                error = _too_large(request, response.status_code)
                await _close_quietly(response)
                raise error

        try:
            buffered_content = response.content
        except httpx.ResponseNotRead:
            buffered_content = None
        if buffered_content is not None and len(buffered_content) > self.maximum_bytes:
            error = _too_large(request, response.status_code)
            await _close_quietly(response)
            raise error

        if not isinstance(response.stream, httpx.AsyncByteStream):
            await response.aclose()
            raise TypeError("wrapped transport returned a synchronous response stream")
        response.stream = CappedAsyncByteStream(
            response.stream,
            maximum_bytes=self.maximum_bytes,
            request=request,
            status_code=response.status_code,
        )
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def make_hosted_mcp_http_client(
    *,
    headers: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> Any:
    """Create the production MCP client while retaining transport injection."""

    capped_transport = CappedAsyncTransport(
        transport if transport is not None else httpx.AsyncHTTPTransport(),
        maximum_bytes=MAX_HOSTED_MCP_RESPONSE_BYTES,
    )
    return client_factory(
        headers=headers,
        timeout=httpx.Timeout(12.0, read=20.0),
        follow_redirects=False,
        transport=capped_transport,
    )
