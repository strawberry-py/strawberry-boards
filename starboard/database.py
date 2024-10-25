from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Integer, UniqueConstraint, or_
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

    __table_args__ = (
        UniqueConstraint(
            source_message_id,
            starboard_message_id,
            name="source_message_id_starboard_message_id_unique",
        ),
    )

    @staticmethod
    def get_all(
        guild_id: int,
        author_id: int = None,
        source_channel_id: int = None,
        source_message_id: int = None,
        starboard_channel_id: int = None,
        starboard_message_id: int = None,
    ) -> list[StarboardChannel]:

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

        return query.all()

    @staticmethod
    def add(
        guild_id: int,
        author_id: int,
        source_channel_id: int,
        source_message_id: int,
        starboard_channel_id: int,
        starboard_message_id: int,
    ) -> StarboardChannel:
        sb_message = StarboardMessage(
            guild_id=guild_id,
            author_id=author_id,
            source_channel_id=source_channel_id,
            source_message_id=source_message_id,
            starboard_channel_id=starboard_channel_id,
            starboard_message_id=starboard_message_id,
        )

        session.merge(sb_message)
        session.commit()


class StarboardChannel(database.base):
    __tablename__ = "boards_starboard_channels"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    starboard_channel_id: Mapped[int] = mapped_column(BigInteger)
    limit: Mapped[int]

    def get(
        guild_id: int,
        source_channel_id: int = None,
    ) -> Optional[StarboardChannel]:
        query = session.query(StarboardChannel)

        if source_channel_id:
            query = query.filter_by(source_channel_id=source_channel_id)

        return query.one_or_none()

    def check_unique(guild_id: int, channel_id: int) -> bool:
        query = (
            session.query(StarboardChannel.idx)
            .filter_by(guild_id=guild_id)
            .filter(
                or_(
                    StarboardChannel.source_channel_id == channel_id,
                    StarboardChannel.starboard_channel_id == channel_id,
                )
            )
        )
        return query.first() is None

    def get_all(
        guild_id: int = None, starboard_channel_id: int = None
    ) -> list[StarboardChannel]:
        query = session.query(StarboardChannel)

        if guild_id:
            query = query.filter_by(guild_id=guild_id)

        if starboard_channel_id:
            query.filter_by(starboard_channel_id=starboard_channel_id)

        return query.all()

    def set(
        guild_id: int, source_channel_id: int, starboard_channel_id: int, limit: int
    ) -> StarboardChannel:
        sb_channel = (
            session.query(StarboardChannel)
            .filter_by(guild_id=guild_id)
            .filter_by(source_channel_id=source_channel_id)
            .filter_by(starboard_channel_id=starboard_channel_id)
            .one_or_none()
        )
        if not sb_channel:
            sb_channel = StarboardChannel(
                guild_id=guild_id,
                source_channel_id=source_channel_id,
                starboard_channel_id=starboard_channel_id,
            )

        sb_channel.limit = limit

        session.merge(sb_channel)
        session.commit()

    def remove(self):
        session.delete(self)
        session.commit()
