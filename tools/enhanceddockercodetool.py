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

    def _find_matching_file(self, file_hint):
        """Smart file matching based on filename hints"""
        if not self.uploads_dir.exists():
            return None
            
        # Convert hint to lowercase for case-insensitive matching
        hint_lower = file_hint.lower()
        
        # Common file extensions to check
        extensions = ['.csv', '.txt', '.json', '.xlsx', '.pdf', '.py']
        
        # First try exact matches
        for file in self.uploads_dir.glob('*'):
            if file_hint == file.name:
                return file
                
        # Then try contains matching with extensions
        for file in self.uploads_dir.glob('*'):
            file_lower = file.name.lower()
            if hint_lower in file_lower:
                return file
                
        # Try matching specific patterns
        patterns = {
            'sales': ['*sales*.csv', '*revenue*.csv', '*orders*.csv'],
            'report': ['*report*.pdf', '*report*.xlsx', '*report*.csv'],
            'config': ['*config*.json', '*settings*.json', '*conf*.yaml'],
            'data': ['*data*.csv', '*data*.json', '*dataset*.csv']
        }
        
        for key, patterns_list in patterns.items():
            if key in hint_lower:
                for pattern in patterns_list:
                    matches = list(self.uploads_dir.glob(pattern))
                    if matches:
                        return matches[0]
                        
        return None

    def resolve_upload_path(self, file_path):
        path = Path(file_path)
        
        # If it's an absolute path and exists, use it directly
        if path.is_absolute() and path.exists():
            return path
            
        # If it's in uploads directory, use it
        uploads_path = self.uploads_dir / path
        if uploads_path.exists():
            return uploads_path
            
        # Try smart matching
        matched_file = self._find_matching_file(file_path)
        if matched_file:
            return matched_file
            
        raise FileNotFoundError(f"Could not find file matching: {file_path}")

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
