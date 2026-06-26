import asyncio
from cylink import AsyncCylink

async def main():
    client = AsyncCylink(api_key="cyk_db4d78889d8f7337d4c7857af864de6d08aba8cb")
    response = await client.chat("Hello!")
    print(response.content)
    print("Model:", response.model)

asyncio.run(main())
