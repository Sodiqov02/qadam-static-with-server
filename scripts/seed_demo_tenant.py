import datetime as dt

from src.db import get_session
from src.db_models import Tenant


def main() -> None:
    """One-off demo seed for Railway DB via DATABASE_URL env."""
    slug = "test-tenant"
    with get_session() as session:
        tenant = session.query(Tenant).filter(Tenant.slug == slug).one_or_none()
        if tenant:
            print("test-tenant already exists")
            return
        tenant = Tenant(
            slug=slug,
            name="Test tenant",
            admin_chat_id=1037291604,
            features={},
            is_active=True,
            created_at=dt.datetime.now(dt.timezone.utc),
        )
        session.add(tenant)
        session.flush()
        print(f"created test-tenant id={tenant.id}")


if __name__ == "__main__":
    main()
