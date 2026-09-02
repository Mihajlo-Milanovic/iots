from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select

from db import Reading, SessionLocal

AGGREGATABLE = {"temperature", "humidity", "co", "smoke"}
FIELDS = AGGREGATABLE | {"device_id", "ts", "lat", "lon"}


def _range_filter(stmt, device_id: str, frm: Optional[datetime], to: Optional[datetime]):
    if device_id:
        stmt = stmt.where(Reading.device_id == device_id)
    if frm is not None:
        stmt = stmt.where(Reading.ts >= frm)
    if to is not None:
        stmt = stmt.where(Reading.ts <= to)
    return stmt


def create(data: dict) -> Reading:
    with SessionLocal() as s:
        row = Reading(**data)
        s.add(row)
        s.commit()
        return row


def create_many(items: list[dict]) -> list[Reading]:
    """Upiši seriju očitavanja i vrati upisane redove (sa dodeljenim id-jevima)."""
    if not items:
        return []
    with SessionLocal() as s:
        rows = [Reading(**i) for i in items]
        s.add_all(rows)
        s.commit()
        return rows


def get(rid: int) -> Optional[Reading]:
    with SessionLocal() as s:
        return s.get(Reading, rid)


def list_readings(device_id: str, frm, to, page: int, page_size: int):
    page = max(page, 0)
    page_size = min(page_size or 50, 500)
    with SessionLocal() as s:
        base = _range_filter(select(Reading), device_id, frm, to)
        total = s.scalar(
            _range_filter(select(func.count(Reading.id)), device_id, frm, to)
        )
        rows = s.scalars(
            base.order_by(Reading.ts.desc(), Reading.id.desc())
            .offset(page * page_size)
            .limit(page_size)
        ).all()
        return rows, int(total or 0)


def update(rid: int, data: dict, fields: list[str]) -> Optional[Reading]:
    changed = {k: v for k, v in data.items()
               if k in FIELDS and (not fields or k in fields)}
    with SessionLocal() as s:
        row = s.get(Reading, rid)
        if row is None:
            return None
        for k, v in changed.items():
            setattr(row, k, v)
        s.commit()
        return row


def delete(rid: int) -> bool:
    with SessionLocal() as s:
        row = s.get(Reading, rid)
        if row is None:
            return False
        s.delete(row)
        s.commit()
        return True


def aggregate(device_id: str, field: str, frm, to) -> dict:
    col = getattr(Reading, field)
    with SessionLocal() as s:
        stmt = _range_filter(
            select(func.min(col), func.max(col), func.avg(col),
                   func.sum(col), func.count(col)),
            device_id, frm, to,
        )
        mn, mx, avg, total, cnt = s.execute(stmt).one()
        return {
            "min": float(mn or 0.0),
            "max": float(mx or 0.0),
            "avg": float(avg or 0.0),
            "sum": float(total or 0.0),
            "count": int(cnt or 0),
        }
