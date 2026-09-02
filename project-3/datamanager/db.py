import os
from sqlalchemy import (Column, BigInteger, String, Float, DateTime, Index,
                        create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Reading(Base):
    __tablename__ = "readings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(128), nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    temperature = Column(Float)
    humidity = Column(Float)
    co = Column(Float)
    smoke = Column(Float)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_readings_device_ts", "device_id", "ts"),
        Index("ix_readings_ts", "ts"),
    )


def _url() -> str:
    return (
        f"postgresql+psycopg://{os.getenv('DB_USER', 'iots')}:"
        f"{os.getenv('DB_PASSWORD', 'iots')}@"
        f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME', 'iots')}"
    )


engine = create_engine(_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
