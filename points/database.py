from __future__ import annotations

from enum import Enum
from typing import List, Optional

from sqlalchemy import BigInteger, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from pie.database import database, session

VERSION = 1


class BoardOrder(Enum):
    ASC = 0
    DESC = 1


class Setup(database.base):
    """List of guilds where points should be counted."""

    __tablename__ = "boards_points_setup"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    @classmethod
    def get(cls, guild_id: int) -> Optional[Setup]:
        setup = session.query(cls).filter_by(guild_id=guild_id).one_or_none()
        return setup

    @classmethod
    def get_all(cls) -> List[Setup]:
        setups = session.query(cls).all()
        return setups

    @classmethod
    def add(cls, guild_id: int) -> Optional[Setup]:
        if cls.get(guild_id) is not None:
            return None
        setup = Setup(guild_id=guild_id)
        session.add(setup)
        session.commit()
        return setup

    @classmethod
    def remove(cls, guild_id: int) -> bool:
        count = session.query(cls).filter_by(guild_id=guild_id).delete()
        return count == 1

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"

    def dump(self):
        return {"guild_id": self.guild_id}


class UserStats(database.base):
    """User points for reactions and messages."""

    __tablename__ = "boards_points_users"

    idx: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    points: Mapped[int]

    @staticmethod
    def get_stats(guild_id: int, user_id: int) -> UserStats:
        """Get user stats."""
        query = (
            session.query(UserStats)
            .filter_by(
                guild_id=guild_id,
                user_id=user_id,
            )
            .one_or_none()
        )
        return query

    @staticmethod
    def increment(guild_id: int, user_id: int, value: int):
        query = (
            session.query(UserStats)
            .filter_by(guild_id=guild_id, user_id=user_id)
            .first()
        )

        if not query:
            query = UserStats(guild_id=guild_id, user_id=user_id, points=value)
        else:
            query.points += value

        session.merge(query)
        session.commit()

    def get_count(guild_id: int) -> int:
        count = (
            session.query(func.count(UserStats.user_id))
            .filter_by(guild_id=guild_id)
            .scalar()
        )

        return count

    @staticmethod
    def get_position(guild_id: int, points: int) -> int:
        result = (
            session.query(func.count(UserStats.user_id))
            .filter_by(guild_id=guild_id)
            .filter(getattr(UserStats, "points") > points)
            .one_or_none()
        )
        return result[0] + 1 if result else None

    @staticmethod
    def get_best(guild_id: int, order: BoardOrder, limit: int = 10, offset: int = 0):
        if order == BoardOrder.DESC:
            order = UserStats.points.desc()
        elif order == BoardOrder.ASC:
            order = UserStats.points.asc()

        query = (
            session.query(UserStats)
            .filter_by(guild_id=guild_id)
            .order_by(order)
            .offset(offset)
            .limit(limit)
            .all()
        )

        return query

    def save(self):
        session.commit()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} idx="{self.idx}" guild_id="{self.guild_id}" '
            f'user_id="{self.user_id}" points="{self.points}">'
        )

    def dump(self) -> dict:
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "points": self.points,
        }
