import httpx
import pytest

from hosted_mcp_transport import (
    CappedAsyncTransport,
    HostedMcpResponseEncodingError,
    HostedMcpResponseTooLarge,
)


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.iterations = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.iterations += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_declared_oversize_is_rejected_without_reading_response_body():
    stream = TrackingStream([b"provider body must not be read"])
    seen_accept_encoding = None

    def handler(request):
        nonlocal seen_accept_encoding
        seen_accept_encoding = request.headers["accept-encoding"]
        return httpx.Response(
            200,
            headers={"Content-Length": "9"},
            stream=stream,
        )

    transport = CappedAsyncTransport(
        httpx.MockTransport(handler),
        maximum_bytes=8,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(HostedMcpResponseTooLarge):
            await client.get("https://provider.example/mcp")

    assert seen_accept_encoding == "identity"
    assert stream.iterations == 0
    assert stream.closed is True


@pytest.mark.asyncio
async def test_streamed_oversize_stops_before_overflow_chunk_is_materialized():
    stream = TrackingStream([b"1234", b"5678", b"must-not-be-read"])

    def handler(request):
        return httpx.Response(200, stream=stream, request=request)

    transport = CappedAsyncTransport(
        httpx.MockTransport(handler),
        maximum_bytes=7,
    )
    received = []
    client = httpx.AsyncClient(transport=transport)
    async with (
        client,
        client.stream("GET", "https://provider.example/mcp") as response,
    ):
        with pytest.raises(HostedMcpResponseTooLarge):
            async for chunk in response.aiter_raw():
                received.append(chunk)

    assert received == [b"1234"]
    assert stream.iterations == 2
    assert stream.closed is True


@pytest.mark.asyncio
async def test_encoded_response_is_rejected_before_reading_body():
    stream = TrackingStream([b"compressed-provider-body"])

    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=stream,
        )

    transport = CappedAsyncTransport(
        httpx.MockTransport(handler),
        maximum_bytes=1024,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(HostedMcpResponseEncodingError):
            await client.get("https://provider.example/mcp")

    assert stream.iterations == 0
    assert stream.closed is True
