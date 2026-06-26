import httpx
from .cylink_models import ChatResponse
from .exceptions import APIError, AuthenticationError
from .errors import CylinkAPIError


class AsyncCylink:
    def __init__(self, api_key: str):
        self.base_url = "https://tdbgpvscwaysndrloltl.supabase.co/functions/v1"
        self.api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, endpoint: str, payload: dict = None):
        url = f"{self.base_url}/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.request(
                    method, url,
                    headers=self._headers,
                    json=payload or {},
                )
                if res.status_code == 401:
                    raise AuthenticationError("Invalid API key")
                if not res.is_success:
                    raise APIError(res.text, res.status_code)
                return res.json()
        except httpx.RequestError as e:
            raise CylinkAPIError(str(e))

    async def chat(self, message: str, model: str = "cyanix-core") -> ChatResponse:
        data = await self._request("POST", "cylink-api", {
            "model": model,
            "messages": [{"role": "user", "content": message}],
        })
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            raise CylinkAPIError("Malformed response from Cylink API")
        return ChatResponse(content=content, raw=data, model=model)

    async def ari(self, query: str):
        return await self._request("POST", "ari", {"query": query})

    async def axion(self, query: str, route: str):
        return await self._request("POST", "axion", {"query": query, "route": route})

    async def tools(self, tool: str, query: str):
        return await self._request("POST", "tools", {"tool": tool, "query": query})

    async def models(self):
        return await self._request("GET", "models")

    async def usage(self):
        return await self._request("GET", "usage")

    async def status(self):
        return await self._request("GET", "status")
