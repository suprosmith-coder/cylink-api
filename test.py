import asyncio
from cylink import AsyncAuralis

CODE = """
import requests
password = "abc123"
def fetch(url):
    return requests.get(url).text
"""

async def main():
    client = AsyncAuralis(supabase_jwt="YOUR_SUPABASE_JWT")

    print("=== Streaming tokens ===")
    async for token in client.stream_analyze(CODE, language="python"):
        print(token, end="", flush=True)

    print("\n\n=== Structured result ===")
    result = await client.analyze(CODE, language="python")
    print("Safety tier:", result.safety_tier)
    print("Confidence:", result.confidence)
    for risk in result.risks:
        print(f"  [{risk.severity}] {risk.label} — {risk.description}")
    print("Suggestion:\n", result.suggestion)

asyncio.run(main())
