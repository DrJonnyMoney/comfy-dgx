#!/usr/bin/env python3
"""
ComfyUI starter script for Kubeflow integration.
This script patches ComfyUI to work with Kubeflow's URL prefix system
and ensures it runs on port 8888 instead of the default 8188.
"""

import os
import sys
import importlib.util
import logging
import subprocess
import shutil

# Setup logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComfyUI-Kubeflow")

# Get Kubeflow URL prefix (e.g., /notebook/username/server-name/)
NB_PREFIX = os.environ.get('NB_PREFIX', '')
logger.info(f"Starting ComfyUI with Kubeflow prefix: {NB_PREFIX}")

def patch_comfyui_for_kubeflow():
    """
    Patch ComfyUI server.py to work with Kubeflow URL prefix
    """
    try:
        # Backup original server.py if not already backed up
        server_path = os.path.join(os.path.dirname(__file__), "server.py")
        backup_path = os.path.join(os.path.dirname(__file__), "server.py.original")
        
        if not os.path.exists(backup_path):
            logger.info("Creating backup of original server.py")
            shutil.copy2(server_path, backup_path)
        
        # Load server.py content
        with open(server_path, 'r') as file:
            content = file.read()
        
        # Check if already patched
        if "NB_PREFIX = os.environ.get('NB_PREFIX', '')" in content:
            logger.info("server.py already patched for Kubeflow")
            return
        
        # Add NB_PREFIX to the server.py file to handle Kubeflow URL prefixing
        patched_content = content.replace(
            "app = web.Application()",
            """# Kubeflow integration
NB_PREFIX = os.environ.get('NB_PREFIX', '')
app = web.Application()
# Configure routes with Kubeflow prefix
"""
        )
        
        # Update route registration to include NB_PREFIX
        patched_content = patched_content.replace(
            "app.router.add_get('/", 
            "app.router.add_get(NB_PREFIX + '/"
        )
        patched_content = patched_content.replace(
            "app.router.add_post('/", 
            "app.router.add_post(NB_PREFIX + '/"
        )
        patched_content = patched_content.replace(
            "app.router.add_static('/", 
            "app.router.add_static(NB_PREFIX + '/"
        )
        
        # Write patched content back
        with open(server_path, 'w') as file:
            file.write(patched_content)
        
        logger.info("Successfully patched server.py for Kubeflow integration")
    except Exception as e:
        logger.error(f"Failed to patch ComfyUI server.py: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # Patch ComfyUI for Kubeflow
    patch_comfyui_for_kubeflow()
    
    # Start ComfyUI with modified arguments
    # Use port 8888 (Kubeflow default) instead of 8188 (ComfyUI default)
    # And listen on all interfaces
    cmd = [sys.executable, "main.py", "--port", "8888", "--listen", "0.0.0.0"]
    
    # Execute ComfyUI
    logger.info(f"Starting ComfyUI with command: {' '.join(cmd)}")
    subprocess.run(cmd)
