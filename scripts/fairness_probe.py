from __future__ import annotations

import argparse
import asyncio
import collections
import time

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8010/api/tts/synthesize-channel")
    parser.add_argument("--tenants", type=int, default=4)
    parser.add_argument("--per-tenant", type=int, default=8)
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    done: list[tuple[str, float]] = []
    async with httpx.AsyncClient(timeout=90.0, headers=headers) as client:
        async def run_one(tenant: str, idx: int) -> None:
            payload = {
                "channel_name": tenant,
                "tenant_id": f"tenant:{tenant}",
                "text": f"Fairness test message {idx}",
                "author": f"{tenant}_user_{idx}",
                "user_id": idx,
                "provider": "f5",
                "tts_settings": {"advanced_provider": "f5", "voice": "female_1", "tenant_weight": 1.0},
                "voice_map": {"f5": "female_1", "qwen": "default"},
            }
            started = time.perf_counter()
            response = await client.post(args.url, json=payload)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "failed")
            done.append((tenant, time.perf_counter() - started))

        tasks = []
        for t in range(args.tenants):
            tenant = f"tenant_{t+1}"
            for i in range(args.per_tenant):
                tasks.append(asyncio.create_task(run_one(tenant, i)))
        await asyncio.gather(*tasks)

    grouped = collections.defaultdict(list)
    for tenant, latency in done:
        grouped[tenant].append(latency)

    for tenant in sorted(grouped):
        values = grouped[tenant]
        values.sort()
        p95 = values[max(0, int(len(values) * 0.95) - 1)]
        print(f"{tenant}: count={len(values)} p95={p95:.3f}s mean={sum(values)/len(values):.3f}s")


if __name__ == "__main__":
    asyncio.run(main())

