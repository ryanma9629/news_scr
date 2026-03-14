"""
Health and index API endpoints.

This module provides the health check and index page endpoints.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..middleware import VI_DEPLOY

router = APIRouter(tags=["health"])


@router.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve the index.html file with VI_DEPLOY configuration."""
    project_root = Path(__file__).parent.parent.parent
    index_path = project_root / "static" / "index.html"
    if index_path.exists():
        html_content = index_path.read_text(encoding="utf-8")
        company_name = request.query_params.get("company_name", "")
        customer_id = request.query_params.get("customer_id", "")

        config_script = f"""
    <script>
        window.VI_DEPLOY = {str(VI_DEPLOY).lower()};
        window.URL_COMPANY_NAME = "{company_name}";
        window.URL_CUSTOMER_ID = "{customer_id}";
    </script>
</body>"""
        html_content = html_content.replace("</body>", config_script)
        return HTMLResponse(content=html_content)
    else:
        raise HTTPException(status_code=404, detail="index.html not found")


@router.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "Adverse News Screening API is running."}