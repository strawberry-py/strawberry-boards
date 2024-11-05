from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Integer, UniqueConstraint, func, or_, distinct
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
        """Universal function to search for Starboard channels based on parameters.

        :param guild_id: Discord ID of the guild.
        :param author_id: Discord ID of the original message author.
        :param source_channel_id: Discord ID of the source channel.
        :param source_message_id: Discord ID of the source message.
        :param starboard_channel_id: Discord ID of the Starboard channel.
        :param starboard_message_id: Discord ID of the Starboard message.

        :returns: list of StarboardChannels found (might be empty)
        """

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
    ):
        """Add starboard message.

        :param guild_id: Discord ID of the guild.
        :param author_id: Discord ID of the original message author.
        :param source_channel_id: Discord ID of the source channel.
        :param source_message_id: Discord ID of the source message.
        :param starboard_channel_id: Discord ID of the Starboard channel.
        :param starboard_message_id: Discord ID of the Starboard message.
        """
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

    @staticmethod
    def get_all_authors_count(
        guild_id: int, starboard_channel_id: int = None
    ) -> list[tuple[int, int]]:
        """Gets the list of authors and the count of their starboarded messages
        :param guild_id: ID of the guild
        :param starboard_channel_id: (Optional) ID of the starboard channel

        :return: List of tuples in form of (author_id, count)"""
        query = session.query(
            StarboardMessage.author_id,
            func.count(distinct(StarboardMessage.source_message_id)).label("count"),
        ).filter(StarboardMessage.guild_id == guild_id)

        if starboard_channel_id:
            query = query.filter_by(starboard_channel_id=starboard_channel_id)

        query = query.group_by(StarboardMessage.author_id).order_by(
            func.count(StarboardMessage.author_id).desc()
        )

        return query.all()

    @staticmethod
    def get_author_stats(guild_id: int, author_id: int) -> list[tuple[int, int]]:
        """Gets the list of authors starboarded messages for each starboard channel
        :param guild_id: ID of the guild
        :param author_id: ID of the author

        :return: List of tuples in form of (starboard_channel_id, count)"""
        query = (
            session.query(
                StarboardMessage.starboard_channel_id,
                func.count(distinct(StarboardMessage.source_message_id)).label("count"),
            )
            .filter(StarboardMessage.guild_id == guild_id)
            .filter(StarboardMessage.author_id == author_id)
            .group_by(StarboardMessage.starboard_channel_id)
            .order_by(func.count(StarboardMessage.starboard_channel_id).desc())
        )

        return query.all()

    @staticmethod
    def get_author_total(guild_id: int, author_id: int) -> int:
        """Get total count of author's appearances in Starboard
        :param guild_id: ID of the guild
        :param author_id: ID of the author

        :return: Count of author's starboarded messages"""
        query = (
            session.query(
                func.count(StarboardMessage.author_id),
            )
            .filter(StarboardMessage.guild_id == guild_id)
            .filter(StarboardMessage.author_id == author_id)
        )

        query = query.group_by(StarboardMessage.author_id).order_by(
            func.count(StarboardMessage.starboard_channel_id).desc()
        )

        return query.scalar()


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
        """Gets the starboard channel.
        
        :param guild_id: Discord ID of the guild.
        :param source_channel_id: Optional source channel Discord ID
        
        :returns: StarboardChannel if found, None otherwise"""
        query = session.query(StarboardChannel)

        if source_channel_id:
            query = query.filter_by(source_channel_id=source_channel_id)

        return query.one_or_none()

    def check_unique(guild_id: int, channel_id: int) -> bool:
        """Checks if channel_id is not in use as source channel or Starboard channel.

        :param guild_id: Discord ID of the guild.
        :param channel_id: Discord ID of the channel.

        :returns: True if channel is not used, False otherwise
        """
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
        """Get's all Starboard channels based on the params.

        :param guild_id: Discord ID of the guild.
        :param starboard_channel_id: Discord ID of the Starboard channel.

        :returns: List of Starboard channels (empty if not found)
        """
        query = session.query(StarboardChannel)

        if guild_id:
            query = query.filter_by(guild_id=guild_id)

        if starboard_channel_id:
            query.filter_by(starboard_channel_id=starboard_channel_id)

        return query.all()

    def set(
        guild_id: int, source_channel_id: int, starboard_channel_id: int, limit: int
    ):
        """Add or update Starboard channel.

        :param guild_id: Discord ID of the guild.
        :param source_channel_id: Discord ID of the source channel.
        :param starboard_channel_id: Discord ID of the Starboard channel.
        :param limit: Minimum reactions for the repost.
        """
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
        """Removes Starboard channel."""
        session.delete(self)
        session.commit()
