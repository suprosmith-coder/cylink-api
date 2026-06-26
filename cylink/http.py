import requests
from .exceptions import APIError, AuthenticationError

class HTTPClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def request(self, method: str, endpoint: str, json=None):
        url = f"{self.base_url}/{endpoint}"
        try:
            res = requests.request(
                method, url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=json,
                timeout=60,
            )
            if res.status_code == 401:
                raise AuthenticationError("Invalid API key")
            if not res.ok:
                raise APIError(res.text, res.status_code)
            return res.json()
        except requests.RequestException as e:
            raise APIError(str(e))
