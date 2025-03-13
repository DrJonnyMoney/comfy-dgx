import os
import sys
import asyncio
from aiohttp import web, ClientSession

# Get Kubeflow URL prefix
NB_PREFIX = os.environ.get('NB_PREFIX', '')
print(f"Using prefix: {NB_PREFIX}")

# Create app
app = web.Application()

# Proxy settings
COMFY_PORT = 8188  # Default ComfyUI port

# Start ComfyUI in a background process
async def start_comfyui():
    import subprocess
    process = subprocess.Popen(
        [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", str(COMFY_PORT)],
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    return process

# Simple proxy to forward all request
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
        
        # Preserve more headers, including Origin, Referer, and cookies
        headers = dict(request.headers)
        
        # Remove problematic headers
        headers.pop('Host', None)
        headers.pop('Content-Length', None)
        
        # Set a proper Referer for static assets if missing
        if path.endswith(('.js', '.css', '.png', '.jpg', '.svg')) and 'Referer' not in headers:
            headers['Referer'] = f'http://127.0.0.1:{COMFY_PORT}/'
        
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
                
                # Debug output for 403 errors
                if resp.status == 403:
                    print(f"403 Error for {path}")
                    print(f"Request headers: {headers}")
                    print(f"Response headers: {resp.headers}")
                
                return response
        except Exception as e:
            print(f"Error proxying request: {e}")
            return web.Response(status=500, text=f"Proxy error: {str(e)}")
            
# WebSocket proxy handler
async def websocket_proxy(request):
    from aiohttp import WSMsgType
    
    # Create WebSocket connection to client
    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)
    
    # Get path for ComfyUI WebSocket
    path = request.path
    if path.startswith(NB_PREFIX):
        path = path[len(NB_PREFIX):]
    if not path.startswith('/'):
        path = '/' + path
    
    # Connect to ComfyUI WebSocket
    try:
        async with ClientSession() as session:
            ws_url = f"ws://127.0.0.1:{COMFY_PORT}{path}"
            print(f"WebSocket connecting to: {ws_url}")
            
            async with session.ws_connect(ws_url) as ws_server:
                print(f"WebSocket connected")
                
                # Create background task for server->client messages
                async def forward_server_to_client():
                    async for msg in ws_server:
                        if msg.type == WSMsgType.TEXT:
                            await ws_client.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_client.send_bytes(msg.data)
                        elif msg.type == WSMsgType.CLOSED:
                            break
                
                # Create task for the background forwarding
                server_to_client = asyncio.create_task(forward_server_to_client())
                
                # Handle client->server messages
                async for msg in ws_client:
                    if msg.type == WSMsgType.TEXT:
                        await ws_server.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await ws_server.send_bytes(msg.data)
                    elif msg.type == WSMsgType.CLOSED:
                        break
                
                # Cancel the background task
                server_to_client.cancel()
                
                return ws_client
    except Exception as e:
        print(f"WebSocket error: {e}")
        if not ws_client.closed:
            await ws_client.close()
        return ws_client

# Add routes
app.router.add_routes([
    web.get('/ws', websocket_proxy),  # Handle root WebSocket
    web.get(NB_PREFIX + '/ws', websocket_proxy),  # Handle WebSocket with prefix
    web.route('*', '/{path:.*}', proxy_handler),  # Handle everything else
    web.route('*', '/', proxy_handler)  # Handle root path
])

async def main():
    # Start ComfyUI
    process = await start_comfyui()
    print("Started ComfyUI process")
    
    # Give ComfyUI a moment to start
    await asyncio.sleep(2)
    
    # Start the proxy server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8888)
    await site.start()
    
    print(f"Proxy server running at http://0.0.0.0:8888/")
    
    # Keep the server running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
