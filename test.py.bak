import asyncio
from cylink.auralis import AsyncAuralis

CODE = """
import requests
password = "abc123"
def fetch(url):
    return requests.get(url).text
"""

async def main():
    client = AsyncAuralis(api_key="cyk_db4d78889d8f7337d4c7857af864de6d08aba8cb")
    
    print("=== Streaming ===")
    async for token in client.stream_analyze(CODE, language="python"):
        print(token, end="", flush=True)
    
    print("\n\n=== Full result ===")
    result = await client.analyze(CODE, language="python")
    print("Safety:", result.safety_tier)
    print("Confidence:", result.confidence)
    for risk in result.risks:
        print(f"  [{risk.severity}] {risk.label}")

asyncio.run(main())
