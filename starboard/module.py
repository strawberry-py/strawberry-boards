import discord
from discord.ext import commands

from pie.bot import Strawberry

from ..karma.module import Karma


class Starboard(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


async def setup(bot: Strawberry) -> None:
    await bot.add_cog(Starboard(bot))
