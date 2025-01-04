import os
import docker
import tempfile
import shutil
from pathlib import Path
from tools.base import BaseTool

class EnhancedDockerCodeTool(BaseTool):
    name = "enhanceddockercodetool"
    description = '''
    Enhanced Docker-based Python code execution tool with improved file handling.
    Supports automatic upload/download directory management and smart path resolution.
    Executes Python code in isolated Docker containers with file transfer capabilities.
    '''
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "upload_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "container_path": {"type": "string"},
                        "content": {"type": "string"}
                    }
                }
            },
            "download_paths": {
                "type": "array",
                "items": {"type": "string"}
            },
            "requirements": {
                "type": "array",
                "items": {"type": "string"}
            },
            "env_vars": {
                "type": "object",
                "additionalProperties": {"type": "string"}
            }
        },
        "required": ["code"]
    }

    def __init__(self):
        super().__init__()
        self.client = docker.from_env()
        self.uploads_dir = Path('./uploads')
        self.downloads_dir = Path('./downloads')
        self.downloads_dir.mkdir(exist_ok=True)

    def resolve_upload_path(self, file_path):
        path = Path(file_path)
        if not path.is_absolute():
            path = self.uploads_dir / path
        if not path.exists():
            raise FileNotFoundError(f"Upload file not found: {path}")
        return path

    def prepare_container(self, requirements=None, env_vars=None):
        container_config = {
            "image": "python:3.9-slim",
            "command": "tail -f /dev/null",
            "detach": True,
            "remove": True,
            "environment": env_vars or {}
        }
        container = self.client.containers.run(**container_config)
        
        if requirements:
            requirements_str = " ".join(requirements)
            container.exec_run(f"pip install {requirements_str}")
        
        return container

    def execute(self, **kwargs) -> str:
        code = kwargs.get("code")
        upload_files = kwargs.get("upload_files", [])
        download_paths = kwargs.get("download_paths", [])
        requirements = kwargs.get("requirements", [])
        env_vars = kwargs.get("env_vars", {})

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            script_path = temp_path / "script.py"
            script_path.write_text(code)

            container = self.prepare_container(requirements, env_vars)
            
            try:
                for file_spec in upload_files:
                    if "content" in file_spec:
                        container_path = file_spec["container_path"]
                        content = file_spec["content"]
                        temp_file = temp_path / "temp_content"
                        temp_file.write_text(content)
                        tar_data = docker.utils.tar(str(temp_file))
                        container.put_archive("/", tar_data)
                    else:
                        local_path = self.resolve_upload_path(file_spec["path"])
                        container_path = file_spec["container_path"]
                        tar_data = docker.utils.tar(str(local_path))
                        container.put_archive("/", tar_data)

                container.put_archive("/", docker.utils.tar(str(script_path)))
                result = container.exec_run(f"python /script.py")
                
                for download_path in download_paths:
                    try:
                        bits, stat = container.get_archive(download_path)
                        download_file = self.downloads_dir / Path(download_path).name
                        with open(download_file, 'wb') as f:
                            for chunk in bits:
                                f.write(chunk)
                    except docker.errors.NotFound:
                        print(f"Warning: Download file not found: {download_path}")

                return result.output.decode('utf-8')

            finally:
                container.stop()
                container.remove(force=True)

    def cleanup(self):
        try:
            containers = self.client.containers.list(filters={"ancestor": "python:3.9-slim"})
            for container in containers:
                container.stop()
                container.remove(force=True)
        except Exception as e:
            print(f"Cleanup error: {str(e)}")