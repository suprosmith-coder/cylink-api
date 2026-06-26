from .http import HTTPClient
from .cylink_models import ChatResponse
from .errors import CylinkAPIError


class Cylink:
    def __init__(self, api_key: str):
        self.base_url = "https://tdbgpvscwaysndrloltl.supabase.co/functions/v1"
        self.http = HTTPClient(self.base_url, api_key)
        self.api_key = api_key

    # -------------------------
    # internal request wrapper
    # -------------------------
    def _request(self, method: str, endpoint: str, payload: dict | None = None):
        try:
            return self.http.request(method, endpoint, payload or {})
        except Exception as e:
            raise CylinkAPIError(str(e))

    # -------------------------
    # CHAT
    # -------------------------
    def chat(self, message: str, model: str = "cyanix-core") -> ChatResponse:
        data = self._request(
            "POST",
            "cylink-api",
            {
                "model": model,
                "messages": [{"role": "user", "content": message}],
            },
        )

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            raise CylinkAPIError("Malformed response from Cylink API")

        return ChatResponse(
            content=content,
            raw=data,
            model=model,
        )

    # -------------------------
    # ARI routing
    # -------------------------
    def ari(self, query: str):
        return self._request("POST", "ari", {"query": query})

    # -------------------------
    # Axion routing
    # -------------------------
    def axion(self, query: str, route: str):
        return self._request(
            "POST",
            "axion",
            {"query": query, "route": route},
        )

    # -------------------------
    # Tools
    # -------------------------
    def tools(self, tool: str, query: str):
        return self._request(
            "POST",
            "tools",
            {"tool": tool, "query": query},
        )

    # -------------------------
    # Models
    # -------------------------
    def models(self):
        return self._request("GET", "models")

    # -------------------------
    # Usage
    # -------------------------
    def usage(self):
        return self._request("GET", "usage")

    # -------------------------
    # Status
    # -------------------------
    def status(self):
        return self._request("GET", "status")