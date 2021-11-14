from __future__ import annotations

from typing import Optional, Union, List, Dict

from sqlalchemy import (
    update,
    func,
    asc,
    desc,
    ARRAY,
    Column,
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
)
from sqlalchemy.orm import Query

import discord

from database import database, session


class UserChannelConfig(database.base):
    """Represents a cofiguration of a guild.

    Attributes:
        guild_id: ID of the guild.
        ignored_channels: IDs of channels that are ignored when ranking.
        ignored_users: IDs of users that are ignored when ranking.
    """

    __tablename__ = "user_channel_config"

    guild_id = Column(BigInteger, primary_key=True, autoincrement=False)
    ignored_channels = Column(ARRAY(BigInteger))
    ignored_users = Column(ARRAY(BigInteger))

    @staticmethod
    def add(
        guild_id: int,
        ignored_channels: Union[int, List[int]] = None,
        ignored_users: Union[int, List[int]] = None,
    ) -> UserChannelConfig:
        """Updates the Guild Config item. Creates if not already present

        Args:
            guild_id: ID of the guild.
            ignored_channels: ID or list of IDs of the channel(s) to ignore. Defaults to None.
            ignored_users: ID or list of IDs of the users(s) to ignore. Defaults to None.

        Returns:
            Added/Updated config object
        """
        if ignored_channels is None and ignored_users is None:
            return
        query = (
            session.query(UserChannelConfig).filter_by(guild_id=guild_id).one_or_none()
        )

        if query is not None:
            if ignored_channels is not None:
                if isinstance(ignored_channels, int):
                    query.ignored_channels.append(ignored_channels)
                else:
                    query.ignored_channels.extend(ignored_channels)
            if ignored_users is not None:
                if isinstance(ignored_users, int):
                    query.ignored_users.append(ignored_users)
                else:
                    query.ignored_users.extend(ignored_users)
        else:
            query = UserChannelConfig(
                guild_id=guild_id,
                ignored_channels=ignored_channels,
                ignored_users=ignored_users,
            )
            session.add(query)
        session.commit()
        return query

    @staticmethod
    def get(guild_id: int) -> Optional[UserChannelConfig]:
        """Retreives the guild configuration

        Args:
            guild_id: ID of the guild.

        Returns:
            Config object (if found)
        """
        return (
            session.query(UserChannelConfig).filter_by(guild_id=guild_id).one_or_none()
        )


class UserChannel(database.base):
    """Represents a database UserChannel item for `Messages` module.

    Attributes:
        idx: The database item ID.
        guild_id: ID of the guild.
        guild_name: Name of the guild.
        channel_id: ID of the channel.
        channel_name: Name of the channel.
        user_id: ID of the user.
        user_name: Name of the user.
        is_webhook: Whether the author is a webhook.
        count: Number of messages.
        last_msg_at: When the last message was sent.
    """

    __tablename__ = "user_channels"

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger)
    guild_name = Column(String)
    channel_id = Column(BigInteger)
    channel_name = Column(String)
    user_id = Column(BigInteger)
    user_name = Column(String)
    is_webhook = Column(Boolean)
    count = Column(BigInteger, default=1)
    last_msg_at = Column(DateTime)

    @staticmethod
    def increment(message: discord.Message, positive: bool) -> UserChannel:
        """Increment user_channel count by one, if it doesn't exist, create it

        Args:
            message: The message object to increment from
            positive: Whether we add or subtract
        """
        guild_id = message.guild.id
        guild_name = message.guild.name
        channel_id = message.channel.id
        channel_name = message.channel.name
        user_id = message.author.id
        user_name = message.author.display_name
        is_webhook = True if message.webhook_id else False
        last_msg_at = message.created_at

        user_channel = (
            session.query(UserChannel)
            .filter_by(
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=user_id,
            )
            .one_or_none()
        )
        if user_channel is None:
            user_channel = UserChannel(
                guild_id=guild_id,
                guild_name=guild_name,
                channel_id=channel_id,
                channel_name=channel_name,
                user_id=user_id,
                user_name=user_name,
                is_webhook=is_webhook,
                count=1 if positive else 0,
                last_msg_at=last_msg_at,
            )
            session.add(user_channel)
        else:
            if positive:
                user_channel.count = user_channel.count + 1
            else:
                user_channel.count = user_channel.count - 1
            if user_channel.last_msg_at < last_msg_at:
                user_channel.last_msg_at = last_msg_at

        UserChannel._update_names(user_channel)
        session.commit()

        return user_channel

    @staticmethod
    def _update_names(user_channel: UserChannel):
        """Updates the names in the whole database.

        Args:
            user_channel: [description]
        """
        stmt_guild = (
            update(UserChannel)
            .where(UserChannel.guild_id == user_channel.guild_id)
            .values(guild_name=user_channel.guild_name)
            .execution_options(synchronize_session=False)
        )
        stmt_channel = (
            update(UserChannel)
            .where(UserChannel.channel_id == user_channel.channel_id)
            .values(channel_name=user_channel.channel_name)
            .execution_options(synchronize_session=False)
        )
        stmt_user = (
            update(UserChannel)
            .where(UserChannel.guild_id == user_channel.guild_id)
            .where(UserChannel.user_id == user_channel.user_id)
            .values(user_name=user_channel.user_name)
            .execution_options(synchronize_session=False)
        )

        session.execute(stmt_guild)
        session.execute(stmt_channel)
        session.execute(stmt_user)

    @staticmethod
    def _filter(
        query: Query = None,
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> Query:
        """Adds filters to a query or creates a new query.

        Args:
            query: Query the filters get added to. Creates a new one if None.
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            The filtered query.
        """
        if query is None:
            query = session.query(UserChannel)

        if guild is not None:
            query = query.filter_by(guild_id=guild.id)
        if channel is not None:
            query = query.filter_by(channel_id=channel.id)
        if member is not None:
            query = query.filter_by(member_id=member.id)
        if not webhooks:
            query = query.filter_by(is_webhook=False)
        if not include_filtered:
            config = UserChannelConfig.get(guild.id)
            query = query.filter(
                UserChannel.channel_id.not_in(config.ignored_channels)
            ).filter(UserChannel.user_id.not_in(config.ignored_users))

        return query

    @staticmethod
    def get(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> List[UserChannel]:
        """Gets result from the database filtered by various optional filters.

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting list
        """
        query = UserChannel._filter(guild, channel, member, webhooks, include_filtered)
        return query.all()

    @staticmethod
    def get_last(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks=False,
        include_filtered=False,
    ) -> UserChannel:
        """Gets UserChannel item with the last `last_msg_at` attribute with applied optional filters.

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting item
        """
        query = UserChannel._filter(guild, channel, member, webhooks, include_filtered)
        return query.order_by(desc(UserChannel.last_msg_at)).first()

    @staticmethod
    def _get_user_query(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> Query:
        """Gets ranked query for user counts.

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting query
        """
        last_msg_at = func.max(UserChannel.last_msg_at).label("last_msg_at")
        total = func.sum(UserChannel.count).label("total")
        rank = (
            func.dense_rank()
            .over(order_by=[desc(total), asc(last_msg_at)])
            .label("rank")
        )

        query = session.query(
            UserChannel.guild_id,
            UserChannel.guild_name,
            UserChannel.user_id,
            UserChannel.user_name,
            last_msg_at,
            total,
            rank,
        )
        query = UserChannel._filter(
            query=query,
            guild=guild,
            channel=channel,
            member=member,
            webhooks=webhooks,
            include_filtered=include_filtered,
        )
        query = query.group_by(
            UserChannel.guild_id,
            UserChannel.guild_name,
            UserChannel.user_id,
            UserChannel.user_name,
        ).order_by("rank")

        return query

    @staticmethod
    def _get_channel_query(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> Query:
        """Gets ranked query for channel counts.

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting query
        """
        last_msg_at = func.max(UserChannel.last_msg_at).label("last_msg_at")
        total = func.sum(UserChannel.count).label("total")
        rank = (
            func.dense_rank()
            .over(order_by=[desc(total), asc(last_msg_at)])
            .label("rank")
        )
        query = session.query(
            UserChannel.guild_id,
            UserChannel.guild_name,
            UserChannel.channel_id,
            UserChannel.channel_name,
            last_msg_at,
            total,
            rank,
        )
        query = UserChannel._filter(
            query=query,
            guild=guild,
            channel=channel,
            member=member,
            webhooks=webhooks,
            include_filtered=include_filtered,
        )
        query = query.group_by(
            UserChannel.guild_id,
            UserChannel.guild_name,
            UserChannel.channel_id,
            UserChannel.channel_name,
        ).order_by("rank")

        return query

    @staticmethod
    def get_user_counts(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> List[UserChannel]:
        """Gets list of ranked user counts.

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting list
        """
        query = UserChannel._get_user_query(
            guild=guild,
            channel=channel,
            channel=channel,
            webhooks=webhooks,
            include_filtered=include_filtered,
        )
        return query.all()

    @classmethod
    def get_channel_counts(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> List[UserChannel]:
        """Gets list of ranked channel counts.

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting list
        """
        query = UserChannel._get_channel_query(
            guild=guild,
            channel=channel,
            member=member,
            webhooks=webhooks,
            include_filtered=include_filtered,
        )
        return query.all()

    @classmethod
    def get_user_ranked(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> UserChannel:
        """Gets ranked user

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting item
        """
        subquery = UserChannel._get_user_query(
            guild=guild,
            channel=channel,
            webhooks=webhooks,
            include_filtered=include_filtered,
        ).subquery()
        query = session.query(subquery).filter(subquery.c.user_id == member.id)
        result = query.one_or_none()
        return result

    @classmethod
    def get_channel_ranked(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> UserChannel:
        """Gets ranked channel

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Resulting item
        """
        subquery = UserChannel._get_channel_query(
            guild=guild,
            member=member,
            webhooks=webhooks,
            include_filtered=include_filtered,
        ).subquery()
        query = session.query(subquery).filter(subquery.c.channel_id == channel.id)
        result = query.first()
        return result

    @classmethod
    def get_user_sum(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> int:
        """Gets total user result count

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Number of items
        """
        query = UserChannel._filter(
            guild=guild,
            channel=channel,
            member=member,
            webhooks=webhooks,
            include_filtered=include_filtered,
        )
        result = query.count()
        return result

    @classmethod
    def get_channel_sum(
        guild: discord.Guild = None,
        channel: discord.TextChannel = None,
        member: discord.Member = None,
        webhooks: bool = False,
        include_filtered: bool = False,
    ) -> int:
        """Gets total channel result count

        Args:
            guild: The guild to filter by. Defaults to None.
            channel: The channel to filter by. Defaults to None.
            member: The guild object to filter by. Defaults to None.
            webhooks: Whether webhook items should be returned. Defaults to False.
            include_filtered: Whether filtered items should be returned. Defaults to False.

        Returns:
            Number of items
        """
        query = UserChannel._filter(
            guild=guild,
            channel=channel,
            member=member,
            webhooks=webhooks,
            include_filtered=include_filtered,
        )
        result = query.count()
        return result

    def save(self):
        """Commits the UserChannel to the database."""
        session.commit()

    def __repr__(self):
        return (
            f'<UserChannel idx="{self.idx}" '
            f'guild_id="{self.guild_id}" channel_id="{self.channel_id}" '
            f'channel_name="{self.channel_name}" user_id="{self.user_id}" '
            f'user_name="{self.user_name}" is_webhook="{self.is_webhook}"'
            f'count="{self.user_id}" last_msg_at="{self.is_webhook}">'
        )

    def dump(self) -> Dict:
        """Dumps UserChannel into a dictionary.

        Returns:
            The UnverifyItem as a dictionary.
        """
        return {
            "idx": self.idx,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "channel_name": self.channel_name,
            "user_name": self.user_name,
            "is_webhook": self.is_webhook,
            "count": self.count,
            "last_msg_at": self.last_msg_at,
        }
