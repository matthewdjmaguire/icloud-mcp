import azure.functions as func
import httpx
import subprocess
import asyncio
import os
import sys
import logging

app = func.FunctionApp()

# Global subprocess handle — persists between warm invocations
_mcp_process = None
_mcp_ready = False

async def ensure_mcp_server():
    """Start the FastMCP server subprocess if not already running."""
    global _mcp_process, _mcp_ready

    if _mcp_process is not None and _mcp_process.poll() is None:
        return  # Already running

    logging.info("Starting FastMCP subprocess...")
    _mcp_process = subprocess.Popen(
        [sys.executable, "run.py", "--http", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy()
    )

    # Give it a moment to start up
    await asyncio.sleep(2)
    _mcp_ready = True
    logging.info("FastMCP subprocess started.")


@app.function_name(name="mcp")
@app.route(route="mcp", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def mcp_endpoint(req: func.HttpRequest) -> func.HttpResponse:

    # Validate API key
    api_key = req.headers.get("x-api-key")
    expected = os.environ.get("MCP_API_KEY")
    if not api_key or api_key != expected:
        return func.HttpResponse("Unauthorized", status_code=401)

    # Ensure the MCP server subprocess is running
    await ensure_mcp_server()

    # Proxy the request to the local FastMCP server
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"http://localhost:8000/mcp"
            
            # Forward method, headers (minus host), and body
            headers = {
                k: v for k, v in req.headers.items()
                if k.lower() not in ("host", "x-api-key")
            }
            
            response = await client.request(
                method=req.method,
                url=url,
                headers=headers,
                content=req.get_body(),
            )

            return func.HttpResponse(
                body=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                mimetype=response.headers.get("content-type", "application/json"),
            )

    except httpx.ConnectError:
        logging.error("Could not connect to FastMCP subprocess.")
        return func.HttpResponse("MCP server unavailable", status_code=503)


@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)


@app.timer_trigger(
    schedule="0 */30 * * * *",
    arg_name="timer",
    run_on_startup=True
)
async def warmup(timer: func.TimerRequest) -> None:
    """Keeps the function warm and the subprocess alive."""
    await ensure_mcp_server()
    logging.info("Warm-up ping complete.")
