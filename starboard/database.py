from __future__ import annotations

from sqlalchemy import BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pie.database import database

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

class StarboardChannel(database.base):
    __tablename__ = "boards_starboard_channels"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    starboard_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    limit: Mapped[int]
