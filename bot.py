import os
import asyncio

import discord
import wavelink

from discord.ext import commands
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = os.getenv("LAVALINK_PORT", "443")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

if not LAVALINK_HOST:
    raise RuntimeError("LAVALINK_HOST is missing from .env")

if not LAVALINK_PASSWORD:
    raise RuntimeError("LAVALINK_PASSWORD is missing from .env")


# ============================================================
# LAVALINK URL
# ============================================================

host = LAVALINK_HOST.strip()

host = host.replace("https://", "")
host = host.replace("http://", "")
host = host.rstrip("/")

LAVALINK_URI = f"https://{host}:{LAVALINK_PORT}"

print(f"🔌 Lavalink URI: {LAVALINK_URI}")


# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print("=" * 50)
    print(f"✅ Logged in as: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print("=" * 50)

    if wavelink.Pool.nodes:
        print("ℹ️ Lavalink node already exists.")
        return

    try:

        node = wavelink.Node(
            identifier="Railway",
            uri=LAVALINK_URI,
            password=LAVALINK_PASSWORD,
            retries=10
        )

        await wavelink.Pool.connect(
            nodes=[node],
            client=bot
        )

        print("✅ Lavalink connection requested.")

    except Exception as e:

        print("=" * 50)
        print("❌ LAVALINK CONNECTION ERROR")
        print(f"Type: {type(e).__name__}")
        print(f"Error: {e}")
        print("=" * 50)


# ============================================================
# LAVALINK READY
# ============================================================

@bot.event
async def on_wavelink_node_ready(payload):

    print("=" * 50)
    print(f"🟢 Lavalink ready: {payload.node.identifier}")
    print("=" * 50)


# ============================================================
# JOIN
# ============================================================

@bot.command()
async def join(ctx):

    if not ctx.author.voice:
        await ctx.send(
            "❌ Join a voice channel first."
        )
        return

    channel = ctx.author.voice.channel

    try:

        player = ctx.guild.voice_client

        if player:

            await ctx.send(
                "✅ I'm already connected."
            )
            return

        print(f"🔵 Joining: {channel.name}")

        player = await channel.connect(
            cls=wavelink.Player
        )

        print("🟢 Discord voice connected.")

        await ctx.send(
            f"✅ Joined **{channel.name}**"
        )

    except Exception as e:

        print("=" * 50)
        print("❌ VOICE CONNECTION ERROR")
        print(f"Type: {type(e).__name__}")
        print(f"Error: {e}")
        print("=" * 50)

        await ctx.send(
            f"❌ Voice error: `{type(e).__name__}`"
        )


# ============================================================
# PLAY
# ============================================================

@bot.command()
async def play(ctx, *, query: str):

    if not ctx.author.voice:

        await ctx.send(
            "❌ Join a voice channel first."
        )
        return

    try:

        # ----------------------------------------------------
        # Get existing player
        # ----------------------------------------------------

        player = ctx.guild.voice_client

        # ----------------------------------------------------
        # Connect if not already connected
        # ----------------------------------------------------

        if not player:

            channel = ctx.author.voice.channel

            print(
                f"🔵 Connecting to: {channel.name}"
            )

            player = await channel.connect(
                cls=wavelink.Player
            )

            print(
                "🟢 Discord voice connected."
            )

        # ----------------------------------------------------
        # Verify player
        # ----------------------------------------------------

        if not isinstance(player, wavelink.Player):

            await ctx.send(
                "❌ Voice player is invalid."
            )
            return

        # ----------------------------------------------------
        # Search YouTube
        # ----------------------------------------------------

        print(
            f"🔎 Searching YouTube: {query}"
        )

        results = await wavelink.Playable.search(
            query,
            source=wavelink.TrackSource.YouTube
        )

        # ----------------------------------------------------
        # No results
        # ----------------------------------------------------

        if not results:

            await ctx.send(
                "❌ No results found."
            )
            return

        # ----------------------------------------------------
        # Get first track
        # ----------------------------------------------------

        if isinstance(
            results,
            wavelink.Playlist
        ):

            if not results.tracks:

                await ctx.send(
                    "❌ Playlist is empty."
                )
                return

            track = results.tracks[0]

        else:

            track = results[0]

        # ----------------------------------------------------
        # Play
        # ----------------------------------------------------

        print(
            f"🎵 Found: {track.title}"
        )

        await player.play(track)

        print(
            f"▶️ Playing: {track.title}"
        )

        await ctx.send(
            f"▶️ **{track.title}**"
        )

    except Exception as e:

        print("=" * 50)
        print("❌ PLAY ERROR")
        print(f"Type: {type(e).__name__}")
        print(f"Error: {e}")
        print("=" * 50)

        await ctx.send(
            f"❌ Playback error: `{type(e).__name__}`"
        )


# ============================================================
# PAUSE
# ============================================================

@bot.command()
async def pause(ctx):

    player = ctx.guild.voice_client

    if not isinstance(
        player,
        wavelink.Player
    ):

        await ctx.send(
            "❌ I'm not connected."
        )
        return

    await player.pause(True)

    await ctx.send(
        "⏸️ Paused."
    )


# ============================================================
# RESUME
# ============================================================

@bot.command()
async def resume(ctx):

    player = ctx.guild.voice_client

    if not isinstance(
        player,
        wavelink.Player
    ):

        await ctx.send(
            "❌ I'm not connected."
        )
        return

    await player.pause(False)

    await ctx.send(
        "▶️ Resumed."
    )


# ============================================================
# STOP
# ============================================================

@bot.command()
async def stop(ctx):

    player = ctx.guild.voice_client

    if not isinstance(
        player,
        wavelink.Player
    ):

        await ctx.send(
            "❌ I'm not connected."
        )
        return

    await player.stop()

    await ctx.send(
        "⏹️ Stopped."
    )


# ============================================================
# LEAVE
# ============================================================

@bot.command()
async def leave(ctx):

    player = ctx.guild.voice_client

    if not isinstance(
        player,
        wavelink.Player
    ):

        await ctx.send(
            "❌ I'm not in a voice channel."
        )
        return

    await player.disconnect()

    await ctx.send(
        "👋 Left the voice channel."
    )


# ============================================================
# PING
# ============================================================

@bot.command()
async def ping(ctx):

    discord_ping = round(
        bot.latency * 1000
    )

    try:

        node = wavelink.Pool.get_node()

        await ctx.send(
            f"🏓 Discord: `{discord_ping}ms`\n"
            f"🎵 Lavalink: `{node.status}`"
        )

    except Exception:

        await ctx.send(
            f"🏓 Discord: `{discord_ping}ms`\n"
            f"🎵 Lavalink: `Not connected`"
        )


# ============================================================
# START
# ============================================================

async def main():

    async with bot:

        await bot.start(TOKEN)


if __name__ == "__main__":

    asyncio.run(main())
