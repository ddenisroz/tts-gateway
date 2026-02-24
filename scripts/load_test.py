from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def _one_request(client: httpx.AsyncClient, url: str, idx: int) -> float:
    payload = {
        "channel_name": f"load_channel_{idx % 5}",
        "text": "Привет! Это тестовая фраза для измерения задержки.",
        "author": f"user_{idx}",
        "user_id": idx,
        "provider": "f5",
        "voice_map": {"f5": "female_1", "qwen": "default"},
        "tts_settings": {"advanced_provider": "f5", "voice": "female_1"},
        "word_filter": [],
        "blocked_users": [],
    }
    started = time.perf_counter()
    response = await client.post(url, json=payload)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error") or "request failed")
    return time.perf_counter() - started


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8010/api/tts/synthesize-channel")
    parser.add_argument("--total", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []

    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        async def run_one(i: int) -> None:
            async with semaphore:
                latency = await _one_request(client, args.url, i)
                latencies.append(latency)

        await asyncio.gather(*(run_one(i) for i in range(args.total)))

    latencies.sort()
    p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95) - 1))
    p95 = latencies[p95_index]
    print(f"count={len(latencies)}")
    print(f"mean={statistics.mean(latencies):.3f}s")
    print(f"p95={p95:.3f}s")
    print(f"max={max(latencies):.3f}s")


if __name__ == "__main__":
    asyncio.run(main())

