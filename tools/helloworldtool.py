from tools.base import BaseTool
import datetime

class HelloWorldTool(BaseTool):
    name = "helloworldtool"
    description = '''
    A simple tool that prints 'Hello World' and returns the current timestamp.
    Returns a string containing the greeting and timestamp.
    '''
    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    def execute(self, **kwargs) -> str:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"Hello World! Current timestamp: {current_time}"
        print(message)
        return message