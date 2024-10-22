from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pie.database import database, session

VERSION = 1


class StarboardMessage(database.base):
    __tablename__ = "boards_starboard_messages"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    starboard_channel_id: Mapped[int] = mapped_column(BigInteger)
    starboard_message_id: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = UniqueConstraint(
        source_message_id,
        starboard_message_id,
        name="source_message_id_starboard_message_id_unique",
    )

    @staticmethod
    def get(
        guild_id: int,
        author_id: int = None,
        source_channel_id: int = None,
        source_message_id: int = None,
        starboard_channel_id: int = None,
        starboard_message_id: int = None,
    ) -> Optional[StarboardChannel]:

        query = session.query(StarboardMessage).filter_by(guild_id=guild_id)

        if author_id:
            query = query.filter_by(author_id=author_id)
        if source_channel_id:
            query = query.filter_by(source_channel_id=source_channel_id)
        if source_message_id:
            query = query.filter_by(source_message_id=source_message_id)
        if starboard_channel_id:
            query = query.filter_by(starboard_channel_id=starboard_channel_id)
        if starboard_message_id:
            query = query.filter_by(starboard_message_id=starboard_message_id)

        return query.one_or_none()


class StarboardChannel(database.base):
    __tablename__ = "boards_starboard_channels"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    starboard_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    limit: Mapped[int]
