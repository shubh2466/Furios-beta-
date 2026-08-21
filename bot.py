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
    host = host[8:]
elif host.startswith("http://"):
    host = host[7:]

host = host.rstrip("/")

LAVALINK_URI = f"{LAVALINK_SCHEME}://{host}:{LAVALINK_PORT}"

print("=" * 60)
print(f"🔌 Lavalink URI: {LAVALINK_URI}")
print("=" * 60)


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

lavalink_ready = asyncio.Event()


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print("=" * 60)
    print(f"✅ Logged in as: {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print("=" * 60)

    # Prevent duplicate nodes after reconnect
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

        print("🔌 Lavalink connection started.")

    except Exception as exc:

        print("=" * 60)
        print("❌ LAVALINK CONNECTION ERROR")
        print(f"Type: {type(exc).__name__}")
        print(f"Error: {exc}")
        print("=" * 60)


# ============================================================
# LAVALINK NODE EVENTS
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


# ============================================================
# TRACK EVENTS
# ============================================================

@bot.event
async def on_wavelink_track_start(payload):

    player = payload.player
    track = payload.track

    print("=" * 60)
    print("▶️ TRACK START")
    print(f"Track: {track.title}")
    print(f"Identifier: {track.identifier}")
    print(
        f"Player connected: "
        f"{player.connected if player else 'unknown'}"
    )
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
    print(f"Threshold: {payload.threshold}")
    print("=" * 60)


@bot.event
async def on_wavelink_track_end(payload):

    print("=" * 60)
    print("⏹️ TRACK END")
    print(f"Track: {payload.track.title}")
    print(f"Reason: {payload.reason}")
    print("=" * 60)


# ============================================================
# PLAYER / VOICE EVENTS
# ============================================================

@bot.event
async def on_wavelink_player_update(payload):

    player = payload.player

    print(
        f"📶 PLAYER UPDATE | "
        f"guild={player.guild.id if player and player.guild else 'unknown'} "
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
    print(f"Remote: {payload.by_remote}")
    print("=" * 60)


# ============================================================
# GET PLAYER
# ============================================================

def get_player(ctx: commands.Context):

    player = ctx.guild.voice_client

    if isinstance(player, wavelink.Player):
        return player

    return None


# ============================================================
# ENSURE VOICE CONNECTION
# ============================================================

async def ensure_player(ctx: commands.Context):

    if not ctx.author.voice:
        raise RuntimeError(
            "You must join a voice channel first."
        )

    player = get_player(ctx)

    if player:

        # Move player if user is in another channel
        if player.channel != ctx.author.voice.channel:

            await player.move_to(
                ctx.author.voice.channel
            )

        return player

    channel = ctx.author.voice.channel

    print(
        f"🔵 Connecting to Discord voice: {channel.name}"
    )

    player = await channel.connect(
        cls=wavelink.Player,
        self_deaf=True
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
async def join(ctx):

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
async def play(ctx, *, query: str):

    try:

        # ----------------------------------------------------
        # Wait for Lavalink
        # ----------------------------------------------------

        if not lavalink_ready.is_set():

            print("⏳ Waiting for Lavalink...")

            try:

                await asyncio.wait_for(
                    lavalink_ready.wait(),
                    timeout=15
                )

            except asyncio.TimeoutError:

                await ctx.send(
                    "❌ Lavalink did not become ready."
                )

                return

        # ----------------------------------------------------
        # Connect to Discord voice
        # ----------------------------------------------------

        player = await ensure_player(ctx)

        print("=" * 60)
        print("🎵 PLAYER BEFORE SEARCH")
        print(f"Connected: {player.connected}")
        print(f"Playing: {player.playing}")
        print(f"Ping: {player.ping}")
        print("=" * 60)

        # ----------------------------------------------------
        # Build search identifier
        # ----------------------------------------------------

        query = query.strip()

        if not query:
            await ctx.send("❌ Enter a song name or URL.")
            return

        if query.startswith("https://") or query.startswith("http://"):

            identifier = query

        else:

            identifier = f"ytsearch:{query}"

        print(
            f"🔎 Searching Lavalink: {identifier}"
        )

        # ----------------------------------------------------
        # Search with explicit timeout
        # ----------------------------------------------------

        try:

            results = await asyncio.wait_for(
                wavelink.Playable.search(identifier),
                timeout=20
            )

        except asyncio.TimeoutError:

            print("=" * 60)
            print("❌ SEARCH TIMEOUT")
            print("Lavalink did not return search results within 20 seconds.")
            print("=" * 60)

            await ctx.send(
                "❌ Lavalink search timed out."
            )

            return

        except Exception as exc:

            print("=" * 60)
            print("❌ SEARCH ERROR")
            print(f"Type: {type(exc).__name__}")
            print(f"Error: {exc}")
            print("=" * 60)

            await ctx.send(
                f"❌ Search error: `{type(exc).__name__}`"
            )

            return

        # ----------------------------------------------------
        # Search result check
        # ----------------------------------------------------

        print(
            f"✅ Search returned: {type(results).__name__}"
        )

        if not results:

            await ctx.send(
                "❌ No results found."
            )

            return

        # ----------------------------------------------------
        # Select first track
        # ----------------------------------------------------

        if isinstance(results, wavelink.Playlist):

            if not results.tracks:

                await ctx.send(
                    "❌ Playlist contains no tracks."
                )

                return

            track = results.tracks[0]

        else:

            track = results[0]

        print("=" * 60)
        print("🎵 TRACK SELECTED")
        print(f"Title: {track.title}")
        print(f"Author: {track.author}")
        print(f"Identifier: {track.identifier}")
        print(f"URI: {track.uri}")
        print(f"Source: {track.source}")
        print("=" * 60)

        # ----------------------------------------------------
        # Send play request
        # ----------------------------------------------------

        print("▶️ Sending play request to Lavalink...")

        try:

            await asyncio.wait_for(
                player.play(
                    track,
                    replace=True
                ),
                timeout=20
            )

        except asyncio.TimeoutError:

            print("=" * 60)
            print("❌ PLAY REQUEST TIMEOUT")
            print("=" * 60)

            await ctx.send(
                "❌ Lavalink play request timed out."
            )

            return

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        print("=" * 60)
        print("✅ PLAY REQUEST SENT")
        print(f"Track: {track.title}")
        print(f"Connected: {player.connected}")
        print(f"Playing: {player.playing}")
        print(f"Ping: {player.ping}ms")
        print("=" * 60)

        await ctx.send(
            f"▶️ **{track.title}**"
        )

    except Exception as exc:

        print("=" * 60)
        print("❌ PLAY COMMAND ERROR")
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
async def pause(ctx):

    player = get_player(ctx)

    if not player:
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

    player = get_player(ctx)

    if not player:
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

    player = get_player(ctx)

    if not player:
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

    player = get_player(ctx)

    if not player:
        await ctx.send(
            "❌ I'm not in a voice channel."
        )
        return

    await player.disconnect()

    await ctx.send(
        "👋 Left the voice channel."
    )


# ============================================================
# NOW PLAYING
# ============================================================

@bot.command()
async def nowplaying(ctx):

    player = get_player(ctx)

    if not player or not player.current:

        await ctx.send(
            "❌ Nothing is playing."
        )

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
            f"🎵 Lavalink: `Disconnected`"
        )


# ============================================================
# COMMAND ERROR
# ============================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ Missing command argument."
        )

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
