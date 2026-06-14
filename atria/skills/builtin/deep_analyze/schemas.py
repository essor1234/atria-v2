"""JSON parameter schemas for deep_analyze tools."""

PARAMS_DEEP_ANALYZE = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to a .csv or .xlsx file.",
        },
        "domain_context": {
            "type": "string",
            "description": (
                "Optional framing for domain enrichment "
                "(e.g. 'workforce automation 2030'). "
                "If omitted, the topic is inferred from the filename."
            ),
            "default": "",
        },
        "depth": {
            "type": "string",
            "enum": ["fast", "standard", "deep"],
            "description": (
                "Analysis depth. 'fast' = 2 sections & 3 charts, "
                "'standard' = 3-4 sections & 4 charts (default), "
                "'deep' = 5 sections & 6 charts."
            ),
            "default": "standard",
        },
    },
    "required": ["file_path"],
}

PARAMS_GET_ANALYZE_STATUS = {
    "type": "object",
    "properties": {"job_id": {"type": "string", "description": "Job ID from deep_analyze."}},
    "required": ["job_id"],
}

PARAMS_CANCEL_ANALYZE = {
    "type": "object",
    "properties": {"job_id": {"type": "string", "description": "Job ID from deep_analyze."}},
    "required": ["job_id"],
}
