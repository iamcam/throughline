# scripts/create_test_db.py
import asyncio
import asyncpg
from src.config import get_settings

async def main():
    settings = get_settings()

    # Derive test DB name from main DB URL
    base_url = settings.database_url
    db_name = base_url.split("/")[-1]
    test_db_name = f"{db_name}_test"

    # Connect to postgres system DB to run CREATE DATABASE
    # asyncpg needs a plain postgresql:// URL, not postgresql+asyncpg://
    conn_url = base_url.rsplit("/", 1)[0].replace("postgresql+asyncpg", "postgresql") + "/postgres"

    conn = await asyncpg.connect(conn_url)
    try:
        await conn.execute(f'CREATE DATABASE "{test_db_name}"')
        print(f"Created: {test_db_name}")
    except asyncpg.DuplicateDatabaseError:
        print(f"Already exists: {test_db_name}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())