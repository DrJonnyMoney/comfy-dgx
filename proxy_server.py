import os
import sys
import asyncio
import subprocess
import time
import logging
from aiohttp import web, ClientSession, WSMsgType

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("comfyui-proxy")

# Configuration
NB_PREFIX = os.environ.get('NB_PREFIX', '')
COMFY_PORT = 8188
PROXY_PORT = 8888
MAX_REQUEST_SIZE = 1024 * 1024 * 1024  # 1GB
HTTP_TIMEOUT = 600  # 10 minutes
STARTUP_TIMEOUT = 60  # Max seconds to wait for ComfyUI to start
HEARTBEAT_INTERVAL = 30  # WebSocket heartbeat interval in seconds
comfyui_process = None

# Common path normalization function
def normalize_path(path):
    """Normalize path by removing prefix and ensuring it starts with a slash"""
    if path.startswith(NB_PREFIX):
        path = path[len(NB_PREFIX):]
    if not path.startswith('/'):
        path = '/' + path
    return path

# Start ComfyUI as a subprocess
def start_comfyui():
    cmd = [
        sys.executable, 
        "main.py", 
        "--listen", "0.0.0.0", 
        "--port", str(COMFY_PORT), 
        "--enable-cors-header", "*"
    ]
    logger.info(f"Starting ComfyUI with command: {' '.join(cmd)}")
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)

# Check if ComfyUI is responding
async def is_comfyui_ready():
    """Check if ComfyUI is up and responding to requests"""
    try:
        async with ClientSession() as session:
            async with session.get(f'http://127.0.0.1:{COMFY_PORT}/', timeout=2) as resp:
                return resp.status < 500
    except:
        return False

# Proxy handler for HTTP requests
async def proxy_handler(request):
    # Normalize the path
    path = normalize_path(request.path)
    target_url = f'http://127.0.0.1:{COMFY_PORT}{path}'
    
    # Add query parameters if present
    params = request.rel_url.query
    if params:
        target_url += '?' + '&'.join(f"{k}={v}" for k, v in params.items())
    
    logger.debug(f"Proxying: {request.method} {request.path} -> {target_url}")
    
    # Forward the request
    async with ClientSession() as session:
        # Copy headers but set the Host to match what ComfyUI expects
        headers = dict(request.headers)
        headers['Host'] = f'127.0.0.1:{COMFY_PORT}'
        
        # Remove headers that might cause issues
        headers.pop('Content-Length', None)
        
        # Read request data if not a GET request
        data = await request.read() if request.method != 'GET' else None
        
        try:
            async with session.request(
                request.method, 
                target_url, 
                headers=headers, 
                data=data, 
                allow_redirects=False,
                cookies=request.cookies,
                timeout=HTTP_TIMEOUT
            ) as resp:
                # Read the response body
                body = await resp.read()
                
                # Create response with the same status code and body
                response = web.Response(
                    status=resp.status,
                    body=body
                )
                
                # Copy relevant headers from the response
                for key, value in resp.headers.items():
                    if key.lower() not in ('content-length', 'transfer-encoding'):
                        response.headers[key] = value
                
                return response
        except Exception as e:
            error_msg = f"Proxy error: {str(e)}"
            logger.error(error_msg)
            
            # Return appropriate error response based on Accept header
            if 'application/json' in request.headers.get('Accept', ''):
                return web.json_response({"error": error_msg}, status=500)
            else:
                return web.Response(status=500, text=error_msg)

# WebSocket proxy handler
async def websocket_proxy(request):
    # Normalize the path
    ws_path = normalize_path(request.path)
    ws_url = f"ws://127.0.0.1:{COMFY_PORT}{ws_path}"
    
    logger.debug(f"WebSocket request: {request.path} -> {ws_url}")
    
    # Prepare client WebSocket
    ws_client = web.WebSocketResponse(heartbeat=HEARTBEAT_INTERVAL)
    await ws_client.prepare(request)
    
    # Two tasks for bidirectional communication
    client_to_server_task = None
    server_to_client_task = None
    
    try:
        async with ClientSession() as session:
            logger.debug(f"Connecting to WebSocket: {ws_url}")
            
            async with session.ws_connect(
                ws_url, 
                timeout=60, 
                heartbeat=HEARTBEAT_INTERVAL
            ) as ws_server:
                logger.debug("WebSocket connected")
                
                # Server to client message forwarding
                async def forward_server_to_client():
                    try:
                        async for msg in ws_server:
                            if msg.type == WSMsgType.TEXT:
                                await ws_client.send_str(msg.data)
                            elif msg.type == WSMsgType.BINARY:
                                await ws_client.send_bytes(msg.data)
                            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                                break
                    except Exception as e:
                        logger.error(f"Error forwarding server to client: {e}")
                
                # Client to server message forwarding
                async def forward_client_to_server():
                    try:
                        async for msg in ws_client:
                            if msg.type == WSMsgType.TEXT:
                                await ws_server.send_str(msg.data)
                            elif msg.type == WSMsgType.BINARY:
                                await ws_server.send_bytes(msg.data)
                            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                                break
                    except Exception as e:
                        logger.error(f"Error forwarding client to server: {e}")
                
                # Start both forwarding tasks
                server_to_client_task = asyncio.create_task(forward_server_to_client())
                client_to_server_task = asyncio.create_task(forward_client_to_server())
                
                # Wait until either task completes (meaning a connection closed)
                done, pending = await asyncio.wait(
                    [server_to_client_task, client_to_server_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel the pending task
                for task in pending:
                    task.cancel()
                
    except Exception as e:
        logger.error(f"WebSocket proxy error: {e}")
    finally:
        # Clean up tasks if they exist and weren't already cancelled
        for task in [client_to_server_task, server_to_client_task]:
            if task and not task.done():
                task.cancel()
        
        # Make sure the client WebSocket is closed
        if not ws_client.closed:
            await ws_client.close()
    
    return ws_client

# Monitor ComfyUI health and restart if needed
async def health_monitor():
    global comfyui_process
    
    while True:
        # Check if process is still running
        if comfyui_process.poll() is not None:
            logger.warning("ComfyUI process died, restarting...")
            comfyui_process = start_comfyui()
        
        # Sleep for 30 seconds between checks
        await asyncio.sleep(30)

async def main():
    global comfyui_process
    
    # Start ComfyUI
    comfyui_process = start_comfyui()
    
    # Wait for ComfyUI to start by polling
    logger.info("Waiting for ComfyUI to start...")
    start_time = time.time()
    while not await is_comfyui_ready():
        if time.time() - start_time > STARTUP_TIMEOUT:
            logger.error(f"ComfyUI failed to start within {STARTUP_TIMEOUT} seconds")
            comfyui_process.terminate()
            sys.exit(1)
        await asyncio.sleep(1)
    
    logger.info("ComfyUI started successfully")
    
    # Create and start health monitor
    health_task = asyncio.create_task(health_monitor())
    
    # Create app with routes
    app = web.Application(client_max_size=MAX_REQUEST_SIZE)
    
    # Set up routes - only need one of each with catch-all patterns
    app.router.add_routes([
        web.get(NB_PREFIX + '/ws', websocket_proxy),
        web.get('/ws', websocket_proxy),
        web.route('*', '/{path:.*}', proxy_handler),
    ])
    
    # Start the proxy server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PROXY_PORT)
    await site.start()
    
    logger.info(f"Proxy server running at http://0.0.0.0:{PROXY_PORT}{NB_PREFIX}/")
    
    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        # Clean up
        health_task.cancel()
        
        if comfyui_process:
            comfyui_process.terminate()
            try:
                # Wait for process to terminate gracefully
                comfyui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't terminate in time
                comfyui_process.kill()
            
            logger.info("ComfyUI process terminated")
        
        # Clean up the web server
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user, shutting down")
