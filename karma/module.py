import asyncio
import math
import re
from typing import List, Optional, Set, Tuple, Union

import discord
from discord.ext import commands, tasks

from pie import check, i18n, logger, utils

from .database import (
    BoardOrder,
    BoardType,
    DiscordEmoji,
    IgnoredChannel,
    KarmaMember,
    UnicodeEmoji,
)

_ = i18n.Translator("modules/boards").translate
bot_log = logger.Bot.logger()
guild_log = logger.Guild.logger()

EMOJI_REGEX = "^:[a-zA-Z0-9]+:$"


class Karma(commands.Cog):
    """Module uses custom cache that is dumped to DB once in a while
    to increase performance as the reaction might be added and immediately removed.

    The cache uses (guild_id, user_id) tuple as key.
    """

    def __init__(self, bot):
        self.bot = bot

        self.value_cache = {}
        self.given_cache = {}
        self.taken_cache = {}

        self.karma_cache_loop.start()

    # Karma cache

    @tasks.loop(seconds=30.0)
    async def karma_cache_loop(self) -> None:
        self._karma_cache_save()

    @karma_cache_loop.before_loop
    async def karma_cache_loop_before(self):
        """Wait until the bot is ready."""
        await self.bot.wait_until_ready()

    @karma_cache_loop.after_loop
    async def karma_cache_loop_after(self):
        if self.karma_cache_loop.is_being_cancelled():
            self._karma_cache_save()

    def _karma_cache_save(self):
        """Save the karma values in given interval."""
        value_cache = self.value_cache.copy()
        self.value_cache = {}
        given_cache = self.given_cache.copy()
        self.given_cache = {}
        taken_cache = self.taken_cache.copy()
        self.taken_cache = {}

        for (guild_id, member_id), delta in value_cache.items():
            member = KarmaMember.get_or_add(guild_id, member_id)
            member.value += delta
            member.save()

        for (guild_id, member_id), delta in given_cache.items():
            member = KarmaMember.get_or_add(guild_id, member_id)
            member.given += delta
            member.save()

        for (guild_id, member_id), delta in taken_cache.items():
            member = KarmaMember.get_or_add(guild_id, member_id)
            member.taken += delta
            member.save()

    # Listeners

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, reaction: discord.RawReactionActionEvent):
        """Handle added reactions."""
        await self._process_reaction(reaction=reaction, added=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, reaction: discord.RawReactionActionEvent):
        """Handle removed reactions."""
        await self._process_reaction(reaction=reaction, added=False)

    # Commands

    @commands.guild_only()
    @check.acl2(check.ACLevel.MEMBER)
    @commands.group(name="karma")
    async def karma_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="get")
    async def karma_get(self, ctx, member: Optional[discord.Member] = None):
        """Display karma information on some user."""
        if member is None:
            member = ctx.author
        kmember = KarmaMember.get_or_add(ctx.guild.id, member.id)

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "User karma"),
            description=utils.text.sanitise(member.display_name),
        )

        embed.add_field(
            name=_(ctx, "Karma"),
            value=f"**{kmember.value}** (#{kmember.value_position})",
            inline=False,
        )
        embed.add_field(
            name=_(ctx, "Karma given"),
            value=f"**{kmember.given}** (#{kmember.given_position})",
        )
        embed.add_field(
            name=_(ctx, "Karma taken"),
            value=f"**{kmember.taken}** (#{kmember.taken_position})",
        )

        avatar_url: str = member.display_avatar.replace(size=256).url
        embed.set_thumbnail(url=avatar_url)

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="emoji")
    async def karma_emoji(self, ctx, emoji: Union[discord.PartialEmoji, str]):
        """Display karma information on emoji."""
        if isinstance(emoji, discord.PartialEmoji):
            karma_emoji = DiscordEmoji.get(ctx.guild.id, emoji.id)
            emoji_url = emoji.url
        elif re.match(EMOJI_REGEX, emoji):
            found_emoji = discord.utils.get(
                ctx.guild.emojis, name=emoji.replace(":", "")
            )
            if not found_emoji:
                await ctx.reply(_(ctx, "Emoji {emoji} not found.").format(emoji=emoji))
                return

            karma_emoji = DiscordEmoji.get(ctx.guild.id, emoji.id)
            emoji_url = emoji.url

        else:
            karma_emoji = UnicodeEmoji.get(ctx.guild.id, emoji)
            emoji_url = None

        if not karma_emoji:
            await ctx.reply(_(ctx, "This emoji does not have karma value."))
            return

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Emoji karma"),
        )

        embed.add_field(name=_(ctx, "Karma value"), value=karma_emoji.value)

        embed.set_thumbnail(url=emoji_url)

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="emojis")
    async def karma_emojis(self, ctx):
        """Display karma emojis on this server."""
        emojis = DiscordEmoji.get_all(ctx.guild.id) + UnicodeEmoji.get_all(ctx.guild.id)
        if not emojis:
            await ctx.reply(_(ctx, "No emoji has karma value on this server."))
            return

        emojis_positive = [e for e in emojis if e.value > 0]
        emojis_neutral = [e for e in emojis if e.value == 0]
        emojis_negative = [e for e in emojis if e.value < 0]

        not_voted_emoji_ids: List[int] = []
        db_ids: Set[str] = set([e.emoji_id for e in DiscordEmoji.get_all(ctx.guild.id)])
        for emoji in ctx.guild.emojis:
            if emoji.id not in db_ids:
                not_voted_emoji_ids.append(emoji.id)

        missing_emojis: int = 0

        def format_emojis(
            emojis: List[Union[UnicodeEmoji, DiscordEmoji, int]]
        ) -> List[str]:
            """Format a list of emojis or emoji IDs."""
            nonlocal missing_emojis

            emoji_list = []
            for i, emoji in enumerate(emojis):
                if isinstance(emoji, UnicodeEmoji):
                    emoji_str = emoji.emoji
                if isinstance(emoji, DiscordEmoji):
                    emoji = emoji.emoji_id
                if isinstance(emoji, int):
                    guild_emoji: Optional[discord.Emoji] = self.bot.get_emoji(emoji)
                    if guild_emoji is None:
                        DiscordEmoji.remove(ctx.guild.id, emoji)
                        missing_emojis += 1
                        continue
                    emoji_str = str(guild_emoji)
                emoji_list.append(emoji_str)

            lines = [emoji_list[i : i + 8] for i in range(0, len(emoji_list), 8)]
            lines = [" ".join(line) for line in lines]

            messages = [lines[i : i + 3] for i in range(0, len(lines), 3)]
            messages = ["\n".join(message) for message in messages]

            return messages

        if len(emojis_positive):
            await ctx.send(_(ctx, "Emojis with positive karma"))
            for line in format_emojis(emojis_positive):
                if line:
                    await ctx.send(line)
        if len(emojis_neutral):
            await ctx.send(_(ctx, "Emojis with neutral karma"))
            for line in format_emojis(emojis_neutral):
                if line:
                    await ctx.send(line)
        if len(emojis_negative):
            await ctx.send(_(ctx, "Emojis with negative karma"))
            for line in format_emojis(emojis_negative):
                if line:
                    await ctx.send(line)
        if len(not_voted_emoji_ids):
            await ctx.send(_(ctx, "Emojis with no karma value"))
            for line in format_emojis(not_voted_emoji_ids):
                if line:
                    await ctx.send(line)

        if missing_emojis:
            await guild_log.info(
                ctx.author,
                ctx.channel,
                (
                    f"{missing_emojis} emojis were not found when "
                    "karma emojis were displayed. They have "
                    "been removed from the database."
                ),
            )

    @check.acl2(check.ACLevel.MOD)
    @karma_.command(name="vote")
    async def karma_vote(
        self, ctx, emoji: Optional[Union[discord.PartialEmoji, str]] = None
    ):
        """Vote over emoji's karma value."""
        await utils.discord.delete_message(ctx.message)

        if emoji is None:
            voted_ids = [e.emoji_id for e in DiscordEmoji.get_all(ctx.guild.id)]
            for guild_emoji in ctx.guild.emojis:
                if guild_emoji.id not in voted_ids:
                    emoji = guild_emoji
                    break

        if emoji is None:
            await ctx.author.send(
                _(ctx, "All server emojis have been assigned a karma value.")
            )
            return

        if emoji is not None and isinstance(emoji, discord.PartialEmoji):
            emoji = next((x for x in ctx.guild.emojis if x.id == emoji.id), None)
            if emoji is None:
                await ctx.author.send(_(ctx, "That emoji is not from this server."))
                return

        if isinstance(emoji, str) and re.match(EMOJI_REGEX, emoji):
            found_emoji = discord.utils.get(
                ctx.guild.emojis, name=emoji.replace(":", "")
            )
            if not found_emoji:
                await ctx.reply(_(ctx, "Emoji {emoji} not found.").format(emoji=emoji))
                return
            emoji = found_emoji

        emoji_name: str = getattr(emoji, "name", str(emoji))

        guild_size, time_limit, voter_limit = Karma._get_karma_vote_config(ctx.guild)
        await guild_log.debug(
            ctx.author,
            ctx.channel,
            f"Guild size is {guild_size}: "
            + f"karma vote takes {time_limit} minutes and {voter_limit} voters.",
        )

        gtx = i18n.TranslationContext(ctx.guild.id, None)
        message = (
            _(gtx, "Karma vote over the value of {emoji} started.")
            + "\n"
            + _(gtx, "The vote will run for **{minutes}** minutes.")
            + " "
            + _(gtx, "Required minimum vote count is **{count}**.")
        )

        vote_message = await ctx.send(
            message.format(emoji=str(emoji), minutes=time_limit, count=voter_limit)
        )

        # Set the value to zero, so we can run this command multiple times
        # without starting a vote over the same emoji over and over.
        if isinstance(emoji, discord.Emoji):
            DiscordEmoji.add(ctx.guild.id, emoji.id, 0)

        await guild_log.info(
            ctx.author, ctx.channel, f"Karma vote over emoji '{emoji_name}' started."
        )

        votes = {"🔼": 0, "0⃣": 0, "🔽": 0}
        emoji_labels = {"🔼": "+1", "0⃣": "0", "🔽": "-1"}
        for vote_option in votes.keys():
            await vote_message.add_reaction(vote_option)

        await asyncio.sleep(time_limit * 60)

        # Fetch updated message with the votes
        vote_message = await vote_message.channel.fetch_message(vote_message.id)
        for reaction in vote_message.reactions:
            if str(reaction.emoji) not in votes.keys():
                continue
            votes[reaction.emoji] = reaction.count - 1

        log_message: str = (
            f"Karma vote over emoji '{emoji_name}' ended: "
            + ", ".join(f"{v}x {emoji_labels[k]}" for k, v in votes.items())
            + "."
        )

        if sum(votes.values()) < voter_limit:
            await guild_log.info(
                ctx.author,
                ctx.channel,
                log_message + " Not enough votes, aborted.",
            )
            await ctx.send(
                _(gtx, "Vote over {emoji} failed (not enough votes).").format(
                    emoji=str(emoji)
                )
            )
            return

        result: Optional[int] = None
        if votes["🔼"] > votes["0⃣"] and votes["🔼"] > votes["🔽"]:
            result = 1
        elif votes["0⃣"] > votes["🔽"] and votes["0⃣"] > votes["🔼"]:
            result = 0
        elif votes["🔽"] > votes["0⃣"] and votes["🔽"] > votes["🔼"]:
            result = -1
        else:
            await guild_log.info(
                ctx.author,
                ctx.channel,
                log_message + " Inconclusive, aborted.",
            )
            await ctx.send(
                _(gtx, "Vote over {emoji} ended in a draw.").format(emoji=str(emoji))
            )
            return

        if isinstance(emoji, discord.Emoji):
            DiscordEmoji.add(ctx.guild.id, emoji.id, result)
        if isinstance(emoji, str):
            UnicodeEmoji.add(ctx.guild.id, emoji, result)

        await guild_log.info(
            ctx.author, ctx.channel, log_message + f" Setting to {result}."
        )
        await ctx.send(
            _(gtx, "Karma value of {emoji} is **{value}**.").format(
                emoji=str(emoji), value=result
            )
        )

    @check.acl2(check.ACLevel.MOD)
    @karma_.command(name="unset")
    async def karma_unset(self, ctx, emoji: Union[discord.PartialEmoji, str]):
        """Set emoji's karma value."""
        emoji_name: str
        if isinstance(emoji, discord.PartialEmoji):
            DiscordEmoji.remove(ctx.guild.id, emoji.id)
            emoji_name = emoji.name
        elif re.match(EMOJI_REGEX, emoji):
            found_emoji = discord.utils.get(
                ctx.guild.emojis, name=emoji.replace(":", "")
            )
            if not found_emoji:
                await ctx.reply(_(ctx, "Emoji {emoji} not found.").format(emoji=emoji))
                return
            DiscordEmoji.remove(ctx.guild.id, found_emoji.id)
            emoji_name = found_emoji.name
        else:
            UnicodeEmoji.remove(ctx.guild.id, emoji)
            emoji_name = emoji

        await guild_log.info(
            ctx.author, ctx.channel, f"Karma value of '{emoji_name}' unset."
        )
        await ctx.reply(_(ctx, "Emoji's karma value has been unset."))

    @check.acl2(check.ACLevel.MOD)
    @karma_.command(name="set")
    async def karma_set(self, ctx, emoji: Union[discord.PartialEmoji, str], value: int):
        """Set emoji's karma value."""
        if value not in (-1, 0, 1):
            await ctx.reply(_(ctx, "Usual values are only 1, 0 or -1."))

        emoji_name: str
        if isinstance(emoji, discord.PartialEmoji):
            DiscordEmoji.add(ctx.guild.id, emoji.id, value)
            emoji_name = emoji.name
        elif re.match(EMOJI_REGEX, emoji):
            found_emoji = discord.utils.get(
                ctx.guild.emojis, name=emoji.replace(":", "")
            )
            if not found_emoji:
                await ctx.reply(_(ctx, "Emoji {emoji} not found.").format(emoji=emoji))
                return
            DiscordEmoji.add(ctx.guild.id, found_emoji.id, value)
            emoji_name = found_emoji.name
        else:
            UnicodeEmoji.add(ctx.guild.id, emoji, value)
            emoji_name = emoji

        await guild_log.info(
            ctx.author, ctx.channel, f"Karma value of '{emoji_name}' set to {value}."
        )
        await ctx.reply(_(ctx, "The value has been set."))

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="message")
    async def karma_message(self, ctx, message: discord.Message):
        """Display total message karma."""
        if IgnoredChannel.get(message.guild.id, message.channel.id) is not None:
            await ctx.reply(_(ctx, "Karma is disabled in message's channel."))
            return

        message_karma: int = 0
        output = {"negative": [], "neutral": [], "positive": []}
        for reaction in message.reactions:
            if type(reaction.emoji) is discord.Emoji:
                emoji = DiscordEmoji.get(ctx.guild.id, reaction.emoji.id)
            elif type(reaction.emoji) is str:
                emoji = UnicodeEmoji.get(ctx.guild.id, reaction.emoji)
            else:
                # PartialEmoji which is not usable by the bot
                emoji = None

            if not emoji:
                continue

            emoji_to_append = (
                emoji.emoji
                if isinstance(emoji, UnicodeEmoji)
                else self.bot.get_emoji(emoji.emoji_id)
            )

            if emoji.value < 0:
                output["negative"].append(emoji_to_append)
                message_karma -= reaction.count
            elif emoji.value > 0:
                output["positive"].append(emoji_to_append)
                message_karma += reaction.count
            else:
                output["neutral"].append(emoji_to_append)

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Message karma"),
            description=_(
                ctx,
                "Total karma value of [the message]({link}) is {value} karma points.",
            ).format(link=message.jump_url, value=message_karma),
        )

        timestamp: str = utils.time.format_datetime(
            utils.time.id_to_datetime(message.id)
        )
        embed.add_field(
            name=timestamp,
            value=_(ctx, "**{user}** in #{channel}").format(
                user=utils.text.sanitise(message.author.display_name),
                channel=message.channel.name,
            ),
            inline=True,
        )

        if message.content:
            embed.add_field(
                name=_(ctx, "Message content"),
                value=message.content[:512],
                inline=False,
            )

        if output["positive"]:
            embed.add_field(
                name=_(ctx, "Positive reactions"),
                value=" ".join(str(e) for e in output["positive"]),
                inline=False,
            )
        if output["negative"]:
            embed.add_field(
                name=_(ctx, "Negative reactions"),
                value=" ".join(str(e) for e in output["negative"]),
                inline=False,
            )
        if output["neutral"]:
            embed.add_field(
                name=_(ctx, "Neutral reactions"),
                value=" ".join(str(e) for e in output["neutral"]),
                inline=False,
            )

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MOD)
    @karma_.command(name="give")
    async def karma_give(
        self, ctx, value: int, members: commands.Greedy[discord.Member]
    ):
        """Give some karma to multiple users."""
        if not members:
            await ctx.reply(_(ctx, "You have to specify at least one member."))
            return

        for member in members:
            user = KarmaMember.get_or_add(ctx.guild.id, member.id)
            user.value += value
            user.save()

        reply: str
        if len(members) == 1:
            reply = _(ctx, "Member {member} got {value} karma points.").format(
                member=utils.text.sanitise(member.name),
                value=value,
            )
        else:
            reply = _(ctx, "Every member got {value} karma points").format(
                value=value,
            )
        await ctx.reply(reply)

        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"{value} karma points added to " + ", ".join([m.name for m in members]),
        )

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="leaderboard")
    async def karma_leaderboard(self, ctx):
        """Display karma leaders."""
        embeds = Karma._create_embeds(
            ctx=ctx,
            title=_(ctx, "Karma leaderboard"),
            description=_(ctx, "Score, descending"),
            board=BoardType.value,
            order=BoardOrder.DESC,
        )

        if not embeds:
            await ctx.reply(_(ctx, "Karma data not yet available."))
            return

        scrollable = utils.ScrollableEmbed(ctx, embeds)
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="loserboard")
    async def karma_loserboard(self, ctx):
        """Display karma losers."""
        embeds = Karma._create_embeds(
            ctx=ctx,
            title=_(ctx, "Karma loserboard"),
            description=_(ctx, "Score, ascending"),
            board=BoardType.value,
            order=BoardOrder.ASC,
        )

        if not embeds:
            await ctx.reply(_(ctx, "Karma data not yet available."))
            return

        scrollable = utils.ScrollableEmbed(ctx, embeds)
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="givingboard")
    async def karma_givingboard(self, ctx):
        """Display karma givers."""
        embeds = Karma._create_embeds(
            ctx=ctx,
            title=_(ctx, "Karma givingboard"),
            description=_(ctx, "Score, descending"),
            board=BoardType.given,
            order=BoardOrder.DESC,
        )

        if not embeds:
            await ctx.reply(_(ctx, "Karma data not yet available."))
            return

        scrollable = utils.ScrollableEmbed(ctx, embeds)
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MEMBER)
    @karma_.command(name="takingboard")
    async def karma_takingboard(self, ctx):
        """Display karma takers."""
        embeds = Karma._create_embeds(
            ctx=ctx,
            title=_(ctx, "Karma takingboard"),
            description=_(ctx, "Score, descending"),
            board=BoardType.taken,
            order=BoardOrder.DESC,
        )

        if not embeds:
            await ctx.reply(_(ctx, "Karma data not yet available."))
            return

        scrollable = utils.ScrollableEmbed(ctx, embeds)
        await scrollable.scroll()

    @check.acl2(check.ACLevel.SUBMOD)
    @karma_.group(name="ignore")
    async def karma_ignore(self, ctx):
        """Manage channels where karma is disabled."""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.SUBMOD)
    @karma_ignore.command(name="list")
    async def karma_ignore_list(self, ctx):
        """List channels where karma is disabled."""
        ignored_channels = IgnoredChannel.get_all(ctx.guild.id)
        if not ignored_channels:
            await ctx.reply(_(ctx, "Karma is not ignored in any of the channels."))
            return

        channels = [ctx.guild.get_channel(c.channel_id) for c in ignored_channels]

        table_pages: List[str] = utils.text.create_table(
            channels,
            {
                "id": _(ctx, "Channel ID"),
                "name": _(ctx, "Channel name"),
            },
        )
        for table_page in table_pages:
            await ctx.send("```" + table_page + "```")

    @check.acl2(check.ACLevel.MOD)
    @karma_ignore.command(name="set")
    async def karma_ignore_set(self, ctx, channel: discord.TextChannel):
        """Ignore karma in supplied channel."""
        ignored_channel = IgnoredChannel.add(ctx.guild.id, channel.id)
        if ignored_channel is None:
            await ctx.reply(_(ctx, "Karma is already ignored in that channel."))
            return

        await guild_log.info(
            ctx.author, ctx.channel, f"Karma will be ignored in #{channel.name}"
        )
        await ctx.reply(
            _(ctx, "Karma will be ignored in {channel} from now on.").format(
                channel=channel.mention
            )
        )

    @check.acl2(check.ACLevel.MOD)
    @karma_ignore.command(name="unset")
    async def karma_ignore_unset(self, ctx, channel: discord.TextChannel):
        """Stop ignoring karma in supplied channel."""
        unignored_channel = IgnoredChannel.remove(ctx.guild.id, channel.id)
        if unignored_channel is None:
            await ctx.reply(_(ctx, "Karma is not ignored in that channel."))
            return

        await guild_log.info(
            ctx.author, ctx.channel, f"Karma won't be ignored in #{channel.name}"
        )
        await ctx.reply(
            _(ctx, "Karma will not be ignored in {channel} from now on.").format(
                channel=channel.mention
            )
        )

    # Functions

    async def _process_reaction(
        self, reaction: discord.RawReactionActionEvent, added: bool
    ):
        """Helper function for the reaction events.

        :param reaction: Raw Reaction event to process.
        :param added: If the reaction was added or removed."""
        if IgnoredChannel.get(reaction.guild_id, reaction.channel_id):
            return

        emoji_value: int = Karma.get_emoji_value(reaction.guild_id, reaction.emoji)

        if emoji_value == 0:
            return

        message: discord.Message = None
        try:
            message = await utils.discord.get_message(
                self.bot,
                reaction.guild_id,
                reaction.channel_id,
                reaction.message_id,
            )
        except discord.NotFound:
            pass

        if message is None:
            await guild_log.debug(
                reaction.user_id,
                reaction.channel_id,
                f"Message {reaction.message_id} not found on karma reaction add.",
            )
            return
        if added:
            await self.reaction_added(
                msg_author_id=message.author.id,
                react_author_id=reaction.user_id,
                emoji_value=emoji_value,
            )
        else:
            await self.reaction_removed(
                message_author=message.author.id,
                reaction_author=reaction.user_id,
                emoji_value=emoji_value,
            )

    async def reaction_added(
        self, guild_id: int, msg_author_id: int, react_author_id: int, emoji_value: int
    ):
        """Adds karma value using the cache (when reaction is added).

        :param guild_id: Guild ID of the reaction
        :param msg_author_id: Discord ID of message author
        :param react_author_id: Discord ID of reaction author
        :param emoji_value: Karma value of the emoji
        """
        msg_author = Karma.get_cache_key(guild_id, msg_author_id)
        react_author = Karma.get_cache_key(guild_id, react_author_id)

        self.value_cache.setdefault(msg_author, 0)
        self.value_cache[msg_author] += emoji_value

        if emoji_value > 0:
            self.given_cache.setdefault(react_author, 0)
            self.given_cache[react_author] += emoji_value
        else:
            self.taken_cache.setdefault(react_author, 0)
            self.taken_cache[react_author] += -emoji_value

    async def reaction_removed(
        self, guild_id: int, msg_author_id: int, react_author_id: int, emoji_value: int
    ):
        """Removes karma value using the cache (when reaction is removed).


        :param guild_id: Guild ID of the reaction
        :param msg_author_id: Discord ID of message author
        :param react_author_id: Discord ID of reaction author
        :param emoji_value: Karma value of the emoji
        """
        msg_author = Karma.get_cache_key(guild_id, msg_author_id)
        react_author = Karma.get_cache_key(guild_id, react_author_id)

        self.value_cache.setdefault(msg_author, 0)
        self.value_cache[msg_author] -= emoji_value

        if emoji_value > 0:
            self.given_cache.setdefault(react_author, 0)
            self.given_cache[react_author] -= emoji_value
        else:
            self.taken_cache.setdefault(react_author, 0)
            self.taken_cache[react_author] -= -emoji_value

    # Static helper functions

    @staticmethod
    def _create_embeds(
        *,
        ctx: commands.Context,
        title: str,
        description: str,
        board: BoardType,
        order: BoardOrder,
        item_count: int = 10,
        page_count: int = 10,
    ) -> List[discord.Embed]:
        """Helper function that generates Karma embed."""
        pages: List[discord.Embed] = []

        author = KarmaMember.get(ctx.guild.id, ctx.author.id)
        guild_limit: int = KarmaMember.get_count(ctx.guild.id)
        limit: int = min(guild_limit, page_count * item_count)

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=title,
            description=description,
        )

        for page_number in range(page_count):
            users = KarmaMember.get_list(
                ctx.guild.id,
                board,
                order,
                item_count,
                item_count * page_number,
            )
            if not users:
                break

            page = embed.copy()

            page_title: str
            if order == BoardOrder.DESC:
                page_title = _(ctx, "Top {limit}").format(limit=limit)
            elif order == BoardOrder.ASC:
                page_title = _(ctx, "Worst {limit}").format(limit=limit)

            page.add_field(
                name=page_title,
                value=Karma._create_embed_page(users, ctx.author, ctx.guild, board),
                inline=False,
            )

            if author and ctx.author.id not in [u.user_id for u in users]:
                page.add_field(
                    name=_(ctx, "Your score"),
                    value=Karma._create_embed_page(
                        [author], ctx.author, ctx.guild, board
                    ),
                    inline=False,
                )

            pages.append(page)

        return pages

    @staticmethod
    def _create_embed_page(
        users: List[KarmaMember],
        author: discord.Member,
        guild: discord.Guild,
        board: BoardType,
    ) -> str:
        """Helper function that generates Karma embed page."""
        result = []
        line_template = "`{value:>6}` … {name}"
        utx = i18n.TranslationContext(guild.id, author.id)

        for user in users:
            member = guild.get_member(user.user_id)
            if member and member.display_name:
                name = utils.text.sanitise(member.display_name, limit=32)
            else:
                name = _(utx, "Unknown member")

            if user.user_id == author.id:
                name = f"**{name}**"

            result.append(
                line_template.format(
                    value=getattr(user, board.name),
                    name=name,
                )
            )

        return "\n".join(result)

    @staticmethod
    def _get_karma_vote_config(guild: discord.Guild) -> Tuple[str, int, int]:
        """Based on guild size, determine vote parameters.

        :param guild: Discord guild to generate the config value

        :return: Guild size, time limit (in minutes) and voter limit.
        """
        member_count = len([m for m in guild.members if not m.bot])

        if member_count < 5:
            # tiny guilds
            return ("tiny", 60, math.ceil(member_count / 2))

        if member_count < 20:
            # small guilds
            return ("small", 60, 5)

        if member_count < 250:
            # big guilds
            return ("big", 120, 10)

        # large guilds
        return ("large", 180, 15)

    @staticmethod
    def get_emoji_value(guild_id: int, emoji: discord.PartialEmoji) -> int:
        """Get's emoji value from DB (default 0)

        :param guild_id: ID of the guild
        :param emoji: Partial Emoji to get the karma value.

        :return: Emoji karma value"""
        if emoji.is_custom_emoji():
            emoji = DiscordEmoji.get(guild_id, emoji.id)
        else:
            emoji = UnicodeEmoji.get(guild_id, emoji.name)
        emoji_value: int = getattr(emoji, "value", 0)

        return emoji_value

    @staticmethod
    def get_cache_key(guild_id: int, user_id: int) -> Tuple[int, int]:
        """Prepares key for cache from guild_id and user_id.

        :param guild_id: Guild ID used for cache processing.
        :param user_id: Discord user ID for cache processing.
        """
        return (guild_id, user_id)


async def setup(bot) -> None:
    await bot.add_cog(Karma(bot))
