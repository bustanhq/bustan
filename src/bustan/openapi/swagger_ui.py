"""Swagger UI registration helpers."""

from __future__ import annotations

from ..contracts import AdapterRoute, HttpRequest, HttpResponse
from .schema_builder import generate_schema


class SwaggerModule:
    """Registers OpenAPI JSON and Swagger UI routes."""

    @staticmethod
    def setup(
        app,
        path: str,
        document: dict[str, object],
        *,
        swagger_ui_path: str | None = None,
    ) -> None:
        schema = generate_schema(app.route_contracts, document)
        json_path = path
        ui_path = swagger_ui_path or f"{path}/docs"

        async def openapi_json(_request: HttpRequest) -> HttpResponse:
            return HttpResponse.json(schema)

        async def swagger_html(_request: HttpRequest) -> HttpResponse:
            return HttpResponse(
                body=_swagger_html_template(json_path).encode("utf-8"),
                media_type="text/html",
            )

        app.get_http_adapter().register_routes(
            [
                AdapterRoute(
                    path=json_path,
                    methods=("GET",),
                    name="openapi_json",
                    handler=openapi_json,
                ),
                AdapterRoute(
                    path=ui_path,
                    methods=("GET",),
                    name="swagger_ui",
                    handler=swagger_html,
                ),
            ]
        )


def _swagger_html_template(openapi_path: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Bustan Swagger UI</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({{
        url: "{openapi_path}",
        dom_id: "#swagger-ui"
      }});
    </script>
  </body>
</html>
"""
