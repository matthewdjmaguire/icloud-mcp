import azure.functions as func
import httpx
import subprocess
import asyncio
import os
import sys
import logging

app = func.FunctionApp()

_mcp_process = None
_mcp_ready = False

WWWROOT = "/home/site/wwwroot"

async def ensure_mcp_server():
    """Start the FastMCP subprocess if not already running."""
    global _mcp_process, _mcp_ready

    if _mcp_process is not None and _mcp_process.poll() is None:
        return  # Already running

    logging.info("Starting FastMCP subprocess...")

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{WWWROOT}:"
        f"{WWWROOT}/.python_packages/lib/site-packages:"
        + env.get("PYTHONPATH", "")
    )
    env["PORT"] = "8000"

    _mcp_process = subprocess.Popen(
        [sys.executable, f"{WWWROOT}/run.py", "--http", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,  # Separate from stdout
        cwd=WWWROOT,
        env=env
    )

    # Poll until ready or failed
    for attempt in range(20):
        await asyncio.sleep(1)

        # Check if process died — drain full output for diagnostics
        if _mcp_process.poll() is not None:
            try:
                stdout, stderr = _mcp_process.communicate(timeout=5)
                for line in (stdout + stderr).decode().strip().splitlines():
                    logging.error(f"FastMCP: {line}")
            except Exception as e:
                logging.error(f"Could not read subprocess output: {e}")
            logging.error(f"FastMCP exited with code: {_mcp_process.returncode}")
            return

        # Log any stdout lines while waiting
        if _mcp_process.stdout:
            try:
                line = _mcp_process.stdout.readline()
                if line:
                    logging.info(f"FastMCP: {line.decode().strip()}")
            except Exception:
                pass

        # Check if accepting connections
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get("http://localhost:8000/mcp")
                logging.info(f"FastMCP ready after {attempt + 1}s")
                _mcp_ready = True
                return
        except (httpx.ConnectError, httpx.TimeoutException):
            logging.info(f"Waiting for FastMCP... attempt {attempt + 1}")
            continue

    logging.error("FastMCP failed to start after 20 seconds")


@app.function_name(name="mcp")
@app.route(route="mcp", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def mcp_endpoint(req: func.HttpRequest) -> func.HttpResponse:

    await ensure_mcp_server()

    if not _mcp_ready:
        return func.HttpResponse("MCP server unavailable", status_code=503)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                k: v for k, v in req.headers.items()
                if k.lower() not in ("host",)
            }

            response = await client.request(
                method=req.method,
                url="http://localhost:8000/mcp",
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
    await ensure_mcp_server()
    logging.info("Warm-up ping complete.")
