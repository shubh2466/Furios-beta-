import os
import asyncio
import logging

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv


# ============================================================
# ENV
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = os.getenv("LAVALINK_PORT", "443")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")
LAVALINK_SCHEME = os.getenv("LAVALINK_SCHEME", "https")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

if not LAVALINK_HOST:
    raise RuntimeError("LAVALINK_HOST is missing")

if not LAVALINK_PASSWORD:
    raise RuntimeError("LAVALINK_PASSWORD is missing")


# ============================================================
# LAVALINK URI
# ============================================================

host = LAVALINK_HOST.strip()

if host.startswith("https://"):
    host = host[len("https://"):]
elif host.startswith("http://"):
    host = host[len("http://"):]

host = host.rstrip("/")

LAVALINK_URI = f"{LAVALINK_SCHEME}://{host}:{LAVALINK_PORT}"

print("=" * 60)
print(f"🔌 Lavalink URI: {LAVALINK_URI}")
print("=" * 60)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logging.getLogger("discord").setLevel(logging.INFO)
logging.getLogger("wavelink").setLevel(logging.INFO)


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

lavalink_ready = asyncio.Event()


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"✅ Logged in as: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print("=" * 60)

    if wavelink.Pool.nodes:
        print("ℹ️ Lavalink node already exists.")
        return

    try:
        node = wavelink.Node(
            identifier="Railway",
            uri=LAVALINK_URI,
            password=LAVALINK_PASSWORD,
            retries=10,
        )

        await wavelink.Pool.connect(
            nodes=[node],
            client=bot,
        )

        print("🔌 Lavalink connection started.")

    except Exception as exc:
        print("=" * 60)
        print("❌ LAVALINK CONNECTION ERROR")
        print(f"Type: {type(exc).__name__}")
        print(f"Error: {exc}")
        print("=" * 60)


# ============================================================
# LAVALINK EVENTS
# ============================================================

@bot.event
async def on_wavelink_node_ready(payload):
    lavalink_ready.set()

    print("=" * 60)
    print(f"🟢 Lavalink READY: {payload.node.identifier}")
    print(f"📡 Node status: {payload.node.status}")
    print("=" * 60)


@bot.event
async def on_wavelink_node_closed(payload):
    lavalink_ready.clear()

    print("=" * 60)
    print("🔴 Lavalink NODE CLOSED")
    print(f"Node: {payload.node.identifier}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_start(payload):
    print("=" * 60)
    print("▶️ TRACK START")
    print(f"Track: {payload.track.title}")
    print(f"Identifier: {payload.track.identifier}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_end(payload):
    print("=" * 60)
    print("⏹️ TRACK END")
    print(f"Track: {payload.track.title}")
    print(f"Reason: {payload.reason}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_exception(payload):
    print("=" * 60)
    print("❌ TRACK EXCEPTION")
    print(f"Track: {payload.track.title}")
    print(f"Exception: {payload.exception}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_stuck(payload):
    print("=" * 60)
    print("⚠️ TRACK STUCK")
    print(f"Track: {payload.track.title}")
    print(f"Threshold: {payload.threshold}")
    print("=" * 60)


@bot.event
async def on_wavelink_player_update(payload):
    print(
        f"📶 PLAYER UPDATE | "
        f"connected={payload.connected} "
        f"ping={payload.ping}ms "
        f"position={payload.position}ms"
    )


@bot.event
async def on_wavelink_websocket_closed(payload):
    print("=" * 60)
    print("🔴 LAVALINK WEBSOCKET CLOSED")
    print(f"Code: {payload.code}")
    print(f"Reason: {payload.reason}")
    print("=" * 60)


# ============================================================
# VOICE
# ============================================================

async def get_or_connect_player(ctx):
    if not ctx.author.voice:
        raise RuntimeError("Join a voice channel first.")

    player = ctx.guild.voice_client

    if isinstance(player, wavelink.Player):
        return player

    channel = ctx.author.voice.channel

    print(f"🔵 Connecting to Discord voice: {channel.name}")

    player = await channel.connect(
        cls=wavelink.Player,
        self_deaf=True,
    )

    print(
        f"🟢 Discord voice connected | "
        f"guild={ctx.guild.id} "
        f"channel={channel.name} "
        f"connected={player.connected}"
    )

    return player


# ============================================================
# PLAY
# ============================================================

@bot.command()
async def play(ctx, *, query: str):

    if not lavalink_ready.is_set():
        await ctx.send("❌ Lavalink is not ready.")
        return

    try:
        player = await get_or_connect_player(ctx)

        print("=" * 60)
        print("🎵 PLAY")
        print(f"Query: {query}")
        print(f"Connected: {player.connected}")
        print(f"Playing before search: {player.playing}")
        print(f"Ping before search: {player.ping}")
        print("=" * 60)

        # ----------------------------------------------------
        # SEARCH
        # ----------------------------------------------------

        search_query = query

        if not (
            query.startswith("http://")
            or query.startswith("https://")
        ):
            search_query = f"ytsearch:{query}"

        print(f"🔎 Searching Lavalink: {search_query}")

        try:
            tracks = await asyncio.wait_for(
                wavelink.Playable.search(search_query),
                timeout=20,
            )
        except asyncio.TimeoutError:
            print("❌ Search timed out.")
            await ctx.send("❌ YouTube search timed out.")
            return

        print(f"✅ Search returned: {type(tracks).__name__}")

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        if not tracks:
            print("❌ Search returned no tracks.")
            await ctx.send("❌ No results found.")
            return

        print(f"📦 Result count: {len(tracks)}")
        print("➡️ Selecting first result...")

        track = tracks[0]

        print(f"✅ First result type: {type(track).__name__}")

        # ----------------------------------------------------
        # METADATA
        # ----------------------------------------------------

        print("➡️ Reading track metadata...")

        print(f"Title: {track.title}")
        print(f"Author: {track.author}")
        print(f"Identifier: {track.identifier}")
        print(f"URI: {track.uri}")
        print(f"Source: {track.source}")

        print("✅ TRACK SELECTED")

        # ----------------------------------------------------
        # PLAY
        # ----------------------------------------------------

        print("▶️ Sending play request...")

        try:
            await asyncio.wait_for(
                player.play(
                    track,
                    replace=True,
                ),
                timeout=20,
            )
        except asyncio.TimeoutError:
            print("❌ Player.play() timed out.")
            await ctx.send("❌ Lavalink play request timed out.")
            return

        print("=" * 60)
        print("✅ PLAY REQUEST SENT")
        print(f"Track: {track.title}")
        print(f"Connected: {player.connected}")
        print(f"Playing: {player.playing}")
        print(f"Ping: {player.ping}")
        print("=" * 60)

        await ctx.send(
            f"▶️ **{track.title}**"
        )

    except Exception as exc:
        print("=" * 60)
        print("❌ PLAY ERROR")
        print(f"Type: {type(exc).__name__}")
        print(f"Error: {exc}")
        print("=" * 60)

        await ctx.send(
            f"❌ Playback error: `{type(exc).__name__}`"
        )


# ============================================================
# JOIN
# ============================================================

@bot.command()
async def join(ctx):
    try:
        player = await get_or_connect_player(ctx)

        await ctx.send(
            f"✅ Joined **{player.channel.name}**"
        )

    except Exception as exc:
        print(f"❌ JOIN ERROR: {type(exc).__name__}: {exc}")
        await ctx.send(
            f"❌ Voice error: `{type(exc).__name__}`"
        )


# ============================================================
# PAUSE
# ============================================================

@bot.command()
async def pause(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        await ctx.send("❌ I'm not connected.")
        return

    await player.pause(True)
    await ctx.send("⏸️ Paused.")


# ============================================================
# RESUME
# ============================================================

@bot.command()
async def resume(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        await ctx.send("❌ I'm not connected.")
        return

    await player.pause(False)
    await ctx.send("▶️ Resumed.")


# ============================================================
# STOP
# ============================================================

@bot.command()
async def stop(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        await ctx.send("❌ I'm not connected.")
        return

    await player.stop()
    await ctx.send("⏹️ Stopped.")


# ============================================================
# LEAVE
# ============================================================

@bot.command()
async def leave(ctx):
    player = ctx.guild.voice_client

    if not isinstance(player, wavelink.Player):
        await ctx.send("❌ I'm not in a voice channel.")
        return

    await player.disconnect()
    await ctx.send("👋 Left the voice channel.")


# ============================================================
# PING
# ============================================================

@bot.command()
async def ping(ctx):
    discord_ping = round(bot.latency * 1000)

    try:
        node = wavelink.Pool.get_node()

        await ctx.send(
            f"🏓 Discord: `{discord_ping}ms`\n"
            f"🎵 Lavalink: `{node.status}`"
        )

    except Exception:
        await ctx.send(
            f"🏓 Discord: `{discord_ping}ms`\n"
            f"🎵 Lavalink: `Disconnected`"
        )


# ============================================================
# COMMAND ERROR
# ============================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing argument.")
        return

    print("=" * 60)
    print("❌ COMMAND ERROR")
    print(f"Command: {ctx.command}")
    print(f"Type: {type(error).__name__}")
    print(f"Error: {error}")
    print("=" * 60)


# ============================================================
# START
# ============================================================

async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
