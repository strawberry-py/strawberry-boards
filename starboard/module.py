import asyncio
import os
import re
from types import SimpleNamespace
from typing import Optional, Union
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from pie import check, i18n, utils
from pie.bot import Strawberry, logger

from ..karma.module import Karma
from .database import StarboardChannel, StarboardMessage

ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp"]
URL_REGEX = r"^https{0,1}:\/\/\S*"

bot_log = logger.Bot.logger()
guild_log = logger.Guild.logger()

_ = i18n.Translator("modules/boards").translate


class Starboard(commands.Cog):

    starboard: app_commands.Group = app_commands.Group(
        name="starboard",
        description="Starboard stats.",
        default_permissions=discord.Permissions(read_message_history=True),
    )

    starboard_admin: app_commands.Group = app_commands.Group(
        name="starboardadmin",
        description="Starboard administration and management.",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot: Strawberry = bot
        self.starboard_channels = []
        self.source_channels = []
        self._reaction_lock = asyncio.Lock()
        self._reaction_processing = []

        for sb_channel in StarboardChannel.get_all():
            self.starboard_channels.append(sb_channel.starboard_channel_id)
            self.source_channels.append(sb_channel.source_channel_id)

    # Listeners

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, reaction: discord.RawReactionActionEvent):
        """Handle added reactions."""
        if reaction.channel_id in self.source_channels:
            await self._process_reaction(reaction)
        elif reaction.channel_id in self.starboard_channels:
            await self._proxy_karma(reaction, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, reaction: discord.RawReactionActionEvent):
        """Handle removed reactions."""
        if reaction.channel_id in self.starboard_channels:
            await self._proxy_karma(reaction, added=False)

    # Commands

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MOD)
    @starboard_admin.command(
        name="list",
        description="List starboard channels and it's configuration.",
    )
    async def starboard_admin_list(
        self, itx: discord.Interaction, starboard: discord.TextChannel = None
    ):
        sb_channels: list[StarboardChannel] = StarboardChannel.get_all(
            guild_id=itx.guild_id,
            starboard_channel_id=starboard.id if starboard else None,
        )

        if len(sb_channels) == 0:
            await itx.response.send_message(
                content=_(itx, "No starboard channel found!"), ephemeral=True
            )
            return

        channels = []

        for sb_channel in sb_channels:
            # Dummy instance to hold the data for table_pages
            source_channel = self.bot.get_channel(sb_channel.source_channel_id)
            starboard_channel = self.bot.get_channel(sb_channel.starboard_channel_id)
            channel = SimpleNamespace(
                source_id=sb_channel.source_channel_id,
                source_name=source_channel.name if source_channel else "?",
                starboard_id=sb_channel.starboard_channel_id,
                starboard_name=starboard_channel.name if starboard_channel else "?",
                limit=sb_channel.limit,
            )
            channels.append(channel)

        table_pages: list[str] = utils.text.create_table(
            channels,
            {
                "source_id": _(itx, "Source channel ID"),
                "source_name": _(itx, "Source channel"),
                "starboard_id": _(itx, "Starboard channel ID"),
                "starboard_name": _(itx, "Starboard channel"),
                "limit": _(itx, "Limit"),
            },
        )
        await itx.response.send_message(content="```" + table_pages[0] + "```")
        for table_page in table_pages[1:]:
            await itx.followup.send("```" + table_page + "```")

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MOD)
    @starboard_admin.command(
        name="set", description="Add or changes starboard channel configuration."
    )
    @app_commands.describe(
        source="Channel to monitor for reactions.",
        starboard="Channel to repost the message.",
        limit="Minimal amount of (positive) reactions to repost the message.",
    )
    async def starboard_admin_set(
        self,
        itx: discord.Interaction,
        source: discord.TextChannel,
        starboard: discord.TextChannel,
        limit: int,
    ):
        if limit <= 0:
            await itx.response.send_message(
                content=_(itx, "Limit must be higher than 0!"), ephemeral=True
            )
            return

        if not StarboardChannel.check_unique(itx.guild.id, source.id):
            await itx.response.send_message(
                content=_(
                    itx, "Source channel is already in use as source or starboard!"
                ),
                ephemeral=True,
            )
            return

        if StarboardChannel.get(guild_id=itx.guild.id, source_channel_id=starboard.id):
            await itx.response.send_message(
                content=_(itx, "Starboard channel is already in use as source!"),
                ephemeral=True,
            )
            return

        StarboardChannel.set(
            guild_id=itx.guild.id,
            source_channel_id=source.id,
            starboard_channel_id=starboard.id,
            limit=limit,
        )

        self.source_channels.append(source.id)
        self.starboard_channels.append(starboard.id)

        await itx.response.send_message(
            content=_(
                itx,
                "Starboard configured to repost messages from {source_channel} to {starboard_channel} when reaching {limit} reactions.",
            ).format(
                source_channel=source.mention,
                starboard_channel=starboard.mention,
                limit=limit,
            ),
            ephemeral=True,
        )

        await guild_log.info(
            itx.user,
            itx.channel,
            f"Channel {source.name} added as source for Starboard channel {starboard.name} with limit {limit}.",
        )

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MOD)
    @starboard_admin.command(
        name="unset", description="Unset starboard channel and it's configuration."
    )
    @app_commands.describe(
        source="Channel to monitor for reactions.",
    )
    async def starboard_admin_unset(
        self,
        itx: discord.Interaction,
        source: discord.TextChannel = None,
        source_id: str = None,
    ):
        # NOT XOR - only one of the must have value
        if not (bool(source) ^ bool(source_id)):
            await itx.response.send_message(
                content=_(
                    itx,
                    "Exactly one of the parameters `source` or `source_id` must be specified!",
                ),
                ephemeral=True,
            )
            return

        if source:
            source_id = source.id
        else:
            try:
                source_id = int(source_id)
            except ValueError:
                await itx.response.send_message(
                    content=_(
                        itx,
                        "Argument `source_id` is not valid channel ID!",
                    ),
                    ephemeral=True,
                )

        sb_channel: StarboardChannel = StarboardChannel.get(
            guild_id=itx.guild_id, source_channel_id=source_id
        )

        if not sb_channel:
            await itx.response.send_message(
                content=_(itx, "Channel {channel} is not configured as source!").format(
                    channel=source.mention if source else source_id
                ),
                ephemeral=True,
            )
            return

        self.source_channels.remove(sb_channel.source_channel_id)
        self.starboard_channels.remove(sb_channel.starboard_channel_id)

        await guild_log.info(
            itx.user,
            itx.channel,
            f"Channel {source.name if source else source_id} removed as source from Starboard.",
        )

        sb_channel.remove()

        await itx.response.send_message(
            content=_(itx, "Channel {channel} was unset as source!").format(
                channel=source.mention if source else source_id
            ),
            ephemeral=True,
        )

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MOD)
    @starboard_admin.command(
        name="history",
        description="Checks the channel's latest messages for repost potential.",
    )
    @app_commands.describe(
        source="Source channel to check the history.",
        limit="Amount of messages to check.",
    )
    async def starboard_admin_history(
        self, itx: discord.Interaction, source: discord.TextChannel, limit: int = 300
    ):
        sb_channel = StarboardChannel.get(
            guild_id=itx.guild.id, source_channel_id=source.id
        )

        if not sb_channel:
            await itx.response.send_message(
                content=_(
                    itx, "Channel {channel} is not Starboard source channel!"
                ).format(channel=source.mention),
                ephemeral=True,
            )
            return

        await itx.response.defer(thinking=True, ephemeral=True)
        async for message in source.history(limit=limit, oldest_first=True):
            fake_emoji = discord.PartialEmoji(name="\u2764\uFE0F")

            data = {
                "user_id": itx.user.id,
                "channel_id": source.id,
                "message_id": message.id,
                "emoji": fake_emoji,
                "guild_id": itx.guild.id,
                "type": discord.enums.ReactionType.normal,
            }
            event = discord.RawReactionActionEvent(
                data=data, emoji=fake_emoji, event_type="REACTION_ADD"
            )
            await self._process_reaction(reaction=event)

        await (await itx.original_response()).edit(
            content=_(
                itx,
                "History for channel {channel} checked, processed {limit} messages.",
            ).format(channel=source.mention, limit=limit)
        )

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MEMBER)
    @starboard.command(
        name="leaderboard", description="Lists the most starboarded users."
    )
    async def starboard_leaderboard(
        self, itx: discord.Interaction, source: discord.TextChannel = None
    ):
        await itx.response.send_message(
            content=_(itx, "Not implemented yet."), ephemeral=True
        )
        # TODO

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MEMBER)
    @starboard.command(name="stats", description="Display user's Starboard stats.")
    async def starboard_info(
        self, itx: discord.Interaction, member: discord.User = None
    ):
        await itx.response.defer(thinking=True)
        member: Union[discord.User, discord.Member] = member if member else itx.user
        db_stats: list[tuple[int, int]] = StarboardMessage.get_author_stats(
            guild_id=itx.guild.id, author_id=member.id
        )

        if not db_stats:
            await (await itx.original_response()).edit(
                content=_(
                    itx,
                    "No stats found for {member}",
                ).format(member=member.display_name)
            )
            return

        embed: discord.Embed = await self._get_user_embed(itx, member, db_stats)

        await (await itx.original_response()).edit(embed=embed)

    # Helper functions

    async def _get_user_embed(
        self,
        itx: discord.Interaction,
        member: Union[discord.User, discord.Member],
        stats: list[tuple[int, int]],
    ) -> discord.Embed:
        embed = utils.discord.create_embed(
            author=itx.user,
            title=_(itx, "Starboard stats for {name}").format(name=member.display_name),
        )

        total: int = 0
        lines = []

        for channel_id, count in stats:
            if len(lines) == 10:
                lines.append("...")
                break
            channel: discord.TextChannel = self.bot.get_channel(channel_id)
            channel_mention: str = channel.mention if channel else f"({channel_id})"
            total += count

            line = f"{channel_mention} … `{count:>6}`"
            lines.append(line)

        embed.add_field(name=_(itx, "Starboard channels"), value="\n".join(lines), inline=False)
        embed.add_field(name=_(itx, "Total starboarded messages"), value=total, inline=False)

        return embed

    async def _proxy_karma(self, reaction: discord.RawReactionActionEvent, added: bool):
        messages: StarboardMessage = StarboardMessage.get_all(
            guild_id=reaction.guild_id, starboard_message_id=reaction.message_id
        )
        if not messages:
            return
        message: StarboardMessage = messages[0]

        karma: Karma = self.bot.get_cog("Karma")
        if not karma:
            return

        if message.author_id == reaction.user_id:
            return

        emoji_value = karma.get_emoji_value(
            guild_id=reaction.guild_id, emoji=reaction.emoji
        )

        if emoji_value == 0:
            return

        if added:
            karma.reaction_added(
                guild_id=reaction.guild_id,
                msg_author_id=message.author_id,
                react_author_id=reaction.user_id,
                emoji_value=emoji_value,
            )
        else:
            karma.reaction_removed(
                guild_id=reaction.guild_id,
                msg_author_id=message.author_id,
                react_author_id=reaction.user_id,
                emoji_value=emoji_value,
            )

    async def _process_reaction(self, reaction: discord.RawReactionActionEvent):
        async with self._reaction_lock:
            if reaction.message_id in self._reaction_processing:
                return

            sb_message: StarboardMessage = StarboardMessage.get_all(
                guild_id=reaction.guild_id, source_message_id=reaction.message_id
            )
            if sb_message:
                return

            self._reaction_processing.append(reaction.message_id)

        message: discord.Message = None
        try:
            message = await utils.discord.get_message(
                bot=self.bot,
                guild_or_user_id=reaction.guild_id,
                channel_id=reaction.channel_id,
                message_id=reaction.message_id,
            )
        except Exception:
            pass

        if not message:
            self._reaction_processing.remove(reaction.message_id)
            return

        sb_db_channel = StarboardChannel.get(
            guild_id=reaction.guild_id, source_channel_id=reaction.channel_id
        )

        m_reaction: discord.Reaction

        for m_reaction in message.reactions:
            if m_reaction.count < sb_db_channel.limit:
                continue

            if (
                self.bot.get_cog("Karma")
                and Karma.get_emoji_value(message.guild.id, m_reaction.emoji) < 1
            ):
                continue

            await self._repost_message(
                channel_id=sb_db_channel.starboard_channel_id, message=message
            )

            await guild_log.info(
                None,
                message.channel,
                f"Message {message.jump_url} reached limit {sb_db_channel} reactions. Reposted to {sb_db_channel.starboard_channel_id}.",
            )
            break

        self._reaction_processing.remove(message.id)

    async def _repost_message(self, channel_id: int, message: discord.Message):
        sb_channel: discord.TextChannel = self.bot.get_channel(channel_id)

        if sb_channel is None:
            await guild_log.warning(
                None,
                None,
                f"Starboard can't find channel {channel_id} set up for channel {channel_id}!",
            )
            return

        starboard_messages: list[discord.Message] = await self._send_messages(
            channel=sb_channel, message=message
        )
        for starboard_message in starboard_messages:
            StarboardMessage.add(
                guild_id=message.guild.id,
                author_id=message.author.id,
                source_channel_id=message.channel.id,
                source_message_id=message.id,
                starboard_channel_id=starboard_message.channel.id,
                starboard_message_id=starboard_message.id,
            )

    async def _process_attachments(
        self, attachments: list[discord.Attachment], msg_content: str
    ) -> tuple[Optional[Union[discord.File, str]], Union[str, discord.File]]:
        embed_image = None
        secondary_attachments = []
        for attachment in attachments:
            attachment_file = await attachment.to_file()

            if (
                attachment.content_type is not None
                and attachment.content_type.startswith("image/")
            ):
                if not embed_image:
                    if not attachment.is_spoiler():
                        embed_image = attachment_file
                        continue
            secondary_attachments.append(attachment_file)

        for url in re.findall(URL_REGEX, msg_content):
            if not embed_image:
                extension: str = os.path.splitext(urlparse(url).path)[1:][0]
                if len(extension) and extension.lower() in ALLOWED_EXTENSIONS:
                    embed_image = url
                    continue
            secondary_attachments.append(url)

        return (embed_image, secondary_attachments)

    async def _send_messages(
        self, channel: discord.TextChannel, message: discord.Message
    ) -> list[discord.Message]:
        embed = utils.discord.create_embed(
            author=message.author,
            color=discord.Colour.yellow(),
            title=Starboard._get_title(message.reactions),
        )
        embed.timestamp = message.created_at
        embed.add_field(
            name="Link:",
            value=f"[Original]({message.jump_url}) - <#{message.channel.id}>",
            inline=False,
        )

        embed_image, sec_attachments = await self._process_attachments(
            attachments=message.attachments, msg_content=message.content
        )
        if embed_image is not None:
            embed.set_image(
                url=(
                    f"attachment://{embed_image.filename}"
                    if isinstance(embed_image, discord.File)
                    else embed_image if isinstance(embed_image, str) else None
                )
            )

        text: str = re.sub(URL_REGEX, "", message.content).strip()
        if text and len(embed) + len(text) < 5800:
            embed.add_field(name="Text:", value=text, inline=False)

        messages: list[discord.Message] = []
        try:
            messages.append(await channel.send(embed=embed, file=embed_image))
        except Exception as e:
            await guild_log.error(
                None,
                None,
                f"Starboard can't send message to {channel.id}!",
                exception=e,
            )
            return []

        sec_message = await self._send_secondary(
            channel=channel, sec_attachments=sec_attachments
        )
        if sec_message:
            messages.append(sec_message)

        return messages

    async def _send_secondary(
        self,
        channel: discord.TextChannel,
        sec_attachments: list[Union[discord.File, str]],
    ) -> Optional[discord.Message]:
        if len(sec_attachments) > 0:
            files = [file for file in sec_attachments if isinstance(file, discord.File)]
            urls = [url for url in sec_attachments if isinstance(url, str)]
            sec_mess_text = urls[0] if urls else None
            for url in urls[1:]:
                if len(sec_mess_text) + len(url) >= 2000:
                    break
                sec_mess_text += f"\n{url}"
            message = None
            try:
                message = await channel.send(content=sec_mess_text, files=files[:10])
            except Exception as e:
                await guild_log.error(
                    None,
                    None,
                    f"Starboard can't send secondary message to {channel.id}!",
                    exception=e,
                )
            return message

    @staticmethod
    def _get_title(reactions: list[discord.Reaction]) -> str:
        title_parts: list[str] = [
            f"{reaction.emoji}{reaction.count}"
            for reaction in reactions
            if not isinstance(reaction.emoji, discord.PartialEmoji)
        ]
        title: str = ""
        for title_part in title_parts:
            if len(title) + len(title_part) > 254:
                break
            title += f" {title_part}"

        return title


async def setup(bot: Strawberry) -> None:
    await bot.add_cog(Starboard(bot))
