import re
import json
import httpx
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional
from .exceptions import APIError, AuthenticationError
from .errors import CylinkAPIError


@dataclass
class AuralisRisk:
    id: str
    label: str
    severity: str
    category: str
    description: str


@dataclass
class AuralisResult:
    intent: str
    intent_detail: str
    complexity: str
    complexity_note: str
    confidence: int
    safety_tier: str
    risks: List[AuralisRisk]
    suggestion: str
    explanation: List[str]
    raw: dict = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "AuralisResult":
        risks = [
            AuralisRisk(
                id=r.get("id", ""),
                label=r.get("label", ""),
                severity=r.get("severity", "low"),
                category=r.get("category", "logic"),
                description=r.get("description", ""),
            )
            for r in data.get("risks", [])
        ]
        return cls(
            intent=data.get("intent", ""),
            intent_detail=data.get("intent_detail", ""),
            complexity=data.get("complexity", "medium"),
            complexity_note=data.get("complexity_note", ""),
            confidence=data.get("confidence", 0),
            safety_tier=data.get("safety_tier", "medium"),
            risks=risks,
            suggestion=data.get("suggestion", ""),
            explanation=data.get("explanation", []),
            raw=data,
        )


class AsyncAuralis:
    """
    Async client for the Auralis edge function (/functions/v1/analyze).

    Requires a Supabase JWT (from supabase.auth.sign_in_with_password etc.),
    NOT a cyk_ API key.

    Usage:
        client = AsyncAuralis(supabase_jwt="eyJ...")
        result = await client.analyze("print('hello')", language="python")
        async for token in client.stream_analyze("...", language="js"):
            print(token, end="", flush=True)
    """

    BASE_URL = "https://tdbgpvscwaysndrloltl.supabase.co/functions/v1/analyze"

    def __init__(self, supabase_jwt: str):
        self.supabase_jwt = supabase_jwt
        self._headers = {
            "Authorization": f"Bearer {supabase_jwt}",
            "Content-Type": "application/json",
        }

    async def _stream_sse(self, payload: dict) -> AsyncIterator[dict]:
        """Low-level SSE reader — yields parsed JSON event dicts."""
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                self.BASE_URL,
                headers=self._headers,
                json=payload,
            ) as res:
                if res.status_code == 401:
                    raise AuthenticationError("Invalid or expired Supabase JWT")
                if res.status_code == 429:
                    raise APIError("Rate limit exceeded — max 20 requests/min", 429)
                if not res.is_success:
                    body = await res.aread()
                    raise APIError(body.decode(), res.status_code)

                async for line in res.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        return
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue

    async def stream_analyze(
        self,
        code: str,
        language: str = "python",
        model: str = "llama-3.3-70b-versatile",
    ) -> AsyncIterator[str]:
        """
        Stream raw tokens from Auralis analysis.
        Yields token strings as they arrive.
        The final SSE event contains the structured result — use analyze() for that.
        """
        payload = {"mode": "analyze", "code": code, "language": language, "model": model}
        async for event in self._stream_sse(payload):
            if "error" in event:
                raise CylinkAPIError(event["error"])
            if "token" in event:
                yield event["token"]

    async def analyze(
        self,
        code: str,
        language: str = "python",
        model: str = "llama-3.3-70b-versatile",
    ) -> AuralisResult:
        """
        Fully analyze code and return a structured AuralisResult.
        Consumes the full SSE stream and returns the final result object.
        """
        payload = {"mode": "analyze", "code": code, "language": language, "model": model}
        result_dict = None

        async for event in self._stream_sse(payload):
            if "error" in event:
                raise CylinkAPIError(event["error"])
            if "result" in event:
                result_dict = event["result"]

        if result_dict is None:
            raise CylinkAPIError("Auralis returned no result")

        return AuralisResult.from_dict(result_dict)

    async def stream_chat(
        self,
        messages: list,
        model: str = "llama-3.3-70b-versatile",
    ) -> AsyncIterator[str]:
        """Stream chat tokens from Auralis chat mode."""
        payload = {"mode": "chat", "messages": messages, "model": model}
        async for event in self._stream_sse(payload):
            if "error" in event:
                raise CylinkAPIError(event["error"])
            if "token" in event:
                yield event["token"]

    async def chat(
        self,
        messages: list,
        model: str = "llama-3.3-70b-versatile",
    ) -> str:
        """Chat with Auralis and return the full response as a string."""
        full = ""
        async for token in self.stream_chat(messages, model=model):
            full += token
        return full.strip()
