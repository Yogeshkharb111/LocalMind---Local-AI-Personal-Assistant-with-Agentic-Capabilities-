import asyncio
import json


async def test():
    proc = await asyncio.create_subprocess_exec(
        "node",
        r"C:\Users\Yogesh Kharb\AppData\Roaming\npm\node_modules\@modelcontextprotocol\server-filesystem\dist\index.js",
        r"C:\Users\Yogesh Kharb",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    print(f"Process started, PID: {proc.pid}")

    # Send initialize request
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "test", "version": "1.0"},
        }
    }) + "\n"

    print(f"Sending: {request.strip()}")
    proc.stdin.write(request.encode())
    await proc.stdin.drain()

    print("Waiting for response...")
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=10.0)
        print(f"Got response: {line.decode()}")
    except TimeoutError:
        print("TIMEOUT - no response in 10 seconds")
        stderr = await proc.stderr.read(1000)
        print(f"Stderr: {stderr.decode()}")

    proc.terminate()

asyncio.run(test())
