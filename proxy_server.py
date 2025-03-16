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
comfyui_process = None

# Start ComfyUI as a subprocess with patched server
def start_comfyui():
    global comfyui_process
    
    # Start ComfyUI with appropriate arguments and increased timeout for large models
    cmd = [
        sys.executable, 
        "main.py", 
        "--listen", "0.0.0.0", 
        "--port", str(COMFY_PORT), 
        "--enable-cors-header", "*"
    ]
    print(f"Starting ComfyUI with command: {' '.join(cmd)}")
    
    comfyui_process = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
    return comfyui_process

# Simple proxy to forward all requests with increased timeouts
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
    
    # Forward the request with increased timeout
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
                cookies=request.cookies,
                timeout=600  # 10 minute timeout for large model operations
            ) as resp:
                # Read the response body with a large timeout
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
            error_msg = f"Proxy error: {str(e)}"
            print(error_msg)
            
            # Check content-type of the original request
            accept_header = request.headers.get('Accept', '')
            
            # If the client expects JSON, return JSON error
            if 'application/json' in accept_header:
                return web.json_response({"error": error_msg}, status=500)
            else:
                # Otherwise return plain text
                return web.Response(status=500, text=error_msg)

# WebSocket proxy handler with increased timeout
async def websocket_proxy(request):
    from aiohttp import WSMsgType
    
    ws_path = request.path
    if ws_path.startswith(NB_PREFIX):
        ws_path = ws_path[len(NB_PREFIX):]
    if not ws_path.startswith('/'):
        ws_path = '/' + ws_path
    
    print(f"WebSocket request: {request.path} -> {ws_path}")
    
    ws_client = web.WebSocketResponse(heartbeat=30)  # Add heartbeat to keep connection alive
    await ws_client.prepare(request)
    
    try:
        async with ClientSession() as session:
            ws_url = f"ws://127.0.0.1:{COMFY_PORT}{ws_path}"
            print(f"Connecting to WebSocket: {ws_url}")
            
            async with session.ws_connect(ws_url, timeout=60, heartbeat=30) as ws_server:  # Increased timeout and heartbeat
                print("WebSocket connected")
                
                # Forward messages in both directions
                async def forward_server_to_client():
                    try:
                        async for msg in ws_server:
                            if msg.type == WSMsgType.TEXT:
                                await ws_client.send_str(msg.data)
                            elif msg.type == WSMsgType.BINARY:
                                await ws_client.send_bytes(msg.data)
                            elif msg.type == WSMsgType.ERROR:
                                print(f"WebSocket error: {ws_server.exception()}")
                                break
                    except Exception as e:
                        print(f"Error forwarding server to client: {e}")
                        if not ws_client.closed:
                            await ws_client.close()
                
                # Create task for server->client forwarding
                server_to_client = asyncio.create_task(forward_server_to_client())
                
                # Forward client->server
                try:
                    async for msg in ws_client:
                        if msg.type == WSMsgType.TEXT:
                            await ws_server.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_server.send_bytes(msg.data)
                        elif msg.type == WSMsgType.ERROR:
                            print(f"WebSocket error: {ws_client.exception()}")
                            break
                except Exception as e:
                    print(f"Error forwarding client to server: {e}")
                    if not ws_server.closed:
                        await ws_server.close()
                finally:
                    # Cancel forwarding task
                    server_to_client.cancel()
                
                return ws_client
    except Exception as e:
        print(f"WebSocket proxy error: {e}")
        if not ws_client.closed:
            await ws_client.close()
        return ws_client

# Create web app with routes
app = web.Application(client_max_size=1024*1024*1024)  # 1GB max request size
app.router.add_routes([
    web.get(NB_PREFIX + '/ws', websocket_proxy),
    web.get('/ws', websocket_proxy),
    web.route('*', '/{path:.*}', proxy_handler),
    web.route('*', '/', proxy_handler)
])

async def main():
    global comfyui_process
    
    # Start ComfyUI
    comfyui_process = start_comfyui()
    
    # Give ComfyUI time to start
    print("Waiting for ComfyUI to start...")
    await asyncio.sleep(30)  # Increased wait time for large models
    
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
