import asyncio
import os

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv


# ==========================================
# LOAD ENVIRONMENT
# ==========================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

LAVALINK_HOST = os.getenv(
    "LAVALINK_HOST",
    "lavalink-2026-production-8c44.up.railway.app"
)

LAVALINK_PORT = int(
    os.getenv("LAVALINK_PORT", "443")
)

LAVALINK_PASSWORD = os.getenv(
    "LAVALINK_PASSWORD"
)


# ==========================================
# CHECK CONFIG
# ==========================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing from .env"
    )

if not LAVALINK_PASSWORD:
    raise RuntimeError(
        "LAVALINK_PASSWORD is missing from .env"
    )


# ==========================================
# DISCORD INTENTS
# ==========================================

intents = discord.Intents.default()

intents.message_content = True
intents.voice_states = True


# ==========================================
# BOT
# ==========================================

class Furious(commands.Bot):

    async def setup_hook(self):

        node = wavelink.Node(
            uri=f"https://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD
        )

        print(
            f"🔌 Connecting to Lavalink: "
            f"https://{LAVALINK_HOST}:{LAVALINK_PORT}"
        )

        await wavelink.Pool.connect(
            nodes=[node],
            client=self,
            cache_capacity=100
        )


# Per-guild state that isn't tracked by wavelink itself.
# loop_mode: "off" | "track" | "queue"
guild_loop_mode = {}
# Handle to a pending auto-disconnect task, keyed by guild id.
idle_disconnect_tasks = {}
# Per-guild custom prefix (falls back to DEFAULT_PREFIX when unset).
guild_prefix = {}
# Per-guild 24/7 mode: stay connected even when idle/alone.
guild_247_mode = {}

DEFAULT_PREFIX = "!"
IDLE_TIMEOUT_SECONDS = 300  # 5 minutes with nothing playing/queued


def resolve_prefix(bot_, message):
    if message.guild:
        return guild_prefix.get(message.guild.id, DEFAULT_PREFIX)
    return DEFAULT_PREFIX


bot = Furious(
    command_prefix=resolve_prefix,
    intents=intents,
    help_command=None
)


# ==========================================
# EMBED COLORS
# ==========================================

COLOR_MAIN = discord.Color.blurple()
COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_WARNING = discord.Color.orange()
COLOR_MUSIC = discord.Color.purple()
COLOR_PAUSE = discord.Color.gold()


# ==========================================
# EMBED HELPERS
# ==========================================

def basic_embed(
    title,
    description="",
    color=COLOR_MAIN
):
    return discord.Embed(
        title=title,
        description=description,
        color=color
    )


def get_artwork(track):
    return getattr(track, "artwork", None)


def format_time(ms):
    if ms is None:
        return "00:00"

    total_seconds = int(ms // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{minutes:02d}:{seconds:02d}"


def music_progress_bar(position_ms, length_ms, bar_length=20):
    """Builds a real progress bar based on current playback position."""

    if not length_ms:
        return (
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "`00:00`　　　　　　　　　`00:00`"
        )

    ratio = max(0.0, min(1.0, position_ms / length_ms))
    filled = int(bar_length * ratio)

    bar = "▬" * filled + "🔘" + "▬" * (bar_length - filled)

    return (
        f"{bar}\n"
        f"`{format_time(position_ms)}`　　　　　　　　　`{format_time(length_ms)}`"
    )


def loop_mode_label(mode):
    return {
        "off": "Off",
        "track": "🔂 Track",
        "queue": "🔁 Queue",
    }.get(mode, "Off")


def create_now_playing_embed(track, player=None):

    artist = getattr(
        track,
        "author",
        "Unknown Artist"
    )

    position = getattr(player, "position", 0) if player else 0
    length = getattr(track, "length", None)

    mode = guild_loop_mode.get(
        player.guild.id, "off"
    ) if player and player.guild else "off"

    embed = discord.Embed(
        title="<:214004pixelspotify:1537699774596386926> Now Playing",
        description=(
            f"## {track.title}\n"
            f"🎤 **Artist:** `{artist}`\n"
            f"🔁 **Loop:** `{loop_mode_label(mode)}`\n\n"
            f"{music_progress_bar(position, length)}"
        ),
        color=COLOR_MUSIC
    )

    artwork = get_artwork(track)

    if artwork:
        embed.set_image(url=artwork)

    embed.set_footer(
        text="Furious Music • Use the buttons below to control playback"
    )

    return embed


def create_queue_embed(player):

    tracks = list(player.queue)

    if not tracks:

        return basic_embed(
            "📭 Queue Empty",
            "There are no songs waiting in the queue.",
            COLOR_WARNING
        )

    text = "\n".join(
        f"`{i + 1}.` **{track.title}**"
        for i, track in enumerate(tracks[:10])
    )

    embed = discord.Embed(
        title="<:214004pixelspotify:1537699774596386926> Furious Queue",
        description=text,
        color=COLOR_MUSIC
    )

    if player.current:

        artwork = get_artwork(player.current)

        if artwork:
            embed.set_thumbnail(url=artwork)

    if len(tracks) > 10:

        embed.set_footer(
            text=f"Showing 10 of {len(tracks)} queued tracks"
        )

    else:

        embed.set_footer(
            text=f"{len(tracks)} track(s) in queue"
        )

    return embed


# ==========================================
# PLAYBACK CONTROL VIEW (real buttons)
# ==========================================

class MusicControlView(discord.ui.View):
    """Interactive buttons attached to the Now Playing embed."""

    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    async def _get_player(self, interaction):
        player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "I'm not connected to a voice channel.",
                ephemeral=True
            )
            return None

        if not interaction.user.voice or interaction.user.voice.channel != player.channel:
            await interaction.response.send_message(
                "You need to be in the same voice channel to do that.",
                ephemeral=True
            )
            return None

        return player

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="776450pause", id=1537702507210612786),
        style=discord.ButtonStyle.secondary
    )
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._get_player(interaction)
        if not player:
            return

        if player.paused:
            await player.pause(False)
            button.emoji = discord.PartialEmoji(name="776450pause", id=1537702507210612786)
            await interaction.response.edit_message(view=self)
        else:
            await player.pause(True)
            # No custom "resume/play" emoji was provided, so this one stays unicode.
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="22838skip", id=1537702524218511452),
        style=discord.ButtonStyle.secondary
    )
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._get_player(interaction)
        if not player:
            return

        if not player.playing:
            await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
            return

        await player.skip()
        await interaction.response.send_message("<:22838skip:1537702524218511452> Skipped.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._get_player(interaction)
        if not player:
            return

        player.queue.clear()
        await player.stop()
        await interaction.response.send_message("⏹️ Stopped and cleared the queue.", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._get_player(interaction)
        if not player:
            return

        order = ["off", "track", "queue"]
        current = guild_loop_mode.get(self.guild_id, "off")
        next_mode = order[(order.index(current) + 1) % len(order)]
        guild_loop_mode[self.guild_id] = next_mode

        await interaction.response.send_message(
            f"🔁 Loop mode set to **{loop_mode_label(next_mode)}**.", ephemeral=True
        )


# ==========================================
# EVENTS
# ==========================================

@bot.event
async def on_ready():

    print()
    print("================================")
    print(f"🤖 Furious is online as {bot.user}")
    print(f"🌐 Servers: {len(bot.guilds)}")
    print("================================")
    print()


@bot.event
async def on_wavelink_node_ready(payload):

    print(
        f"<:763305tick:1537700918722691133> Lavalink connected: "
        f"{payload.node.identifier}"
    )


@bot.event
async def on_wavelink_track_end(payload):

    player = payload.player

    if not player or not player.guild:
        return

    # Avoid double-handling when a track is replaced manually (e.g. !skip
    # calling player.play() directly elsewhere, or !stop).
    if getattr(payload, "reason", None) == "replaced":
        return

    guild_id = player.guild.id
    mode = guild_loop_mode.get(guild_id, "off")
    finished_track = getattr(payload, "track", None)

    # Track loop: replay the same track.
    if mode == "track" and finished_track:
        await player.play(finished_track)
        return

    # Queue loop: put the finished track back at the end before advancing.
    if mode == "queue" and finished_track:
        player.queue.put(finished_track)

    if player.queue:
        next_track = player.queue.get()
        await player.play(next_track)
        return

    # Nothing left to play — start an idle timer instead of leaving instantly.
    schedule_idle_disconnect(player)


def schedule_idle_disconnect(player):
    guild_id = player.guild.id

    if guild_247_mode.get(guild_id):
        return

    existing = idle_disconnect_tasks.get(guild_id)
    if existing and not existing.done():
        existing.cancel()

    async def _idle_leave():
        try:
            await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return

        if guild_247_mode.get(guild_id):
            return

        current_player = player.guild.voice_client
        if current_player and not current_player.playing and not current_player.queue:
            await current_player.disconnect()

    idle_disconnect_tasks[guild_id] = bot.loop.create_task(_idle_leave())


def cancel_idle_disconnect(guild_id):
    task = idle_disconnect_tasks.get(guild_id)
    if task and not task.done():
        task.cancel()


@bot.event
async def on_voice_state_update(member, before, after):
    # Auto-leave if the bot ends up alone in a voice channel.
    if member.bot:
        return

    for voice_client in bot.voice_clients:
        if guild_247_mode.get(voice_client.guild.id):
            continue

        channel = voice_client.channel
        if channel and len([m for m in channel.members if not m.bot]) == 0:
            await voice_client.disconnect()


@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        embed = basic_embed(
            "⚠️ Missing Argument",
            f"You're missing the `{error.param.name}` argument.\n"
            f"Try `!help` to see how this command is used.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    if isinstance(error, commands.BadArgument):
        embed = basic_embed(
            "⚠️ Invalid Argument",
            "That argument wasn't in the right format.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    print(f"Unhandled command error in !{ctx.command}: {error}")

    embed = basic_embed(
        "<a:880726error:1537700477955735622> Unexpected Error",
        f"`{type(error).__name__}`",
        COLOR_ERROR
    )
    await ctx.send(embed=embed)


# ==========================================
# PLAYER HELPER
# ==========================================

async def get_player(ctx):

    player = ctx.guild.voice_client

    if player:
        return player

    if not ctx.author.voice:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Voice Channel Required",
            "Join a voice channel first.",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)

        return None

    try:

        player = await ctx.author.voice.channel.connect(
            cls=wavelink.Player
        )

        return player

    except Exception as e:

        print(
            f"Voice connection error: {e}"
        )

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Voice Connection Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)

        return None


# ==========================================
# JOIN
# ==========================================

@bot.command()
async def join(ctx):

    if not ctx.author.voice:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Voice Channel Required",
            "Join a voice channel first.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    channel = ctx.author.voice.channel

    player = ctx.guild.voice_client

    try:

        if not player:

            player = await channel.connect(
                cls=wavelink.Player
            )

        elif player.channel != channel:

            await player.move_to(channel)

        embed = basic_embed(
            "🔊 Connected",
            f"Successfully joined **{channel.name}**.",
            COLOR_SUCCESS
        )

        embed.set_footer(
            text="Furious Music • Voice System"
        )

        await ctx.send(embed=embed)

    except Exception as e:

        print(f"Join error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Failed to Join",
            f"Voice connection failed:\n`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# PLAY
# ==========================================

@bot.command()
async def play(ctx, *, query: str):

    player = await get_player(ctx)

    if not player:
        return

    cancel_idle_disconnect(ctx.guild.id)

    try:

        tracks = await wavelink.Playable.search(
            query
        )

        if not tracks:

            embed = basic_embed(
                "<a:880726error:1537700477955735622> No Results",
                f"No music results found for:\n`{query}`",
                COLOR_ERROR
            )

            return await ctx.send(embed=embed)

        track = tracks[0]

        # ==================================
        # ADD TO QUEUE
        # ==================================

        if player.playing or player.paused:

            player.queue.put(track)

            artist = getattr(
                track,
                "author",
                "Unknown Artist"
            )

            embed = discord.Embed(
                title="➕ Added to Queue",
                description=(
                    f"## {track.title}\n\n"
                    f"🎤 **Artist:** `{artist}`\n"
                    f"📍 **Position:** `{len(player.queue)}`"
                ),
                color=COLOR_WARNING
            )

            artwork = get_artwork(track)

            if artwork:
                embed.set_thumbnail(
                    url=artwork
                )

            embed.set_footer(
                text="Furious Music • Queue System"
            )

            return await ctx.send(
                embed=embed
            )

        # ==================================
        # PLAY
        # ==================================

        await player.play(track)

        embed = create_now_playing_embed(
            track, player
        )

        await ctx.send(
            embed=embed,
            view=MusicControlView(ctx.guild.id)
        )

    except Exception as e:

        print(f"Play error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Playback Error",
            f"Something went wrong:\n`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# SKIP
# ==========================================

@bot.command()
async def skip(ctx):

    player = ctx.guild.voice_client

    if not player or not player.playing:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Nothing Playing",
            "There is no track currently playing.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

        await player.skip()

        embed = basic_embed(
            "<:22838skip:1537702524218511452> Track Skipped",
            "The current track has been skipped.",
            COLOR_WARNING
        )

        embed.set_footer(
            text="Furious Music • Playback"
        )

        await ctx.send(embed=embed)

    except Exception as e:

        print(f"Skip error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Skip Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# PAUSE
# ==========================================

@bot.command()
async def pause(ctx):

    player = ctx.guild.voice_client

    if not player or not player.playing:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Nothing Playing",
            "There is no music currently playing.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

        await player.pause(True)

        track = player.current

        title = (
            track.title
            if track
            else "Current Track"
        )

        embed = discord.Embed(
            title="<:776450pause:1537702507210612786> Music Paused",
            description=(
                f"## {title}\n\n"
                "<:776450pause:1537702507210612786> **Playback Paused**\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
            ),
            color=COLOR_PAUSE
        )

        if track:

            artwork = get_artwork(track)

            if artwork:
                embed.set_thumbnail(
                    url=artwork
                )

        embed.set_footer(
            text="Furious Music • Use !resume to continue"
        )

        await ctx.send(embed=embed)

    except Exception as e:

        print(f"Pause error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Pause Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# RESUME
# ==========================================

@bot.command()
async def resume(ctx):

    player = ctx.guild.voice_client

    if not player:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

        await player.pause(False)

        track = player.current

        title = (
            track.title
            if track
            else "Music"
        )

        embed = discord.Embed(
            title="▶️ Music Resumed",
            description=(
                f"## {title}\n\n"
                "▶️ **Now Playing**\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
            ),
            color=COLOR_SUCCESS
        )

        if track:

            artwork = get_artwork(track)

            if artwork:
                embed.set_thumbnail(
                    url=artwork
                )

        embed.set_footer(
            text="Furious Music • Playback"
        )

        await ctx.send(embed=embed)

    except Exception as e:

        print(f"Resume error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Resume Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# STOP
# ==========================================

@bot.command()
async def stop(ctx):

    player = ctx.guild.voice_client

    if not player:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

        guild_loop_mode[ctx.guild.id] = "off"
        player.queue.clear()

        await player.stop()

        embed = basic_embed(
            "⏹️ Music Stopped",
            "Playback stopped and the queue was cleared.",
            COLOR_ERROR
        )

        embed.set_footer(
            text="Furious Music • Queue Cleared"
        )

        await ctx.send(embed=embed)

    except Exception as e:

        print(f"Stop error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Stop Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# QUEUE
# ==========================================

@bot.command()
async def queue(ctx):

    player = ctx.guild.voice_client

    if not player:

        embed = basic_embed(
            "📭 Queue Empty",
            "I'm not currently connected to a voice channel.",
            COLOR_WARNING
        )

        return await ctx.send(embed=embed)

    if not player.queue:

        embed = basic_embed(
            "📭 Queue Empty",
            "There are no songs waiting in the queue.",
            COLOR_WARNING
        )

        return await ctx.send(embed=embed)

    embed = create_queue_embed(
        player
    )

    await ctx.send(
        embed=embed
    )


# ==========================================
# CLEAR / REMOVE / SHUFFLE
# ==========================================

@bot.command()
async def clear(ctx):

    player = ctx.guild.voice_client

    if not player or not player.queue:
        embed = basic_embed(
            "📭 Queue Empty",
            "There's nothing in the queue to clear.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    player.queue.clear()

    embed = basic_embed(
        "🧹 Queue Cleared",
        "All queued tracks have been removed.",
        COLOR_SUCCESS
    )
    await ctx.send(embed=embed)


@bot.command()
async def remove(ctx, index: int):

    player = ctx.guild.voice_client

    if not player or not player.queue:
        embed = basic_embed(
            "📭 Queue Empty",
            "There's nothing in the queue to remove.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    tracks = list(player.queue)

    if index < 1 or index > len(tracks):
        embed = basic_embed(
            "⚠️ Invalid Position",
            f"Give me a number between `1` and `{len(tracks)}`.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    removed = tracks.pop(index - 1)
    player.queue.clear()
    for t in tracks:
        player.queue.put(t)

    embed = basic_embed(
        "🗑️ Removed",
        f"Removed **{removed.title}** from the queue.",
        COLOR_SUCCESS
    )
    await ctx.send(embed=embed)


@bot.command()
async def shuffle(ctx):

    player = ctx.guild.voice_client

    if not player or not player.queue:
        embed = basic_embed(
            "📭 Queue Empty",
            "There's nothing in the queue to shuffle.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    player.queue.shuffle()

    embed = basic_embed(
        "🔀 Queue Shuffled",
        "The upcoming tracks have been shuffled.",
        COLOR_SUCCESS
    )
    await ctx.send(embed=embed)


# ==========================================
# LOOP
# ==========================================

@bot.command(name="loop")
async def loop_cmd(ctx, mode: str = None):

    player = ctx.guild.voice_client

    if not player:
        embed = basic_embed(
            "<a:880726error:1537700477955735622> Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )
        return await ctx.send(embed=embed)

    valid = {"off", "track", "queue"}

    if mode is None:
        current = guild_loop_mode.get(ctx.guild.id, "off")
        embed = basic_embed(
            "🔁 Loop Status",
            f"Current mode: **{loop_mode_label(current)}**\n"
            f"Use `!loop off|track|queue` to change it.",
            COLOR_MAIN
        )
        return await ctx.send(embed=embed)

    mode = mode.lower()

    if mode not in valid:
        embed = basic_embed(
            "⚠️ Invalid Mode",
            "Choose one of: `off`, `track`, `queue`.",
            COLOR_WARNING
        )
        return await ctx.send(embed=embed)

    guild_loop_mode[ctx.guild.id] = mode

    embed = basic_embed(
        "🔁 Loop Updated",
        f"Loop mode set to **{loop_mode_label(mode)}**.",
        COLOR_SUCCESS
    )
    await ctx.send(embed=embed)


# ==========================================
# NOW PLAYING
# ==========================================

@bot.command()
async def nowplaying(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Nothing Playing",
            "There is currently no music playing.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    embed = create_now_playing_embed(
        player.current, player
    )

    await ctx.send(
        embed=embed,
        view=MusicControlView(ctx.guild.id)
    )


# ==========================================
# VOLUME
# ==========================================

@bot.command()
async def volume(ctx, value: int):

    player = ctx.guild.voice_client

    if not player:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    if not 0 <= value <= 100:

        embed = basic_embed(
            "⚠️ Invalid Volume",
            "Volume must be between **0 and 100**.",
            COLOR_WARNING
        )

        return await ctx.send(embed=embed)

    try:

        await player.set_volume(value)

        filled = int(value / 10)

        empty = 10 - filled

        bar = (
            "█" * filled +
            "░" * empty
        )

        embed = discord.Embed(
            title="🔊 Volume Updated",
            description=(
                f"## `{value}%`\n\n"
                f"`{bar}`"
            ),
            color=COLOR_MAIN
        )

        embed.set_footer(
            text="Furious Music • Volume Control"
        )

        await ctx.send(
            embed=embed
        )

    except Exception as e:

        print(f"Volume error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Volume Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# LEAVE
# ==========================================

@bot.command()
async def leave(ctx):

    player = ctx.guild.voice_client

    if not player:

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

        cancel_idle_disconnect(ctx.guild.id)
        guild_loop_mode[ctx.guild.id] = "off"
        player.queue.clear()

        await player.disconnect()

        embed = basic_embed(
            "👋 Disconnected",
            "Left the voice channel and cleared the queue.",
            COLOR_SUCCESS
        )

        embed.set_footer(
            text="Furious Music • Voice System"
        )

        await ctx.send(embed=embed)

    except Exception as e:

        print(f"Leave error: {e}")

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Leave Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# BOT STATS (SERVERS / USERS)
# ==========================================

@bot.command(name="user", aliases=["stats", "botinfo"])
async def user_stats(ctx):

    total_servers = len(bot.guilds)

    # Sum member counts across all guilds the bot can see.
    total_users = sum(
        guild.member_count or 0
        for guild in bot.guilds
    )

    embed = discord.Embed(
        title="📊 Furious Stats",
        description=(
            f"🌐 **Servers:** `{total_servers}`\n"
            f"👥 **Total Users:** `{total_users}`\n"
            f"🎶 **Active Players:** `{len(bot.voice_clients)}`"
        ),
        color=COLOR_MAIN
    )

    embed.set_thumbnail(
        url=bot.user.display_avatar.url
    )

    embed.set_footer(
        text="Furious Music • Bot Statistics"
    )

    await ctx.send(embed=embed)


# ==========================================
# PING
# ==========================================

@bot.command()
async def ping(ctx):

    bot_latency = round(bot.latency * 1000)

    player = ctx.guild.voice_client
    node_latency = None

    if player and getattr(player, "node", None):
        node_latency = round(player.node.heartbeat)

    description = f"🌐 **Bot:** `{bot_latency}ms`"

    if node_latency is not None:
        description += f"\n🎧 **Lavalink Node:** `{node_latency}ms`"

    embed = basic_embed(
        "🏓 Pong!",
        description,
        COLOR_MAIN
    )

    embed.set_footer(
        text="Furious Music • Latency"
    )

    await ctx.send(embed=embed)


# ==========================================
# PREFIX
# ==========================================

@bot.command()
@commands.has_permissions(manage_guild=True)
async def prefix(ctx, new_prefix: str = None):

    if new_prefix is None:

        current = guild_prefix.get(ctx.guild.id, DEFAULT_PREFIX)

        embed = basic_embed(
            "⚙️ Current Prefix",
            f"My prefix here is `{current}`\n"
            f"Use `{current}prefix <new_prefix>` to change it.",
            COLOR_MAIN
        )

        return await ctx.send(embed=embed)

    if len(new_prefix) > 5:

        embed = basic_embed(
            "⚠️ Invalid Prefix",
            "Prefix must be 5 characters or fewer.",
            COLOR_WARNING
        )

        return await ctx.send(embed=embed)

    guild_prefix[ctx.guild.id] = new_prefix

    embed = basic_embed(
        "<:763305tick:1537700918722691133> Prefix Updated",
        f"My prefix is now `{new_prefix}`",
        COLOR_SUCCESS
    )

    await ctx.send(embed=embed)


@prefix.error
async def prefix_error(ctx, error):

    if isinstance(error, commands.MissingPermissions):

        embed = basic_embed(
            "<a:880726error:1537700477955735622> Missing Permissions",
            "You need the **Manage Server** permission to change the prefix.",
            COLOR_ERROR
        )

        await ctx.send(embed=embed)


# ==========================================
# 24/7 MODE
# ==========================================

@bot.command(name="247")
async def twentyfourseven(ctx):

    guild_id = ctx.guild.id

    currently_on = guild_247_mode.get(guild_id, False)
    guild_247_mode[guild_id] = not currently_on

    if guild_247_mode[guild_id]:

        embed = basic_embed(
            "♾️ 24/7 Mode Enabled",
            "I'll stay in the voice channel even when idle or alone.",
            COLOR_SUCCESS
        )

    else:

        embed = basic_embed(
            "♾️ 24/7 Mode Disabled",
            "I'll auto-disconnect after being idle or left alone again.",
            COLOR_WARNING
        )

        # Re-arm the idle timer immediately if there's nothing playing.
        player = ctx.guild.voice_client
        if player and not player.playing and not player.queue:
            schedule_idle_disconnect(player)

    embed.set_footer(
        text="Furious Music • Voice System"
    )

    await ctx.send(embed=embed)


# ==========================================
# HELP
# ==========================================

@bot.command()
async def help(ctx):

    embed = discord.Embed(
        title="⚡ Furious Music",
        description=(
            "**Music system powered by Lavalink**\n\n"
            "Use `!play <song>` to start listening."
        ),
        color=COLOR_MAIN
    )

    embed.add_field(
        name="<:214004pixelspotify:1537699774596386926> Playback",
        value=(
            "`!play <song>`\n"
            "`!pause`\n"
            "`!resume`\n"
            "`!skip`\n"
            "`!stop`"
        ),
        inline=True
    )

    embed.add_field(
        name="📋 Queue",
        value=(
            "`!queue`\n"
            "`!nowplaying`\n"
            "`!volume <0-100>`\n"
            "`!shuffle`\n"
            "`!remove <#>`\n"
            "`!clear`"
        ),
        inline=True
    )

    embed.add_field(
        name="🔊 Voice",
        value=(
            "`!join`\n"
            "`!leave`\n"
            "`!loop <off|track|queue>`\n"
            "`!247`"
        ),
        inline=True
    )

    embed.add_field(
        name="🛠️ Utility",
        value=(
            "`!ping`\n"
            "`!prefix <new>`\n"
            "`!user`"
        ),
        inline=True
    )

    embed.add_field(
        name="🎧 Example",
        value="`!play Tu`",
        inline=False
    )

    current_prefix = guild_prefix.get(ctx.guild.id, DEFAULT_PREFIX)

    embed.add_field(
        name="⚡ Prefix",
        value=f"`{current_prefix}`",
        inline=True
    )

    embed.set_footer(
        text="Furious • Music & Moderation"
    )

    await ctx.send(
        embed=embed
    )


# ==========================================
# START
# ==========================================

print("🚀 Starting Furious...")

bot.run(TOKEN)
