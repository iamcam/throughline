from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from src.api.dependencies import get_db
from src.config import get_settings

router = APIRouter()
settings = get_settings()

@router.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.8"} #todo - version sprinkled about should replace with single source of truth

@router.get("/health/deep")
async def health_deep(db: AsyncSession = Depends(get_db)):
    checks = {}

    # DB
    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = "OK"
    except Exception as e:
        checks["db"] = f"error: {str(e)}"

    return checks