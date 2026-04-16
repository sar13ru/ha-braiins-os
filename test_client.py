import asyncio
from braiins_client.client import BraiinsClient


async def main():
    # 🔧 Cambia esto por la IP real de tu S21
    host = "10.10.20.4"

    client = BraiinsClient(
        host=host,
        backend="grpc"
    )

    try:
        data = await client.async_get_summary()

        print("\n=== RESULT ===")
        for k, v in data.items():
            print(f"{k}: {v}")

    except Exception as e:
        print("\n=== ERROR ===")
        print(str(e))


if __name__ == "__main__":
    asyncio.run(main())