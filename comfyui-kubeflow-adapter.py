#!/usr/bin/env python3
"""
ComfyUI Kubeflow Adapter

This script serves as an adapter between Kubeflow's URL structure and ComfyUI.
It modifies ComfyUI's server.py to work with Kubeflow's URL prefix system
and addresses security restrictions.
"""

import os
import sys
import shutil
import logging
import subprocess

# Setup logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComfyUI-Kubeflow")

# Get Kubeflow URL prefix (e.g., /notebook/username/server-name/)
NB_PREFIX = os.environ.get('NB_PREFIX', '')
logger.info(f"Starting ComfyUI with Kubeflow prefix: {NB_PREFIX}")

COMFY_DIR = os.path.expanduser("~/ComfyUI")
KUBEFLOW_PORT = 8888  # Kubeflow uses 8888

def patch_comfyui_server():
    """
    Patch ComfyUI's server.py to work with Kubeflow URL prefix and security settings
    """
    try:
        server_path = os.path.join(COMFY_DIR, "server.py")
        backup_path = os.path.join(COMFY_DIR, "server.py.original")
        
        if not os.path.exists(backup_path):
            logger.info("Creating backup of original server.py")
            shutil.copy2(server_path, backup_path)
        else:
            # Reset to original for clean patching
            logger.info("Restoring original server.py for clean patching")
            shutil.copy2(backup_path, server_path)
        
        with open(server_path, 'r') as file:
            content = file.read()
        
        # Add NB_PREFIX as a global variable at the top of the file
        if "NB_PREFIX = os.environ.get('NB_PREFIX', '')" not in content:
            content = "import os\nimport sys\nimport asyncio\nimport traceback\n\n# Kubeflow integration\nNB_PREFIX = os.environ.get('NB_PREFIX', '')\n" + content[content.find("import os\n") + len("import os\n"):]
        
        # Modify CORS settings to be more permissive - Important for Kubeflow
        if "create_cors_middleware" in content:
            # Enable CORS for all origins in ComfyUI
            content = content.replace(
                "def create_cors_middleware(allowed_origin: str):",
                "def create_cors_middleware(allowed_origin: str = '*'):"
            )
            
            # Ensure CORS middleware is always added
            content = content.replace(
                "if args.enable_cors_header:",
                "# Always enable CORS for Kubeflow\nif True:"
            )
            
            # Disable the origin_only_middleware which can block Kubeflow requests
            content = content.replace(
                "middlewares.append(create_origin_only_middleware())",
                "# Disabled for Kubeflow compatibility\n            # middlewares.append(create_origin_only_middleware())"
            )
        
        # Patch routes one by one manually
        replacements = [
            ("@routes.get('/ws')", f"@routes.get(NB_PREFIX + '/ws')"),
            ("@routes.get('/')", f"@routes.get(NB_PREFIX + '/')"),
            ("@routes.get('/embeddings')", f"@routes.get(NB_PREFIX + '/embeddings')"),
            ("@routes.get('/models')", f"@routes.get(NB_PREFIX + '/models')"),
            ("@routes.get('/models/{folder}')", f"@routes.get(NB_PREFIX + '/models/{{folder}}')"),
            ("@routes.get('/extensions')", f"@routes.get(NB_PREFIX + '/extensions')"),
            ("@routes.post('/upload/image')", f"@routes.post(NB_PREFIX + '/upload/image')"),
            ("@routes.post('/upload/mask')", f"@routes.post(NB_PREFIX + '/upload/mask')"),
            ("@routes.get('/view')", f"@routes.get(NB_PREFIX + '/view')"),
            ("@routes.get('/view_metadata/{folder_name}')", f"@routes.get(NB_PREFIX + '/view_metadata/{{folder_name}}')"),
            ("@routes.get('/system_stats')", f"@routes.get(NB_PREFIX + '/system_stats')"),
            ("@routes.get('/prompt')", f"@routes.get(NB_PREFIX + '/prompt')"),
            ("@routes.get('/object_info')", f"@routes.get(NB_PREFIX + '/object_info')"),
            ("@routes.get('/object_info/{node_class}')", f"@routes.get(NB_PREFIX + '/object_info/{{node_class}}')"),
            ("@routes.get('/history')", f"@routes.get(NB_PREFIX + '/history')"),
            ("@routes.get('/history/{prompt_id}')", f"@routes.get(NB_PREFIX + '/history/{{prompt_id}}')"),
            ("@routes.get('/queue')", f"@routes.get(NB_PREFIX + '/queue')"),
            ("@routes.post('/prompt')", f"@routes.post(NB_PREFIX + '/prompt')"),
            ("@routes.post('/queue')", f"@routes.post(NB_PREFIX + '/queue')"),
            ("@routes.post('/interrupt')", f"@routes.post(NB_PREFIX + '/interrupt')"),
            ("@routes.post('/free')", f"@routes.post(NB_PREFIX + '/free')"),
            ("@routes.post('/history')", f"@routes.post(NB_PREFIX + '/history')")
        ]
        
        for old, new in replacements:
            content = content.replace(old, new)
        
        # Fix static routes
        content = content.replace(
            "web.static('/', self.web_root)",
            f"web.static(NB_PREFIX + '/', self.web_root)"
        )
        
        content = content.replace(
            "web.static('/extensions/' + name, dir)",
            f"web.static(NB_PREFIX + '/extensions/' + name, dir)"
        )
        
        # Add prefix to websocket response
        content = content.replace(
            "await self.send(\"status\", { \"status\": self.get_queue_info(), 'sid': sid }, sid)",
            "await self.send(\"status\", { \"status\": self.get_queue_info(), 'sid': sid, 'prefix': NB_PREFIX }, sid)"
        )
        
        # Fix the address print line for the log message
        content = content.replace(
            'logging.info("To see the GUI go to: {}://{}:{}".format(scheme, address_print, port))',
            f'logging.info("To see the GUI go to Kubeflow UI and open the notebook server with prefix: " + NB_PREFIX)'
        )
        
        # Disable Host validation - critical for Kubeflow proxy
        if "host_domain != origin_domain" in content:
            content = content.replace(
                "if host_domain != origin_domain:",
                "if False and host_domain != origin_domain:  # Disabled for Kubeflow compatibility"
            )
        
        # Write patched content back
        with open(server_path, 'w') as file:
            file.write(content)
        
        # Patch index.html to include prefix
        index_path = os.path.join(COMFY_DIR, "web", "index.html")
        if os.path.exists(index_path):
            with open(index_path, 'r') as file:
                html_content = file.read()
            
            # Add base URL prefix to script and link tags
            html_content = html_content.replace('src="scripts/', f'src="{NB_PREFIX}/scripts/')
            html_content = html_content.replace('href="style.css', f'href="{NB_PREFIX}/style.css')
            
            # Add script to set global prefix
            html_content = html_content.replace('</head>', f'<script>window.comfyPrefix = "{NB_PREFIX}";</script></head>')
            
            with open(index_path, 'w') as file:
                file.write(html_content)
            logger.info("Patched index.html for Kubeflow integration")
        
        # Patch main.js for WebSocket connection
        main_js_path = os.path.join(COMFY_DIR, "web", "scripts", "main.js")
        if os.path.exists(main_js_path):
            with open(main_js_path, 'r') as file:
                js_content = file.read()
            
            # Fix WebSocket URL
            if "const socket = new WebSocket(" in js_content:
                js_content = js_content.replace(
                    "const socket = new WebSocket(",
                    "const prefix = window.comfyPrefix || '';\n\tconst socket = new WebSocket("
                )
                js_content = js_content.replace(
                    "const socket = new WebSocket(`ws${location.protocol === 'https:' ? 's' : ''}://${location.host}/ws",
                    "const socket = new WebSocket(`ws${location.protocol === 'https:' ? 's' : ''}://${location.host}${prefix}/ws"
                )
            
            with open(main_js_path, 'w') as file:
                file.write(js_content)
            logger.info("Patched main.js for WebSocket connections")
        
        logger.info("Successfully patched server.py for Kubeflow integration")
        return True
    except Exception as e:
        logger.error(f"Failed to patch ComfyUI server.py: {str(e)}")
        return False

def start_comfyui():
    """
    Start ComfyUI after patching
    """
    try:
        # Change to ComfyUI directory
        os.chdir(COMFY_DIR)
        
        # Start ComfyUI with explicit port parameter and disable security checks
        cmd = [
            sys.executable, 
            "main.py", 
            "--listen", "0.0.0.0", 
            "--port", str(KUBEFLOW_PORT),
            "--enable-cors-header", "*"  # Enable CORS for all origins
        ]
        
        logger.info(f"Starting ComfyUI with command: {' '.join(cmd)}")
        
        # Execute ComfyUI directly (this will replace the current process)
        os.execv(sys.executable, [sys.executable] + ["main.py", "--listen", "0.0.0.0", "--port", str(KUBEFLOW_PORT), "--enable-cors-header", "*"])
        
        # This line will never be reached because execv replaces the current process
        return True
    except Exception as e:
        logger.error(f"Failed to start ComfyUI: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Starting ComfyUI Kubeflow Adapter")
    
    # Ensure ComfyUI directory exists
    if not os.path.exists(COMFY_DIR):
        logger.error(f"ComfyUI directory not found at {COMFY_DIR}")
        sys.exit(1)
    
    # Patch ComfyUI components
    if not patch_comfyui_server():
        logger.error("Failed to patch ComfyUI server")
        sys.exit(1)
    
    # Start ComfyUI with explicit port and security settings
    start_comfyui()
    # If we get here, something went wrong
    logger.error("Failed to start ComfyUI")
    sys.exit(1)
