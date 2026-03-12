import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import Config

DATABASE_URL = Config.DATABASE_URL
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment or config.")

# SQLAlchemy setup with pooling settings for Neon/Serverless Postgres
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"sslmode": "require"} if "neon" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
