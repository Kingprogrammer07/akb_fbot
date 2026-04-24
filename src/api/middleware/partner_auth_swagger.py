from fastapi.openapi.utils import get_openapi
from fastapi import FastAPI


def custom_openapi(app: FastAPI):
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Add security scheme for Partner Key
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    if "securitySchemes" not in openapi_schema["components"]:
        openapi_schema["components"]["securitySchemes"] = {}

    openapi_schema["components"]["securitySchemes"]["AdminAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Admin-Authorization",
        "description": "Admin tokenini kiriting: Bearer <token>",
    }

    openapi_schema["components"]["securitySchemes"]["PartnerKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Partner-Key",
        "description": "Enter your Partner API Key here to test /shipment/ endpoints.",
    }

    # Apply Admin Auth to admin and statistics endpoints
    for path, path_item in openapi_schema.get("paths", {}).items():
        if (
            path.startswith("/api/v1/admin")
            or path.startswith("/api/v1/statistics")
            or path.startswith("/api/v1/payments/process-bulk")
            or path.startswith("/api/v1/payments/adjust-balance")
            or path.startswith("/api/v1/payments/cashier-log")
            or path.startswith("/api/v1/payments/all-cashier-logs")
        ):
            for method, operation in path_item.items():
                if "security" not in operation:
                    operation["security"] = []
                operation["security"].append({"AdminAuth": []})

    # Apply this security to shipment endpoints
    for path, path_item in openapi_schema.get("paths", {}).items():
        if path.startswith("/api/v1/shipment"):
            for method, operation in path_item.items():
                if "security" not in operation:
                    operation["security"] = []
                operation["security"].append({"PartnerKeyAuth": []})

    app.openapi_schema = openapi_schema
    return app.openapi_schema
