# src/api/artwork_proxy.py
import httpx
from fastapi import HTTPException, Response

ARTWORK_FETCH_TIMEOUT_S = 10.0


async def fetch_artwork(image_url: str) -> Response:
    """
    In cases where server-side image requests need to fetch images (eg anti-bot),
    pass in the image source url. Returns error if unable to load - a usable signal
    to the client to try alternatives.
    """
    async with httpx.AsyncClient() as client:
        try:
            upstream = await client.get(image_url, timeout=ARTWORK_FETCH_TIMEOUT_S)
            upstream.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Could not fetch artwork from source")

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )