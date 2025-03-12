# Use the Kubeflow Code-Server Python image
FROM kubeflownotebookswg/codeserver-python:latest

# Switch to root to make modifications
USER root

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Clone ComfyUI repository to tmp_home (which will be copied to home at runtime)
RUN mkdir -p /tmp_home/jovyan/ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /tmp_home/jovyan/ComfyUI
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI

# Create models directory structure
RUN mkdir -p /tmp_home/jovyan/ComfyUI/models/checkpoints
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/ComfyUI/models

# Install PyTorch with CUDA support and ComfyUI requirements
RUN pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu124
WORKDIR /tmp_home/jovyan/ComfyUI
RUN pip install -r requirements.txt
RUN pip install flask

# Copy our Flask proxy app that will serve ComfyUI
COPY app.py /tmp_home/jovyan/
COPY templates /tmp_home/jovyan/templates/
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/app.py
RUN chown -R ${NB_USER}:${NB_GID} /tmp_home/jovyan/templates

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
