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


bot = Furious(
    command_prefix="!",
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

    artwork = getattr(track, "artwork", None)

    if artwork:
        return artwork

    return None


def music_control_bar():

    return (
        "▶️  ⏮️  ⏸️  ⏭️  ⏹️\n\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "`00:00`　　　　　　　　　`00:00`"
    )


def create_now_playing_embed(track):

    artist = getattr(
        track,
        "author",
        "Unknown Artist"
    )

    embed = discord.Embed(
        title="🎵 Now Playing",
        description=(
            f"## {track.title}\n"
            f"🎤 **Artist:** `{artist}`\n\n"
            f"{music_control_bar()}"
        ),
        color=COLOR_MUSIC
    )

    artwork = get_artwork(track)

    if artwork:
        embed.set_image(url=artwork)

    embed.set_footer(
        text="Furious Music • !pause • !resume • !skip • !stop"
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
        title="🎵 Furious Queue",
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
        f"✅ Lavalink connected: "
        f"{payload.node.identifier}"
    )


@bot.event
async def on_wavelink_track_end(payload):

    player = payload.player

    if not player:
        return

    if player.queue:

        track = player.queue.get()

        await player.play(track)


# ==========================================
# PLAYER HELPER
# ==========================================

async def get_player(ctx):

    player = ctx.guild.voice_client

    if player:
        return player

    if not ctx.author.voice:

        embed = basic_embed(
            "❌ Voice Channel Required",
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
            "❌ Voice Connection Failed",
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
            "❌ Voice Channel Required",
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
            "❌ Failed to Join",
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

    try:

        tracks = await wavelink.Playable.search(
            query
        )

        if not tracks:

            embed = basic_embed(
                "❌ No Results",
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
            track
        )

        await ctx.send(
            embed=embed
        )

    except Exception as e:

        print(f"Play error: {e}")

        embed = basic_embed(
            "❌ Playback Error",
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
            "❌ Nothing Playing",
            "There is no track currently playing.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

        await player.skip()

        embed = basic_embed(
            "⏭️ Track Skipped",
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
            "❌ Skip Failed",
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
            "❌ Nothing Playing",
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
            title="⏸️ Music Paused",
            description=(
                f"## {title}\n\n"
                "⏸️ **Playback Paused**\n\n"
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
            "❌ Pause Failed",
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
            "❌ Not Connected",
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
            "❌ Resume Failed",
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
            "❌ Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

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
            "❌ Stop Failed",
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
# NOW PLAYING
# ==========================================

@bot.command()
async def nowplaying(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        embed = basic_embed(
            "❌ Nothing Playing",
            "There is currently no music playing.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    embed = create_now_playing_embed(
        player.current
    )

    await ctx.send(
        embed=embed
    )


# ==========================================
# VOLUME
# ==========================================

@bot.command()
async def volume(ctx, value: int):

    player = ctx.guild.voice_client

    if not player:

        embed = basic_embed(
            "❌ Not Connected",
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
            "❌ Volume Failed",
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
            "❌ Not Connected",
            "I'm not currently in a voice channel.",
            COLOR_ERROR
        )

        return await ctx.send(embed=embed)

    try:

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
            "❌ Leave Failed",
            f"`{type(e).__name__}`",
            COLOR_ERROR
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
        name="🎵 Playback",
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
            "`!volume <0-100>`"
        ),
        inline=True
    )

    embed.add_field(
        name="🔊 Voice",
        value=(
            "`!join`\n"
            "`!leave`"
        ),
        inline=True
    )

    embed.add_field(
        name="🎧 Example",
        value="`!play Tu`",
        inline=False
    )

    embed.add_field(
        name="⚡ Prefix",
        value="`!`",
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

bot.run(TOKEN)        )


# ==========================================
# PLAY
# ==========================================

@bot.command()
async def play(ctx, *, query: str):

    player = await get_player(ctx)

    if not player:
        return

    try:

        tracks = await wavelink.Playable.search(
            query
        )

        if not tracks:

            return await ctx.send(
                "âŒ No results found."
            )

        track = tracks[0]

        if player.playing or player.paused:

            player.queue.put(track)

            await ctx.send(
                f"âž• Added to queue: "
                f"**{track.title}**"
            )

        else:

            await player.play(track)

            await ctx.send(
                f"â–¶ï¸ Playing: "
                f"**{track.title}**"
            )

    except Exception as e:

        print(f"Play error: {e}")

        await ctx.send(
            f"âŒ Playback error: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# SKIP
# ==========================================

@bot.command()
async def skip(ctx):

    player = ctx.guild.voice_client

    if not player or not player.playing:

        return await ctx.send(
            "âŒ Nothing is playing."
        )

    try:

        await player.skip()

        await ctx.send(
            "â­ï¸ Skipped."
        )

    except Exception as e:

        print(f"Skip error: {e}")

        await ctx.send(
            f"âŒ Skip failed: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# PAUSE
# ==========================================

@bot.command()
async def pause(ctx):

    player = ctx.guild.voice_client

    if not player or not player.playing:

        return await ctx.send(
            "âŒ Nothing is playing."
        )

    try:

        await player.pause(True)

        await ctx.send(
            "â¸ï¸ Paused."
        )

    except Exception as e:

        print(f"Pause error: {e}")

        await ctx.send(
            f"âŒ Pause failed: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# RESUME
# ==========================================

@bot.command()
async def resume(ctx):

    player = ctx.guild.voice_client

    if not player:

        return await ctx.send(
            "âŒ I'm not in a voice channel."
        )

    try:

        await player.pause(False)

        await ctx.send(
            "â–¶ï¸ Resumed."
        )

    except Exception as e:

        print(f"Resume error: {e}")

        await ctx.send(
            f"âŒ Resume failed: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# STOP
# ==========================================

@bot.command()
async def stop(ctx):

    player = ctx.guild.voice_client

    if not player:

        return await ctx.send(
            "âŒ I'm not in a voice channel."
        )

    try:

        player.queue.clear()

        await player.stop()

        await ctx.send(
            "â¹ï¸ Stopped and cleared the queue."
        )

    except Exception as e:

        print(f"Stop error: {e}")

        await ctx.send(
            f"âŒ Stop failed: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# QUEUE
# ==========================================

@bot.command()
async def queue(ctx):

    player = ctx.guild.voice_client

    if not player:

        return await ctx.send(
            "âŒ Nothing is playing."
        )

    if not player.queue:

        return await ctx.send(
            "ðŸ“­ Queue is empty."
        )

    tracks = list(player.queue)

    text = "\n".join(
        f"`{i + 1}.` {track.title}"
        for i, track in enumerate(tracks[:10])
    )

    await ctx.send(
        f"ðŸŽµ **Furious Queue**\n{text}"
    )


# ==========================================
# NOW PLAYING
# ==========================================

@bot.command()
async def nowplaying(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        return await ctx.send(
            "âŒ Nothing is playing."
        )

    await ctx.send(
        f"ðŸŽ¶ **Now Playing**\n"
        f"**{player.current.title}**"
    )


# ==========================================
# VOLUME
# ==========================================

@bot.command()
async def volume(ctx, value: int):

    player = ctx.guild.voice_client

    if not player:

        return await ctx.send(
            "âŒ I'm not in a voice channel."
        )

    if not 0 <= value <= 100:

        return await ctx.send(
            "âŒ Volume must be between 0 and 100."
        )

    try:

        await player.set_volume(value)

        await ctx.send(
            f"ðŸ”Š Volume set to **{value}%**"
        )

    except Exception as e:

        print(f"Volume error: {e}")

        await ctx.send(
            f"âŒ Volume failed: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# LEAVE
# ==========================================

@bot.command()
async def leave(ctx):

    player = ctx.guild.voice_client

    if not player:

        return await ctx.send(
            "âŒ I'm not in a voice channel."
        )

    try:

        player.queue.clear()

        await player.disconnect()

        await ctx.send(
            "ðŸ‘‹ Left the voice channel."
        )

    except Exception as e:

        print(f"Leave error: {e}")

        await ctx.send(
            f"âŒ Leave failed: "
            f"`{type(e).__name__}`"
        )


# ==========================================
# HELP
# ==========================================

@bot.command()
async def help(ctx):

    embed = discord.Embed(
        title="ðŸŽµ Furious Music",
        description="Music commands",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Playback",
        value=(
            "`!play <song>`\n"
            "`!pause`\n"
            "`!resume`\n"
            "`!skip`\n"
            "`!stop`"
        ),
        inline=False
    )

    embed.add_field(
        name="Queue",
        value=(
            "`!queue`\n"
            "`!nowplaying`\n"
            "`!volume <0-100>`"
        ),
        inline=False
    )

    embed.add_field(
        name="Voice",
        value="`!join`  `!leave`",
        inline=False
    )

    await ctx.send(embed=embed)


# ==========================================
# START
# ==========================================

print("ðŸš€ Starting Furious...")

bot.run(TOKEN)
