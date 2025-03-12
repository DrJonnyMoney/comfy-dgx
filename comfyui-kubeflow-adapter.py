#!/usr/bin/env python3
"""
ComfyUI Kubeflow Adapter with specific fix for else statement indentation

This script serves as an adapter between Kubeflow's URL structure and ComfyUI.
It modifies ComfyUI's server.py to work with Kubeflow's URL prefix system.
"""

import os
import sys
import shutil
import logging
import re
import time

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
            time.sleep(0.5)  # Give time for the file system to process
        
        # Process the file line by line to ensure indentation is correct
        with open(server_path, 'r') as file:
            lines = file.readlines()
        
        # Add NB_PREFIX variable at the top of the file
        for i, line in enumerate(lines):
            if line.strip() == 'import os':
                lines.insert(i + 4, '\n# Kubeflow integration\nNB_PREFIX = os.environ.get(\'NB_PREFIX\', \'\')\n')
                break
        
        # Patch routes and other elements
        for i, line in enumerate(lines):
            # Route patching
            route_match = re.match(r'(\s*)@routes\.(get|post)\([\'"]/(.*?)[\'"]\)', line)
            if route_match:
                indent, method, path = route_match.groups()
                if '{' in path:  # Handle routes with parameters
                    new_path = path.replace('{', '{{').replace('}', '}}')
                    lines[i] = f"{indent}@routes.{method}(NB_PREFIX + '/{new_path}')\n"
                else:
                    lines[i] = f"{indent}@routes.{method}(NB_PREFIX + '/{path}')\n"
            
            # Fix static routes
            elif "web.static('/', self.web_root)" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}web.static(NB_PREFIX + '/', self.web_root)\n"
            
            elif "web.static('/extensions/' + name, dir)" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}web.static(NB_PREFIX + '/extensions/' + name, dir)\n"
            
            # Disable host validation without changing indentation structure
            elif "if host_domain != origin_domain:" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}if False:  # Disabled for Kubeflow compat - host_domain != origin_domain\n"
            
            # CORS middleware - ensure if/else structure is preserved
            elif "if args.enable_cors_header:" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}if True:  # Always enable CORS for Kubeflow\n"
            
            # Disable origin_only_middleware without affecting structure
            elif "middlewares.append(create_origin_only_middleware())" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}# middlewares.append(create_origin_only_middleware())  # Disabled for Kubeflow\n"
            
            # Update WebSocket response
            elif "await self.send(\"status\", { \"status\": self.get_queue_info(), 'sid': sid }, sid)" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}await self.send(\"status\", {{ \"status\": self.get_queue_info(), 'sid': sid, 'prefix': NB_PREFIX }}, sid)\n"
            
            # Update log message
            elif "logging.info(\"To see the GUI go to:" in line:
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}logging.info(\"To see the GUI go to Kubeflow UI and open the notebook server with prefix: \" + NB_PREFIX)\n"
        
        # Save the patched file
        with open(server_path, 'w') as file:
            file.writelines(lines)
        
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
        os.execv(sys.executable, [sys.executable] + cmd[1:])
        
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
    
    if not modify_port():
        logger.warning("Failed to modify port in main.py")
        # Continue anyway as we'll specify port on command line
    
    # Start ComfyUI with explicit port and security settings
    start_comfyui()
    # If we get here, something went wrong
    logger.error("Failed to start ComfyUI")
    sys.exit(1)
