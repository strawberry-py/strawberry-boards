from __future__ import annotations

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from pie.database import database

VERSION = 1


class BettermemesMessage(database.base):
    __tablename__ = "boards_bettermemes_messages"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repost_message_id: Mapped[int] = mapped_column(BigInteger)


class BettermemesSource(database.base):
    __tablename__ = "boards_bettermemes_sources"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    limit: Mapped[int]
