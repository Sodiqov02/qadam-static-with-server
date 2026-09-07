from src.public_urls import build_public_admin_menu_url


def main() -> None:
    expected = "https://demo.example/admin/menu/cafe-a?admin_token=one-time-token"
    actual = build_public_admin_menu_url(
        "https://demo.example/",
        "cafe-a",
        "one-time-token",
    )
    if actual != expected:
        raise AssertionError(f"unexpected admin URL: {actual}")

    encoded = build_public_admin_menu_url("https://demo.example", "cafe a", "a+b/c")
    if encoded != "https://demo.example/admin/menu/cafe%20a?admin_token=a%2Bb%2Fc":
        raise AssertionError(f"URL components were not encoded safely: {encoded}")

    for unsafe in ("", "http://127.0.0.1:8000", "http://localhost:8000"):
        try:
            build_public_admin_menu_url(unsafe, "demo", "token")
        except ValueError:
            continue
        raise AssertionError(f"unsafe public base URL accepted: {unsafe!r}")

    print("public admin URL regression: OK")


if __name__ == "__main__":
    main()
