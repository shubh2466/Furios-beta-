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

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = os.getenv("LAVALINK_PORT", "2333")
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

for prefix in ("https://", "http://"):
    if host.startswith(prefix):
        host = host[len(prefix):]

host = host.rstrip("/")

if LAVALINK_PORT:
    LAVALINK_URI = f"{LAVALINK_SCHEME}://{host}:{LAVALINK_PORT}"
else:
    LAVALINK_URI = f"{LAVALINK_SCHEME}://{host}"

print(f"🔌 Lavalink URI: {LAVALINK_URI}")


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


# ============================================================
# GLOBAL STATE
# ============================================================

node_connected = asyncio.Event()


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"✅ Logged in as: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print("=" * 60)

    # Avoid creating duplicate nodes after reconnects.
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
    node_connected.set()

    print("=" * 60)
    print(f"🟢 Lavalink READY: {payload.node.identifier}")
    print(f"📡 Node status: {payload.node.status}")
    print("=" * 60)


@bot.event
async def on_wavelink_node_closed(payload):
    node_connected.clear()

    print("=" * 60)
    print("🔴 Lavalink NODE CLOSED")
    print(f"Node: {payload.node.identifier}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_start(payload):
    player = payload.player
    track = payload.track

    print("=" * 60)
    print("▶️ TRACK START")
    print(f"Guild: {player.guild.id if player and player.guild else 'Unknown'}")
    print(f"Track: {track.title}")
    print(f"Player connected: {player.connected if player else False}")
    print(f"Player ping: {player.ping if player else 'Unknown'}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_exception(payload):
    print("=" * 60)
    print("❌ TRACK EXCEPTION")
    print(f"Track: {payload.track.title}")
    print(f"Exception: {payload.exception}")
    print(f"Message: {payload.exception.message}")
    print(f"Severity: {payload.exception.severity}")
    print(f"Cause: {payload.exception.cause}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_stuck(payload):
    print("=" * 60)
    print("⚠️ TRACK STUCK")
    print(f"Track: {payload.track.title}")
    print(f"Threshold: {payload.threshold} ms")
    print("=" * 60)


@bot.event
async def on_wavelink_player_update(payload):
    player = payload.player

    if player is None:
        return

    print(
        f"📶 PLAYER UPDATE | "
        f"guild={player.guild.id if player.guild else 'unknown'} "
        f"connected={payload.connected} "
        f"ping={payload.ping}ms "
        f"position={payload.position}ms"
    )


@bot.event
async def on_wavelink_websocket_closed(payload):
    print("=" * 60)
    print("🔴 LAVALINK VOICE WEBSOCKET CLOSED")
    print(f"Code: {payload.code}")
    print(f"Reason: {payload.reason}")
    print(f"By remote: {payload.by_remote}")
    print("=" * 60)


# ============================================================
# HELPERS
# ============================================================

async def get_player(ctx: commands.Context) -> wavelink.Player | None:
    player = ctx.guild.voice_client

    if isinstance(player, wavelink.Player):
        return player

    return None


async def ensure_player(ctx: commands.Context) -> wavelink.Player:
    if not ctx.author.voice:
        raise RuntimeError("Join a voice channel first.")

    player = await get_player(ctx)

    if player:
        if player.channel != ctx.author.voice.channel:
            await player.move_to(ctx.author.voice.channel)

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
# JOIN
# ============================================================

@bot.command()
async def join(ctx: commands.Context):

    try:
        player = await ensure_player(ctx)

        await ctx.send(
            f"✅ Joined **{player.channel.name}**"
        )

    except Exception as exc:
        print("=" * 60)
        print("❌ JOIN ERROR")
        print(f"Type: {type(exc).__name__}")
        print(f"Error: {exc}")
        print("=" * 60)

        await ctx.send(
            f"❌ Voice error: `{type(exc).__name__}`"
        )


# ============================================================
# PLAY
# ============================================================

@bot.command()
async def play(ctx: commands.Context, *, query: str):

    try:
        # --------------------------------------------
        # Wait for Lavalink
        # --------------------------------------------

        if not node_connected.is_set():

            print("⏳ Waiting for Lavalink...")

            try:
                await asyncio.wait_for(
                    node_connected.wait(),
                    timeout=15,
                )

            except asyncio.TimeoutError:
                await ctx.send(
                    "❌ Lavalink is not ready."
                )
                return

        # --------------------------------------------
        # Voice connection
        # --------------------------------------------

        player = await ensure_player(ctx)

        print(
            f"🎵 Player state before search | "
            f"connected={player.connected} "
            f"playing={player.playing} "
            f"ping={player.ping}"
        )

        # --------------------------------------------
        # Search
        # --------------------------------------------

        print(f"🔎 Searching: {query}")

        if query.startswith(("http://", "https://")):
            search_query = query
        else:
            search_query = f"ytsearch:{query}"

        results = await wavelink.Playable.search(
            search_query
        )

        if not results:
            await ctx.send("❌ No results found.")
            return

        # --------------------------------------------
        # Select track
        # --------------------------------------------

        if isinstance(results, wavelink.Playlist):

            if not results.tracks:
                await ctx.send("❌ Playlist is empty.")
                return

            track = results.tracks[0]

        else:
            track = results[0]

        print("=" * 60)
        print("🎵 TRACK SELECTED")
        print(f"Title: {track.title}")
        print(f"Author: {track.author}")
        print(f"Identifier: {track.identifier}")
        print(f"Source: {track.source}")
        print("=" * 60)

        # --------------------------------------------
        # Play
        # --------------------------------------------

        started = await player.play(
            track,
            replace=True,
        )

        print("=" * 60)
        print("✅ PLAY REQUEST SENT")
        print(f"Track: {started.title}")
        print(f"Connected: {player.connected}")
        print(f"Playing: {player.playing}")
        print(f"Ping: {player.ping}ms")
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
# PAUSE
# ============================================================

@bot.command()
async def pause(ctx: commands.Context):

    player = await get_player(ctx)

    if not player:
        await ctx.send("❌ I'm not connected.")
        return

    await player.pause(True)

    await ctx.send("⏸️ Paused.")


# ============================================================
# RESUME
# ============================================================

@bot.command()
async def resume(ctx: commands.Context):

    player = await get_player(ctx)

    if not player:
        await ctx.send("❌ I'm not connected.")
        return

    await player.pause(False)

    await ctx.send("▶️ Resumed.")


# ============================================================
# STOP
# ============================================================

@bot.command()
async def stop(ctx: commands.Context):

    player = await get_player(ctx)

    if not player:
        await ctx.send("❌ I'm not connected.")
        return

    await player.stop()

    await ctx.send("⏹️ Stopped.")


# ============================================================
# LEAVE
# ============================================================

@bot.command()
async def leave(ctx: commands.Context):

    player = await get_player(ctx)

    if not player:
        await ctx.send("❌ I'm not in a voice channel.")
        return

    await player.disconnect()

    await ctx.send("👋 Left the voice channel.")


# ============================================================
# NOW PLAYING
# ============================================================

@bot.command()
async def nowplaying(ctx: commands.Context):

    player = await get_player(ctx)

    if not player or not player.current:
        await ctx.send("❌ Nothing is playing.")
        return

    track = player.current

    await ctx.send(
        f"🎵 **{track.title}**\n"
        f"⏱️ `{player.position // 1000}s`"
    )


# ============================================================
# PING
# ============================================================

@bot.command()
async def ping(ctx: commands.Context):

    discord_ping = round(bot.latency * 1000)

    try:
        node = wavelink.Pool.get_node()

        if node:
            await ctx.send(
                f"🏓 Discord: `{discord_ping}ms`\n"
                f"🎵 Lavalink: `{node.status}`"
            )
        else:
            await ctx.send(
                f"🏓 Discord: `{discord_ping}ms`\n"
                f"🎵 Lavalink: `No node`"
            )

    except Exception:
        await ctx.send(
            f"🏓 Discord: `{discord_ping}ms`\n"
            f"🎵 Lavalink: `Disconnected`"
        )


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing command argument.")
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
