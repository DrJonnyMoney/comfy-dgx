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
import re

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
    Carefully handles indentation to avoid Python syntax errors.
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
        
        # Read original content
        with open(server_path, 'r') as file:
            content = file.read()
        
        # Add NB_PREFIX as a global variable at the top of the file
        if "NB_PREFIX = os.environ.get('NB_PREFIX', '')" not in content:
            content = content.replace(
                "import os\nimport sys\nimport asyncio\nimport traceback",
                "import os\nimport sys\nimport asyncio\nimport traceback\n\n# Kubeflow integration\nNB_PREFIX = os.environ.get('NB_PREFIX', '')"
            )
        
        # We'll use more precise pattern matching with line-based replacements to avoid indentation issues
        lines = content.split('\n')
        new_lines = []
        
        # Process the file line by line
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Disable the origin_only_middleware
            if "middlewares.append(create_origin_only_middleware())" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}# Disabled for Kubeflow compatibility")
                new_lines.append(f"{indent}# middlewares.append(create_origin_only_middleware())")
                i += 1
                continue
                
            # Fix the CORS middleware
            elif "if args.enable_cors_header:" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}# Always enable CORS for Kubeflow")
                new_lines.append(f"{indent}if True:")
                i += 1
                continue
                
            # Replace routes with prefixed versions
            elif re.match(r"@routes\.(get|post)\(['\"]/(.*?)['\"]\)", line):
                route_type = re.search(r"@routes\.(get|post)", line).group(1)
                route_path = re.search(r"['\"]/(.*?)['\"]", line).group(0)
                indent = line[:len(line) - len(line.lstrip())]
                
                # Special handling for routes with parameters
                if "{" in route_path:
                    route_path_escaped = route_path.replace("{", "{{").replace("}", "}}")
                    new_line = f"{indent}@routes.{route_type}(NB_PREFIX + {route_path_escaped})"
                else:
                    new_line = f"{indent}@routes.{route_type}(NB_PREFIX + {route_path})"
                    
                new_lines.append(new_line)
                i += 1
                continue
                
            # Fix static routes
            elif "web.static('/', self.web_root)" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}web.static(NB_PREFIX + '/', self.web_root)")
                i += 1
                continue
                
            elif "web.static('/extensions/' + name, dir)" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}web.static(NB_PREFIX + '/extensions/' + name, dir)")
                i += 1
                continue
                
            # Disable host validation check
            elif "if host_domain != origin_domain:" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}if False:  # Disabled for Kubeflow compatibility")
                i += 1
                continue
                
            # Add prefix to websocket response
            elif "await self.send(\"status\", { \"status\": self.get_queue_info(), 'sid': sid }, sid)" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}await self.send(\"status\", {{ \"status\": self.get_queue_info(), 'sid': sid, 'prefix': NB_PREFIX }}, sid)")
                i += 1
                continue
                
            # Fix the log message
            elif "logging.info(\"To see the GUI go to: {}://{}:{}\".format(scheme, address_print, port))" in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}logging.info(\"To see the GUI go to Kubeflow UI and open the notebook server with prefix: \" + NB_PREFIX)")
                i += 1
                continue
                
            # Keep the line as is
            else:
                new_lines.append(line)
                i += 1
        
        # Write the patched content back to the file
        with open(server_path, 'w') as file:
            file.write('\n'.join(new_lines))
        
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
    
    # Start ComfyUI with explicit port and security settings
    start_comfyui()
    # If we get here, something went wrong
    logger.error("Failed to start ComfyUI")
    sys.exit(1)
