import datetime
import random
from typing import Union, Dict

import discord
from discord.ext import commands, tasks

import database.config
from core import utils, i18n, TranslationContext, check

from .database import UserStats, BoardOrder

_ = i18n.Translator("modules/boards").translate
config = database.config.Config.get()

LIMITS_MESSAGE = [15, 25]
LIMITS_REACTION = [0, 5]

TIMER_MESSAGE = 60
TIMER_REACTION = 30


class Points(commands.Cog):
    """Get points by having conversations"""

    def __init__(self, bot):
        self.bot = bot

        self.stats_message = {}
        self.stats_reaction = {}

        self.cleanup.start()

    # Commands

    @commands.guild_only()
    @commands.group(name="points")
    @commands.check(check.spamchannel)
    async def points(self, ctx):
        """Get information about user points"""
        await utils.Discord.send_help(ctx)

    @points.command(name="get")
    async def points_get(self, ctx, member: discord.Member = None):
        """Get user points"""
        if member is None:
            member = ctx.author

        result = UserStats.get_stats(ctx.guild.id, member.id)

        embed = utils.Discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Points"),
            description=_(ctx, "**{user}'s** points").format(
                user=utils.Text.sanitise(member.display_name)
            ),
        )
        points = getattr(result, "points", 0)
        message = "**{points}** ({position}.)".format(
            points=points, position=UserStats.get_position(ctx.guild.id, points)
        )

        embed.set_thumbnail(url=member.display_avatar.replace(size=256).url)
        embed.add_field(
            name=_(ctx, "Points and ranking"),
            value=_(ctx, message),
        )
        await ctx.send(embed=embed)
        await utils.Discord.delete_message(ctx.message)

    @points.command(name="leaderboard", aliases=["best"])
    async def points_leaderboard(self, ctx):
        """Points leaderboard"""
        embed = utils.Discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Points 🏆"),
            description=_(ctx, "Score, descending"),
        )

        users = UserStats.get_best(ctx.guild.id, BoardOrder.DESC, 10, offset=0)
        value = Points._get_board(ctx.guild, ctx.author, users)

        embed.add_field(
            name=_(ctx, "Top {limit}").format(limit=10),
            value=value,
            inline=False,
        )

        # if the user is not present, add them to second field
        if ctx.author.id not in [u.user_id for u in users]:
            author = UserStats.get_stats(ctx.guild.id, ctx.author.id)

            embed.add_field(
                name=_(ctx, "Your score"),
                value="`{points:>8}` … {name}".format(
                    points=author.points,
                    name="**" + utils.Text.sanitise(ctx.author.display_name) + "**",
                ),
                inline=False,
            )

        message = await ctx.send(embed=embed)
        await message.add_reaction("⏪")
        await message.add_reaction("◀")
        await message.add_reaction("▶")
        await utils.Discord.delete_message(ctx.message)

    @points.command(name="loserboard", aliases=["worst"])
    async def points_loserboard(self, ctx):
        """Points loserboard"""
        embed = utils.Discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Points 💩"),
            description=_(ctx, "Score, ascending"),
        )

        users = UserStats.get_best(ctx.guild.id, BoardOrder.ASC, limit=10, offset=0)
        value = Points._get_board(ctx.guild, ctx.author, users)

        embed.add_field(
            name=_(ctx, "Worst {limit}").format(limit=10),
            value=value,
            inline=False,
        )

        # if the user is not present, add them to second field
        if ctx.author.id not in [u.user_id for u in users]:
            author = UserStats.get_stats(ctx.guild.id, ctx.author.id)

            embed.add_field(
                name=_(ctx, "Your score"),
                value="`{points:>8}` … {name}".format(
                    points=author.points,
                    name="**" + utils.Text.sanitise(ctx.author.display_name) + "**",
                ),
                inline=False,
            )

        message = await ctx.send(embed=embed)
        await message.add_reaction("⏪")
        await message.add_reaction("◀")
        await message.add_reaction("▶")
        await utils.Discord.delete_message(ctx.message)

    # Listeners

    @commands.Cog.listener()
    async def on_message(self, message):
        """Add points on message"""
        if message.author.bot:
            return

        # Ignore DMs
        if not isinstance(message.channel, discord.TextChannel):
            return

        value = random.randint(LIMITS_MESSAGE[0], LIMITS_MESSAGE[1])

        Points._handle_points(
            message.guild.id,
            message.author.id,
            self.stats_message,
            TIMER_MESSAGE,
            value,
        )

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Handle board scrolling"""
        if user.bot:
            return

        if getattr(reaction.message, "guild", None) is None:
            return

        # add points
        guild_id = reaction.message.guild.id

        value = random.randint(LIMITS_REACTION[0], LIMITS_REACTION[1])

        Points._handle_points(
            guild_id, user.id, self.stats_reaction, TIMER_REACTION, value
        )

        if str(reaction) not in ("⏪", "◀", "▶"):
            return

        tc = TranslationContext(guild_id, reaction.message.author.id)

        if (
            len(reaction.message.embeds) != 1
            or type(reaction.message.embeds[0].title) != str
            or (
                not reaction.message.embeds[0].title.startswith(_(tc, "Points 🏆"))
                and not reaction.message.embeds[0].title.startswith(_(tc, "Points 💩"))
            )
        ):
            return

        embed = reaction.message.embeds[0]

        # get ordering
        if embed.title == _(tc, "Points 💩"):
            order = BoardOrder.ASC
        else:
            order = BoardOrder.DESC

        # get current offset
        if ", " in embed.fields[0].name:
            offset = int(embed.fields[0].name.split(" ")[-1]) - 1
        else:
            offset = 0

        # get new offset
        if str(reaction) == "⏪":
            offset = 0
        elif str(reaction) == "◀":
            offset -= 10
        elif str(reaction) == "▶":
            offset += 10

        if offset < 0:
            return await utils.Discord.remove_reaction(reaction.message, reaction, user)

        users = UserStats.get_best(guild_id, order, 10, offset)
        value = Points._get_board(reaction.message.guild, user, users)
        if not value:
            # offset too big
            return await utils.Discord.remove_reaction(reaction.message, reaction, user)

        if order == BoardOrder.DESC:
            table_name = _(tc, "Best {limit}")
        else:
            table_name = _(tc, "Worst {limit}")

        name = table_name.format(limit=10)

        if offset:
            name += _(tc, ", position {offset}").format(offset=offset + 1)

        embed.clear_fields()
        embed.add_field(name=name, value=value, inline=False)

        # if the user is not present, add them to second field
        if user.id not in [u.user_id for u in users]:
            author = UserStats.get_stats(guild_id, user.id)

            embed.add_field(
                name=_(tc, "Your score"),
                value="`{points:>8}` … {name}".format(
                    points=author.points,
                    name="**" + utils.Text.sanitise(user.display_name) + "**",
                ),
                inline=False,
            )

        await reaction.message.edit(embed=embed)
        await utils.Discord.remove_reaction(reaction.message, reaction, user)

    # Helper functions

    @staticmethod
    def _get_board(
        guild: discord.Guild,
        author: Union[discord.User, discord.Member],
        users: list,
        offset: int = 0,
    ) -> str:
        result = []
        template = "`{points:>8}` … {name}"
        ctx = TranslationContext(guild.id, author.id)
        for db_user in users:
            user = guild.get_member(db_user.user_id)
            if user and user.display_name:
                name = utils.Text.sanitise(user.display_name, limit=1900)
            else:
                name = _(ctx, "Unknown")

            if db_user.user_id == author.id:
                name = "**" + name + "**"

            result.append(template.format(points=db_user.points, name=name))
        return "\n".join(result)

    @staticmethod
    def _handle_points(
        guild_id: int, user_id: int, stats: Dict, timer: int, value: int
    ):
        now = datetime.datetime.now()
        if guild_id not in stats:
            stats[guild_id] = {}

        if (
            user_id not in stats[guild_id]
            or (now - stats[guild_id][user_id]).total_seconds() >= timer
        ):
            stats[guild_id][user_id] = now
            UserStats.increment(guild_id, user_id, value)

    # Tasks

    @tasks.loop(seconds=120.0)
    async def cleanup(self):
        for guild in self.stats_message.keys():
            delete = []
            for uid, time in self.stats_message[guild].items():
                if (datetime.datetime.now() - time).total_seconds() >= TIMER_MESSAGE:
                    delete.append(uid)
            for uid in delete:
                self.stats_message[guild].pop(uid)

        for guild in self.stats_reaction.keys():
            delete = []
            for uid, time in self.stats_reaction[guild].items():
                if (datetime.datetime.now() - time).total_seconds() >= TIMER_REACTION:
                    delete.append(uid)

            for uid in delete:
                self.stats_reaction[guild].pop(uid)


def setup(bot) -> None:
    bot.add_cog(Points(bot))
