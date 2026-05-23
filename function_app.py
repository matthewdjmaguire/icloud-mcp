import azure.functions as func
import subprocess
import sys
import os

app = func.FunctionApp()

@app.function_name(name="mcp")
@app.route(route="mcp", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def mcp_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    # Validate API key
    api_key = req.headers.get("x-api-key")
    if api_key != os.environ.get("MCP_API_KEY"):
        return func.HttpResponse("Unauthorized", status_code=401)
    
    # Forward to the MCP server
    from icloud_mcp.server import create_server
    # Handler logic here - see note below
    pass

@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)

@app.timer_trigger(schedule="0 */30 * * * *", 
                   arg_name="timer",
                   run_on_startup=False)
async def warmup(timer: func.TimerRequest) -> None:
    # Keeps the function warm
    pass
