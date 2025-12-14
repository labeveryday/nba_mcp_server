#!/usr/bin/env python3
"""Capture all output including stderr."""

import asyncio
import sys
import subprocess
import json

async def test_server_communication():
    """Test full server communication cycle."""
    
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "nba_mcp_server",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"NBA_MCP_LOG_LEVEL": "INFO"}
    )
    
    print(f"Server PID: {proc.pid}")
    
    # Send initialize
    init_msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", 
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, 
                          "clientInfo": {"name": "test", "version": "1.0"}}}
    
    msg_str = json.dumps(init_msg) + "\n"
    proc.stdin.write(msg_str.encode())
    await proc.stdin.drain()
    print("Sent initialize request")
    
    # Try to read response
    try:
        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        print(f"Response: {response_line.decode()}")
        
        # Send list_tools
        list_msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        msg_str = json.dumps(list_msg) + "\n"
        proc.stdin.write(msg_str.encode())
        await proc.stdin.drain()
        print("Sent list_tools request")
        
        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        response = json.loads(response_line.decode())
        print(f"Tools count: {len(response.get('result', {}).get('tools', []))}")
        print("✓ Server communication works!")
        
    except asyncio.TimeoutError:
        print("❌ Timeout waiting for response")
        stderr = await proc.stderr.read()
        if stderr:
            print(f"Stderr:\n{stderr.decode()}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2)
        except:
            proc.kill()

if __name__ == "__main__":
    asyncio.run(test_server_communication())
