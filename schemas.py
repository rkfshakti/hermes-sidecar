"""Tool schemas for the two small inspection tools Sidecar exposes."""

SIDECAR_STATUS = {
    "name": "sidecar_status",
    "description": (
        "Show the paired Sidecar daemon, the local workspace it is serving, its effective "
        "approval policy, and the number of audited commands. Use this before assuming a "
        "command will run on the remote host."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

SIDECAR_AUDIT = {
    "name": "sidecar_audit",
    "description": (
        "Read the local Sidecar audit log: recent commands, whether they were auto-allowed, "
        "approved, denied or failed, and their exit codes. Command output is not stored."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent entries to return (default 20, max 200).",
                "default": 20,
            }
        },
        "required": [],
    },
}
