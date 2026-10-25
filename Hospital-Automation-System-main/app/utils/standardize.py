def standardize_string(value):
    """Strip whitespace and convert to uppercase for consistent storage and lookup."""
    if value is not None and isinstance(value, str):
        return value.strip().upper()
    return value


def standardize_skills(value):
    """Normalize comma-separated skill string to uppercase with no spaces, removing duplicates/empty tokens."""
    if value is None or not isinstance(value, str):
        return value
    parts = []
    for part in value.split(","):
        token = part.strip().upper()
        if token and token != "GENERAL":
            parts.append(token)
    return ",".join(parts) if parts else None

