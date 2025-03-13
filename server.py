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
        headers = {key: value for key, value in request.headers.items() 
                  if key.lower() not in ('host', 'content-length')}
        data = await request.read() if method != 'GET' else None
        
        async with session.request(method, target_url, headers=headers, data=data) as resp:
            # Create response
            response = web.Response(
                status=resp.status,
                body=await resp.read(),
                content_type=resp.content_type
            )
            
            # Copy headers
            for key, value in resp.headers.items():
                if key.lower() not in ('content-length', 'content-encoding', 'transfer-encoding'):
                    response.headers[key] = value
            
            return response

# Add the catch-all route
app.add_routes([web.route('*', '{path:.*}', proxy_handler)])

async def main():
    # Start ComfyUI
    process = await start_comfyui()
    
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
