# Use the Kubeflow Code-Server Python image
FROM kubeflownotebookswg/codeserver-python:latest

# Switch to root to make modifications
USER root

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    curl \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Clone ComfyUI repository to tmp_home (which will be copied to home at runtime)
RUN mkdir -p /tmp_home/jovyan/ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /tmp_home/jovyan/ComfyUI
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI

# Create models directory structure
RUN mkdir -p /tmp_home/jovyan/ComfyUI/models/checkpoints \
    /tmp_home/jovyan/ComfyUI/models/clip \
    /tmp_home/jovyan/ComfyUI/models/clip_vision \
    /tmp_home/jovyan/ComfyUI/models/controlnet \
    /tmp_home/jovyan/ComfyUI/models/diffusers \
    /tmp_home/jovyan/ComfyUI/models/embeddings \
    /tmp_home/jovyan/ComfyUI/models/gligen \
    /tmp_home/jovyan/ComfyUI/models/hypernetworks \
    /tmp_home/jovyan/ComfyUI/models/ipadapter \
    /tmp_home/jovyan/ComfyUI/models/loras \
    /tmp_home/jovyan/ComfyUI/models/style_models \
    /tmp_home/jovyan/ComfyUI/models/unet \
    /tmp_home/jovyan/ComfyUI/models/upscale_models \
    /tmp_home/jovyan/ComfyUI/models/vae \
    /tmp_home/jovyan/ComfyUI/input \
    /tmp_home/jovyan/ComfyUI/output
    
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI/models
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI/input
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI/output

# Install PyTorch with CUDA support and ComfyUI requirements
RUN pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu124
WORKDIR /tmp_home/jovyan/ComfyUI
RUN pip install -r requirements.txt

# Install additional packages for the proxy server
RUN pip install aiohttp

# Copy the proxy server script
COPY proxy_server.py /tmp_home/jovyan/ComfyUI/
RUN chown ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI/proxy_server.py

# Remove the code-server service to prevent it from starting
RUN rm -f /etc/services.d/code-server/run || true

# Create comfyui service directory
RUN mkdir -p /etc/services.d/comfyui

# Copy the run script for the ComfyUI service
COPY comfyui-run /etc/services.d/comfyui/run
RUN chmod 755 /etc/services.d/comfyui/run && \
    chown ${NB_USER}:${NB_GID} /etc/services.d/comfyui/run

# Expose port 8888
EXPOSE 8888

# Switch back to non-root user
USER $NB_UID

# Keep the original entrypoint
ENTRYPOINT ["/init"]
