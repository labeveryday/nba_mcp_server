#!/usr/bin/env python3
"""
Alternative smoke test using direct subprocess communication.
This works around stdio_client compatibility issues with Python 3.13.
"""

import asyncio
import json
import sys
import subprocess
from datetime import datetime


async def main() -> int:
    """Test NBA MCP server via direct subprocess communication."""
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting NBA MCP server test...")
    
    # Start server
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "nba_mcp_server",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Server started (PID: {proc.pid})")
    
    try:
        # Test 1: Initialize
        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "1.0"}
            }
        }
        
        proc.stdin.write((json.dumps(init_msg) + "\n").encode())
        await proc.stdin.drain()
        
        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        response = json.loads(response_line.decode())
        
        if response.get("result"):
            print(f"✓ Initialize successful")
        else:
            print(f"✗ Initialize failed: {response}")
            return 1
        
        # Test 2: List tools
        list_msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        proc.stdin.write((json.dumps(list_msg) + "\n").encode())
        await proc.stdin.drain()
        
        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        response = json.loads(response_line.decode())
        
        tools = response.get("result", {}).get("tools", [])
        print(f"✓ Listed {len(tools)} tools")
        
        # Test 3: Call a simple tool
        call_msg = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_server_info",
                "arguments": {}
            }
        }
        proc.stdin.write((json.dumps(call_msg) + "\n").encode())
        await proc.stdin.drain()
        
        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        response = json.loads(response_line.decode())
        
        if response.get("result"):
            print(f"✓ Tool call successful")
        else:
            print(f"✗ Tool call failed: {response}")
            return 1
        
        print(f"\n✓ All tests passed!")
        return 0
        
    except asyncio.TimeoutError:
        print("✗ Timeout waiting for server response")
        stderr = await proc.stderr.read()
        if stderr:
            print(f"Server stderr:\n{stderr.decode()}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2)
        except:
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
