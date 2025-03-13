import os
import sys
import asyncio
import subprocess
from aiohttp import web, ClientSession

# Get Kubeflow URL prefix
NB_PREFIX = os.environ.get('NB_PREFIX', '')
print(f"Using Kubeflow prefix: {NB_PREFIX}")

# The port ComfyUI will run on internally
COMFY_PORT = 8188

# Create a modified version of server.py to disable the host/origin check
def patch_comfyui_server():
    server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
    backup_path = server_path + ".backup"
    
    # Create backup if it doesn't exist
    if not os.path.exists(backup_path):
        import shutil
        shutil.copy2(server_path, backup_path)
        print("Created backup of server.py")
    
    # Read the file line by line to preserve indentation
    with open(backup_path, 'r') as f:
        lines = f.readlines()
    
    patched_lines = []
    patched = False
    for line in lines:
        # Check if this is the line with the security check
        if "if host_domain != origin_domain:" in line:
            # Calculate indentation (number of spaces)
            indentation = len(line) - len(line.lstrip())
            # Create the new line with the same indentation
            new_line = ' ' * indentation + "if False:  # Disabled by Kubeflow proxy - original: host_domain != origin_domain\n"
            patched_lines.append(new_line)
            patched = True
        else:
            patched_lines.append(line)
    
    # Write the patched content back to the file
    with open(server_path, 'w') as f:
        f.writelines(patched_lines)
    
    if patched:
        print("Patched server.py to disable host/origin security check")
    else:
        print("Warning: Could not find security check line in server.py")
    
    return patched

# Start ComfyUI as a subprocess with patched server
def start_comfyui():
    # Patch server.py to disable the security check
    patch_comfyui_server()
    
    # Start ComfyUI with appropriate arguments
    cmd = [sys.executable, "main.py", "--listen", "0.0.0.0", "--port", str(COMFY_PORT), "--enable-cors-header", "*"]
    print(f"Starting ComfyUI with command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
    return process

# Simple proxy to forward all requests
async def proxy_handler(request):
    # Get the part of the path after the prefix
    path = request.path
    if path.startswith(NB_PREFIX):
        path = path[len(NB_PREFIX):]
    if not path.startswith('/'):
        path = '/' + path
        
    target_url = f'http://127.0.0.1:{COMFY_PORT}{path}'
    
    # Get query parameters
    params = request.rel_url.query
    if params:
        target_url += '?' + '&'.join(f"{k}={v}" for k, v in params.items())
    
    print(f"Proxying: {request.method} {request.path} -> {target_url}")
    
    # Forward the request
    async with ClientSession() as session:
        method = request.method
        
        # Copy headers but set the Host to match what ComfyUI expects
        headers = dict(request.headers)
        headers['Host'] = f'127.0.0.1:{COMFY_PORT}'
        
        # Remove headers that might cause issues
        headers.pop('Content-Length', None)
        
        data = await request.read() if method != 'GET' else None
        
        try:
            async with session.request(
                method, 
                target_url, 
                headers=headers, 
                data=data, 
                allow_redirects=False,
                cookies=request.cookies
            ) as resp:
                # Read the response body
                body = await resp.read()
                
                # Create response with the same status code and body
                response = web.Response(
                    status=resp.status,
                    body=body
                )
                
                # Copy content type and other headers
                for key, value in resp.headers.items():
                    if key.lower() not in ('content-length', 'transfer-encoding'):
                        response.headers[key] = value
                
                return response
        except Exception as e:
            print(f"Error proxying request: {e}")
            return web.Response(status=500, text=f"Proxy error: {str(e)}")

# WebSocket proxy handler
async def websocket_proxy(request):
    from aiohttp import WSMsgType
    
    ws_path = request.path
    if ws_path.startswith(NB_PREFIX):
        ws_path = ws_path[len(NB_PREFIX):]
    if not ws_path.startswith('/'):
        ws_path = '/' + ws_path
    
    print(f"WebSocket request: {request.path} -> {ws_path}")
    
    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)
    
    try:
        async with ClientSession() as session:
            ws_url = f"ws://127.0.0.1:{COMFY_PORT}{ws_path}"
            print(f"Connecting to WebSocket: {ws_url}")
            
            async with session.ws_connect(ws_url) as ws_server:
                print("WebSocket connected")
                
                # Forward messages in both directions
                async def forward_server_to_client():
                    async for msg in ws_server:
                        if msg.type == WSMsgType.TEXT:
                            await ws_client.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_client.send_bytes(msg.data)
                        elif msg.type == WSMsgType.ERROR:
                            print(f"WebSocket error: {ws_server.exception()}")
                            break
                
                # Create task for server->client forwarding
                server_to_client = asyncio.create_task(forward_server_to_client())
                
                # Forward client->server
                async for msg in ws_client:
                    if msg.type == WSMsgType.TEXT:
                        await ws_server.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await ws_server.send_bytes(msg.data)
                    elif msg.type == WSMsgType.ERROR:
                        print(f"WebSocket error: {ws_client.exception()}")
                        break
                
                # Cancel forwarding task
                server_to_client.cancel()
                
                return ws_client
    except Exception as e:
        print(f"WebSocket proxy error: {e}")
        if not ws_client.closed:
            await ws_client.close()
        return ws_client

# Create web app with routes
app = web.Application()
app.router.add_routes([
    web.get(NB_PREFIX + '/ws', websocket_proxy),  # WebSocket endpoint with prefix
    web.get('/ws', websocket_proxy),  # WebSocket endpoint without prefix
    web.route('*', '/{path:.*}', proxy_handler),  # All other paths
    web.route('*', '/', proxy_handler)  # Root path
])

async def main():
    # Start ComfyUI with patched server
    comfyui_process = start_comfyui()
    
    # Give it a moment to start
    await asyncio.sleep(2)
    
    # Start our proxy server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8888)
    await site.start()
    
    print(f"Proxy server running at http://0.0.0.0:8888{NB_PREFIX}/")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Shutting down...")
    finally:
        if comfyui_process:
            comfyui_process.terminate()
            print("ComfyUI process terminated")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
