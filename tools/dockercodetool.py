import docker
import tempfile
import os
import json
import base64
from tools.base import BaseTool
from pathlib import Path
import logging
import shutil

class DockerCodeTool(BaseTool):
    name = "dockercodetool"
    description = '''
    Executes Python code safely in a Docker container with:
    - Isolated environment from host system
    - Resource limitations (memory, CPU)
    - Controlled network access
    - Clean environment for each execution
    - File upload/download support
    - Environment variable support
    
    Returns execution results including stdout, stderr, and file contents.
    '''
    
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute"
            },
            "env_vars": {
                "type": "object",
                "description": "Dictionary of environment variables",
                "additionalProperties": {"type": "string"}
            },
            "upload_files": {
                "type": "array",
                "description": "List of files to upload to container",
                "items": {
                    "type": "object",
                    "properties": {
                        "container_path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["container_path", "content"]
                }
            },
            "download_paths": {
                "type": "array",
                "description": "List of file paths to download from container",
                "items": {"type": "string"}
            },
            "requirements": {
                "type": "array",
                "description": "List of pip packages to install",
                "items": {"type": "string"}
            }
        },
        "required": ["code"]
    }

    def __init__(self):
        self.client = docker.from_env()
        self.base_image = "python:3.11-slim"
        
        # Create base image with common dependencies if it doesn't exist
        self._ensure_base_image()

    def _ensure_base_image(self):
        """Create a custom base image with common dependencies."""
        dockerfile = """
        FROM python:3.11-slim
        RUN apt-get update && apt-get install -y --no-install-recommends \
            gcc \
            python3-dev \
            && rm -rf /var/lib/apt/lists/*
        WORKDIR /code
        """
        
        try:
            self.client.images.get("python-sandbox:latest")
        except docker.errors.ImageNotFound:
            # Create temporary directory in a more accessible location
            temp_dir = tempfile.mkdtemp(prefix='dockertool-')
            dockerfile_path = os.path.join(temp_dir, 'Dockerfile')
            
            try:
                with open(dockerfile_path, 'w') as f:
                    f.write(dockerfile)
                
                self.client.images.build(
                    path=temp_dir,
                    dockerfile=dockerfile_path,
                    tag="python-sandbox:latest"
                )
            finally:
                # Clean up temporary directory
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _prepare_container_files(self, code: str, upload_files: list, requirements: list) -> str:
        """Prepare files for the container including the main script and uploaded files."""
        temp_dir = tempfile.mkdtemp(prefix='dockertool-run-')
        
        # Create main script with requirements installation
        main_script = Path(temp_dir) / "main.py"
        
        # If there are requirements, prepend pip install
        setup_code = ""
        if requirements:
            setup_code = f"""
import subprocess
import sys

def install_requirements():
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

install_requirements()
"""
        
        # Write the complete script
        main_script.write_text(setup_code + code)
        
        # Create requirements.txt if needed
        if requirements:
            reqs_file = Path(temp_dir) / "requirements.txt"
            reqs_file.write_text("\n".join(requirements))
        
        # Handle uploaded files
        for file_spec in upload_files:
            file_path = Path(temp_dir) / os.path.basename(file_spec["container_path"])
            content = file_spec["content"]
            
            # Handle base64 content
            if ";base64," in content:
                content = content.split(";base64,")[1]
                file_path.write_bytes(base64.b64decode(content))
            else:
                file_path.write_text(content)
        
        return temp_dir

    def execute(self, **kwargs) -> str:
        temp_dir = None
        try:
            code = kwargs.get("code")
            env_vars = kwargs.get("env_vars", {})
            upload_files = kwargs.get("upload_files", [])
            download_paths = kwargs.get("download_paths", [])
            requirements = kwargs.get("requirements", [])

            # Prepare temporary directory with all files
            temp_dir = self._prepare_container_files(code, upload_files, requirements)

            # Create container with proper mounts and restrictions
            container = self.client.containers.create(
                "python-sandbox:latest",
                command=["python", "/code/main.py"],
                volumes={
                    temp_dir: {
                        'bind': '/code',
                        'mode': 'rw'
                    }
                },
                environment=env_vars,
                mem_limit="512m",  # Limit memory to 512MB
                memswap_limit="512m",  # Disable swap
                cpu_period=100000,  # Default CPU CFS period
                cpu_quota=50000,  # Limit to 50% of CPU
                network_disabled=True,  # Disable network access
                user="nobody"  # Run as non-root user
            )

            try:
                # Start container and wait for completion
                container.start()
                result = container.wait(timeout=30)  # 30 second timeout

                # Get output, capturing both stdout and stderr
                stdout = container.logs(stdout=True, stderr=False).decode('utf-8')
                stderr = container.logs(stdout=False, stderr=True).decode('utf-8')
                
                # Get downloaded files
                downloaded_files = {}
                for path in download_paths:
                    try:
                        bits, _ = container.get_archive(f"/code/{os.path.basename(path)}")
                        content = b"".join([chunk for chunk in bits])
                        downloaded_files[path] = f"data:application/octet-stream;base64,{base64.b64encode(content).decode('utf-8')}"
                    except Exception as e:
                        downloaded_files[path] = f"Error downloading: {str(e)}"

                response = {
                    "success": result["StatusCode"] == 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "error": None if result["StatusCode"] == 0 else f"Exit code: {result['StatusCode']}",
                    "downloaded_files": downloaded_files
                }

            finally:
                # Cleanup container
                container.remove(force=True)

            return json.dumps(response, indent=2)

        except Exception as e:
            logging.error(f"Docker code execution failed: {str(e)}")
            return json.dumps({
                "success": False,
                "error": f"Tool execution failed: {str(e)}",
                "stdout": "",
                "stderr": str(e),
                "downloaded_files": {}
            }, indent=2)
        finally:
            # Clean up temporary directory
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)