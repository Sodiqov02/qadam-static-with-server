from urllib.parse import quote, urlencode, urlsplit, urlunsplit


def build_public_admin_menu_url(public_base_url: str, tenant_slug: str, token: str) -> str:
    """Build the one-time tenant menu-admin URL on a public HTTPS origin."""
    base_url = str(public_base_url or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("PUBLIC_BASE_URL must be an absolute HTTPS origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("PUBLIC_BASE_URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("PUBLIC_BASE_URL must not contain a path")

    slug = quote(str(tenant_slug or "").strip(), safe="")
    if not slug:
        raise ValueError("Tenant slug is required")
    query = urlencode({"admin_token": str(token or "")})
    return urlunsplit((parsed.scheme, parsed.netloc, f"/admin/menu/{slug}", query, ""))
