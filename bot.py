import os
import asyncio
import discord
import wavelink

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_URI = os.getenv("LAVALINK_URI")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

if not LAVALINK_URI:
    raise RuntimeError("LAVALINK_URI is missing from .env")

if not LAVALINK_PASSWORD:
    raise RuntimeError("LAVALINK_PASSWORD is missing from .env")


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🔌 Connecting to Lavalink...")

    try:
        node = wavelink.Node(
            identifier="main",
            uri=LAVALINK_URI,
            password=LAVALINK_PASSWORD,
            retries=10,
        )

        await wavelink.Pool.connect(
            nodes=[node],
            client=bot
        )

        print("✅ Lavalink connected")

    except Exception as e:
        print(f"❌ Lavalink connection failed: {e}")


@bot.event
async def on_wavelink_node_ready(payload):
    print(f"🟢 Lavalink ready: {payload.node.identifier}")


@bot.event
async def on_wavelink_node_connection_closed(payload):
    print(f"🔴 Lavalink connection closed: {payload}")


@bot.event
async def on_wavelink_websocket_closed(payload):
    print(f"⚠️ Lavalink websocket closed: {payload}")


@bot.command()
async def join(ctx):
    """Join the user's voice channel."""

    if not ctx.author.voice:
        return await ctx.send("❌ Join a voice channel first.")

    channel = ctx.author.voice.channel

    try:
        player = ctx.guild.voice_client

        if player:
            if isinstance(player, wavelink.Player):
                if player.channel.id != channel.id:
                    await player.move_to(channel)

                return await ctx.send("✅ Already connected.")

        print(f"🔵 Connecting to voice channel: {channel.name}")

        player = await channel.connect(
            cls=wavelink.Player
        )

        print("🟢 Voice connection completed")

        await ctx.send(f"✅ Joined **{channel.name}**")

    except Exception as e:
        print(f"❌ Voice connection failed: {type(e).__name__}: {e}")
        await ctx.send(f"❌ Voice connection failed: `{type(e).__name__}`")


@bot.command()
async def play(ctx, *, query: str):
    """Play a YouTube/YouTube Music search or URL."""

    if not ctx.author.voice:
        return await ctx.send("❌ Join a voice channel first.")

    try:
        player = ctx.guild.voice_client

        # Connect if not already connected
        if not player:
            channel = ctx.author.voice.channel

            print(f"🔵 Connecting to {channel.name}...")

            player = await channel.connect(
                cls=wavelink.Player
            )

            print("🟢 Voice connection completed")

        if not isinstance(player, wavelink.Player):
            return await ctx.send("❌ Invalid voice player.")

        # Search Lavalink
        print(f"🔎 Searching: {query}")

        tracks = await wavelink.Playable.search(query)

        if not tracks:
            return await ctx.send("❌ No results found.")

        # Search can return a playlist
        if isinstance(tracks, wavelink.Playlist):
            track = tracks.tracks[0]
        else:
            track = tracks[0]

        print(f"🎵 Track: {track.title}")

        # Play
        await player.play(track)

        print(f"▶️ Playing: {track.title}")

        await ctx.send(f"▶️ **{track.title}**")

    except Exception as e:
        print(
            f"❌ PLAY ERROR\n"
            f"Type: {type(e).__name__}\n"
            f"Error: {e}"
        )

        await ctx.send(
            f"❌ Playback error: `{type(e).__name__}`"
        )


@bot.command()
async def pause(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        return await ctx.send("❌ Not connected.")

    await player.pause(True)
    await ctx.send("⏸️ Paused.")


@bot.command()
async def resume(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        return await ctx.send("❌ Not connected.")

    await player.pause(False)
    await ctx.send("▶️ Resumed.")


@bot.command()
async def stop(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        return await ctx.send("❌ Not connected.")

    await player.stop()
    await ctx.send("⏹️ Stopped.")


@bot.command()
async def leave(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        return await ctx.send("❌ I'm not in a voice channel.")

    await player.disconnect()
    await ctx.send("👋 Left the voice channel.")


@bot.command()
async def ping(ctx):
    node = wavelink.Pool.get_node()

    await ctx.send(
        f"🏓 Discord: `{round(bot.latency * 1000)}ms`\n"
        f"🎵 Lavalink: `{node.status}`"
    )


async def main():
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
