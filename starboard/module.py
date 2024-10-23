import asyncio
import os
import re
from typing import Optional, Union
from urllib.parse import urlparse

from database import StarboardChannel, StarboardMessage

import discord
from discord.ext import commands

from pie import utils
from pie.bot import Strawberry, logger

from ..karma.module import Karma

bot_log = logger.Bot.logger()
guild_log = logger.Guild.logger()

ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp"]
URL_REGEX = r"^https{0,1}:\/\/\S*"


class Starboard(commands.Cog):

    def __init__(self, bot):
        self.bot: Strawberry = bot
        self.starboard_channels = []
        self.source_channels = []
        self._reaction_lock = asyncio.Lock()
        self._reaction_processing = []

    # Listeners

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, reaction: discord.RawReactionActionEvent):
        """Handle added reactions."""
        if reaction.channel_id in self.source_channels:
            await self._process_reaction(self, reaction)
        elif reaction.channel_id in self.starboard_channels:
            await self._proxy_karma(self, reaction, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, reaction: discord.RawReactionActionEvent):
        """Handle removed reactions."""
        if reaction.channel_id in self.starboard_channels:
            await self._proxy_karma(self, reaction, added=False)

    # Commands

    pass

    # Helper functions

    async def _proxy_karma(self, reaction: discord.RawReactionActionEvent, added: bool):
        message: StarboardMessage = StarboardMessage.get(
            guild_id=reaction.guild_id, starboard_message_id=reaction.message_id
        )
        if not message:
            return

        karma: Karma = self.bot.get_cog(Karma.qualified_name)
        if not karma:
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
                react_author_id=reaction.member.id,
                emoji_value=emoji_value,
            )
        else:
            karma.reaction_removed(
                guild_id=reaction.guild_id,
                msg_author_id=message.author_id,
                react_author_id=reaction.member.id,
                emoji_value=emoji_value,
            )

    async def _process_reaction(self, reaction: discord.RawReactionActionEvent):
        async with self._reaction_lock:
            if reaction.message_id in self._reaction_processing:
                return

            sb_message: StarboardMessage = StarboardMessage.get(
                guild_id=reaction.guild_id, starboard_message_id=reaction.message_id
            )
            if sb_message is not None:
                return

            self._reaction_processing.append(reaction.message_id)

        message: discord.Message = None
        try:
            message = utils.discord.get_message(
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
                self.bot.get_cog(Karma.qualified_name)
                and Karma.get_emoji_value(m_reaction.emoji) < 1
            ):
                continue

            await self._repost_message(
                reaction=reaction, channel_id=sb_db_channel.starboard_channel_id
            )
            break

        self._reaction_processing.remove(message.id)

    async def _repost_message(self, channel_id: int, message: discord.Message):
        sb_channel: discord.TextChannel = self.bot.get_channel(id=channel_id)

        if sb_channel is None:
            guild_log.warning(
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
                starboard_chanenl_id=starboard_message.channel.id,
                starboard_message_id=starboard_message.id,
            )

    async def _process_attachments(
        self, attachments: list[discord.Attachment], msg_content: str
    ) -> tuple[Optional[str], Union[str, discord.File]]:
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

        embed_image_str: str = None
        if embed_image is not None:
            embed_image_str = (
                f"attachment://{embed_image.filename}"
                if isinstance(embed_image, discord.File)
                else embed_image if isinstance(embed_image, str) else None
            )

        return (embed_image_str, secondary_attachments)

    async def _send_messages(
        self, channel: discord.TextChannel, message: discord.Message
    ) -> list[discord.Message]:
        embed = utils.discord.create_embed(
            author=message.author,
            color=discord.Color.yellow,
            title=Starboard._get_title(message.reactions),
        )
        embed.timestamp = message.created_at
        embed.add_field(
            "Link:", f"[Original]({message.jump_url}) - <#{message.channel.id}>"
        )

        embed_image, sec_attachments = await self._process_attachments(
            attachments=message.attachments, msg_content=message.content
        )
        if embed_image:
            embed.set_image(url=embed_image)

        text: str = re.sub(URL_REGEX, "", message.content).strip()
        if text and len(embed) + len(text) < 5800:
            embed.add_field(name="Text:", value=text)

        messages: list[discord.Message] = []
        try:
            messages.append(await channel.send(embed=embed))
        except Exception as e:
            guild_log.error(
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
            sec_mess_text = urls[0] if urls.lenght() > 0 else None
            for url in urls[1:]:
                if len(sec_mess_text) + len(url) >= 2000:
                    break
                sec_mess_text += f"\n{url}"
            message = None
            try:
                message = await channel.send(content=sec_mess_text, files=files[:10])
            except Exception as e:
                guild_log.error(
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
            if not isinstance(reaction.emoji, str)
        ]
        title: str = ""
        for title_part in title_parts:
            if len(title) + len(title_part) < 255:
                break
            title += title_part

        return title


async def setup(bot: Strawberry) -> None:
    await bot.add_cog(Starboard(bot))
