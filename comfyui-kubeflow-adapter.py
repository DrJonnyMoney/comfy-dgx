#!/usr/bin/env python3
"""
ComfyUI Kubeflow Adapter

This script serves as an adapter between Kubeflow's URL structure and ComfyUI.
It modifies ComfyUI's server.py to work with Kubeflow's URL prefix system.
"""

import os
import sys
import shutil
import logging
import subprocess
import re

# Setup logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComfyUI-Kubeflow")

# Get Kubeflow URL prefix (e.g., /notebook/username/server-name/)
NB_PREFIX = os.environ.get('NB_PREFIX', '')
logger.info(f"Starting ComfyUI with Kubeflow prefix: {NB_PREFIX}")

COMFY_DIR = os.path.expanduser("~/ComfyUI")

def patch_comfyui_server():
    """
    Patch ComfyUI's server.py to work with Kubeflow URL prefix
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
        
        # Inject NB_PREFIX into the server code
        patched_content = content.replace(
            "class PromptServer():",
            "class PromptServer():\n    NB_PREFIX = os.environ.get('NB_PREFIX', '')"
        )
        
        # Patch web routes to include prefix
        patched_content = patched_content.replace(
            "@routes.get('/')",
            "@routes.get(PromptServer.NB_PREFIX + '/')"
        )
        
        # Find and replace all route definitions
        patched_content = re.sub(
            r'@routes\.(get|post|put|delete)\([\'"]\/([^\'"]*)[\'"]',
            r'@routes.\1(PromptServer.NB_PREFIX + \'/\2\'',
            patched_content
        )
        
        # Fix static routes for web root
        patched_content = patched_content.replace(
            "web.static('/', self.web_root)",
            "web.static(PromptServer.NB_PREFIX + '/', self.web_root)"
        )
        
        # Fix static routes for extensions
        patched_content = patched_content.replace(
            "web.static('/extensions/' + name, dir)",
            "web.static(PromptServer.NB_PREFIX + '/extensions/' + name, dir)"
        )
        
        # Fix websocket connections
        patched_content = patched_content.replace(
            "await self.send(\"status\", { \"status\": self.get_queue_info(), 'sid': sid }, sid)",
            "await self.send(\"status\", { \"status\": self.get_queue_info(), 'sid': sid, 'prefix': PromptServer.NB_PREFIX }, sid)"
        )
        
        # Fix URL references in index.html
        for html_file in ["index.html", "index.html.bak"]:
            html_path = os.path.join(COMFY_DIR, "web", html_file)
            if os.path.exists(html_path):
                with open(html_path, 'r') as file:
                    html_content = file.read()
                
                # Fix absolute paths in HTML
                html_content = html_content.replace(
                    'href="/',
                    f'href="{NB_PREFIX}/'
                )
                html_content = html_content.replace(
                    'src="/',
                    f'src="{NB_PREFIX}/'
                )
                
                with open(html_path, 'w') as file:
                    file.write(html_content)
                logger.info(f"Patched {html_file} for Kubeflow integration")
        
        # Write patched content back
        with open(server_path, 'w') as file:
            file.write(patched_content)
        
        logger.info("Successfully patched server.py for Kubeflow integration")
        return True
    except Exception as e:
        logger.error(f"Failed to patch ComfyUI server.py: {str(e)}")
        return False

def patch_comfyui_js():
    """
    Patch ComfyUI's JavaScript files to work with Kubeflow URL prefix
    """
    try:
        # Patch main.js to handle prefix in API calls
        main_js_path = os.path.join(COMFY_DIR, "web", "scripts", "main.js")
        if os.path.exists(main_js_path):
            with open(main_js_path, 'r') as file:
                js_content = file.read()
            
            # Add prefix handling to fetch calls
            if "const prefix = '" not in js_content:
                # Inject prefix code at the beginning after the first imports
                prefix_code = """
// Kubeflow integration
const prefix = document.currentScript?.getAttribute('data-prefix') || 
               window.comfyPrefix || 
               '';

// Update API paths with prefix
const api = {};
api.apiURL = (path) => prefix + path;
                """
                
                # Replace direct API calls with prefixed ones
                js_content = js_content.replace(
                    'fetch("/',
                    'fetch(prefix + "/'
                )
                js_content = js_content.replace(
                    'fetch(\'/',
                    'fetch(prefix + \'/'
                )
                
                # Also fix WebSocket connection
                js_content = js_content.replace(
                    'const socket = new WebSocket(`ws',
                    'const socket = new WebSocket(`ws${window.location.protocol === "https:" ? "s" : ""}://${window.location.host}${prefix}/ws'
                )
                
                with open(main_js_path, 'w') as file:
                    file.write(js_content)
                
                logger.info("Patched main.js for Kubeflow integration")
        return True
    except Exception as e:
        logger.error(f"Failed to patch ComfyUI JS files: {str(e)}")
        return False

def modify_port():
    """
    Modify ComfyUI to use port 8888 instead of 8188
    """
    try:
        main_path = os.path.join(COMFY_DIR, "main.py")
        with open(main_path, 'r') as file:
            content = file.read()
        
        # Change default port
        modified_content = content.replace(
            'parser.add_argument("--port", type=int, default=8188,',
            'parser.add_argument("--port", type=int, default=8888,'
        )
        
        with open(main_path, 'w') as file:
            file.write(modified_content)
        
        logger.info("Modified main.py to use port 8888")
        return True
    except Exception as e:
        logger.error(f"Failed to modify port in main.py: {str(e)}")
        return False

def start_comfyui():
    """
    Start ComfyUI after patching
    """
    try:
        # Change to ComfyUI directory
        os.chdir(COMFY_DIR)
        
        # Start ComfyUI with modified parameters
        cmd = [sys.executable, "main.py", "--listen", "0.0.0.0"]
        
        logger.info(f"Starting ComfyUI with command: {' '.join(cmd)}")
        
        # Use subprocess to keep running in foreground
        process = subprocess.run(cmd)
        
        return process.returncode == 0
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
    
    if not patch_comfyui_js():
        logger.warning("Failed to patch ComfyUI JavaScript files")
        # Continue anyway, might still work
    
    if not modify_port():
        logger.warning("Failed to modify port in main.py")
        # Continue anyway, might still work with arguments
    
    # Start ComfyUI
    if not start_comfyui():
        logger.error("Failed to start ComfyUI")
        sys.exit(1)
