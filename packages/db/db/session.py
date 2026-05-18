import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://health:health_dev@127.0.0.1:3306/health?charset=utf8mb4",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


# Force every connection to use UTC so MySQL's CURRENT_TIMESTAMP defaults
# (used on chat_sessions/chat_turns/chat_trace_steps) produce UTC values.
# Without this MySQL returns the server's local time as a naive DATETIME and
# we end up labeling it "UTC" at the API boundary, shifting every chat
# bubble timestamp by the local offset.
@event.listens_for(engine, "connect")
def _set_session_timezone(dbapi_conn, _):
    with dbapi_conn.cursor() as c:
        c.execute("SET time_zone = '+00:00'")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass
