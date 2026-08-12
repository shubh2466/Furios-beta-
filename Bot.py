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

        # Railway Lavalink
        node = wavelink.Node(
            uri=f"https://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD
        )

        print(
            f"ðŸ”Œ Connecting to Lavalink: "
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
# EVENTS
# ==========================================

@bot.event
async def on_ready():

    print()
    print("================================")
    print(f"ðŸ¤– Furious is online as {bot.user}")
    print(f"ðŸŒ Servers: {len(bot.guilds)}")
    print("================================")
    print()


@bot.event
async def on_wavelink_node_ready(payload):

    print(
        f"âœ… Lavalink connected: "
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

        await ctx.send(
            "âŒ Join a voice channel first."
        )

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

        await ctx.send(
            f"âŒ Voice connection failed: "
            f"`{type(e).__name__}`"
        )

        return None


# ==========================================
# JOIN
# ==========================================

@bot.command()
async def join(ctx):

    if not ctx.author.voice:

        return await ctx.send(
            "âŒ Join a voice channel first."
        )

    channel = ctx.author.voice.channel
    player = ctx.guild.voice_client

    try:

        if not player:

            player = await channel.connect(
                cls=wavelink.Player
            )

        elif player.channel != channel:

            await player.move_to(channel)

        await ctx.send(
            f"ðŸ”Š Joined **{channel.name}**"
        )

    except Exception as e:

        print(f"Join error: {e}")

        await ctx.send(
            f"âŒ Failed to join voice: "
            f"`{type(e).__name__}`"
        )


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
