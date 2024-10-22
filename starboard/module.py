import discord
from discord.ext import commands

from pie.bot import Strawberry

from database import StarboardMessage, StarboardSource

from ..karma.module import Karma


class Starboard(commands.Cog):

    def __init__(self, bot):
        self.bot: Strawberry = bot
        self.starboard_channels = []
        self.source_channels = []

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

    async def _process_reaction(reaction: discord.RawReactionActionEvent):
        pass


async def setup(bot: Strawberry) -> None:
    await bot.add_cog(Starboard(bot))
