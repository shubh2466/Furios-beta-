import asyncio
import json
import os
import traceback
from typing import Optional

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

LAVALINK_HOST = os.getenv(
    "LAVALINK_HOST",
    "furiouslavalink-production-3db0.up.railway.app"
)

LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "443"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

DEFAULT_PREFIX = "!"
IDLE_TIMEOUT = 300
DATA_FILE = "guild_data.json"


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not LAVALINK_PASSWORD:
    raise RuntimeError("LAVALINK_PASSWORD is missing.")


# ============================================================
# SAVED GUILD DATA
# ============================================================

guild_prefix = {}
guild_loop = {}
guild_247 = {}
idle_tasks = {}
voice_locks = {}


def load_data():
    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        guild_prefix.update(
            {int(k): v for k, v in data.get("prefix", {}).items()}
        )

        guild_loop.update(
            {int(k): v for k, v in data.get("loop", {}).items()}
        )

        guild_247.update(
            {int(k): v for k, v in data.get("247", {}).items()}
        )

        print("💾 Guild settings loaded.")

    except Exception:
        print("⚠️ Failed to load guild_data.json")
        traceback.print_exc()


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "prefix": {
                        str(k): v
                        for k, v in guild_prefix.items()
                    },
                    "loop": {
                        str(k): v
                        for k, v in guild_loop.items()
                    },
                    "247": {
                        str(k): v
                        for k, v in guild_247.items()
                    },
                },
                f,
                indent=4
            )

    except Exception:
        print("⚠️ Failed to save guild_data.json")
        traceback.print_exc()


load_data()


# ============================================================
# INTENTS
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True


# ============================================================
# BOT
# ============================================================

class Furious(commands.Bot):

    async def setup_hook(self):

        print()
        print("========================================")
        print("🔌 Connecting to Lavalink...")
        print("========================================")

        uri = f"https://{LAVALINK_HOST}:{LAVALINK_PORT}"

        node = wavelink.Node(
            identifier="Furious-Lavalink",
            uri=uri,
            password=LAVALINK_PASSWORD
        )

        try:
            await wavelink.Pool.connect(
                nodes=[node],
                client=self
            )

            print("✅ Lavalink connection established.")

        except Exception as e:
            print("❌ Lavalink connection failed.")
            print(f"{type(e).__name__}: {e}")
            traceback.print_exc()

        self.add_view(MusicControls())


bot = Furious(
    command_prefix=lambda bot, message: (
        guild_prefix.get(
            message.guild.id,
            DEFAULT_PREFIX
        )
        if message.guild
        else DEFAULT_PREFIX
    ),
    intents=intents,
    help_command=None
)


# ============================================================
# COLORS
# ============================================================

COLOR_MAIN = discord.Color.blurple()
COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_WARNING = discord.Color.orange()
COLOR_MUSIC = discord.Color.purple()
COLOR_PAUSE = discord.Color.gold()


# ============================================================
# EMOJIS
# ============================================================

SPOTIFY = "<:214004pixelspotify:1537699774596386926>"
SKIP = "<:22838skip:1537702524218511452>"
PAUSE = "<:776450pause:1537702507210612786>"
TICK = "<:763305tick:1537700918722691133>"
ERROR = "<a:880726error:1537700477955735622>"


# ============================================================
# EMBED
# ============================================================

def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = COLOR_MAIN
):
    return discord.Embed(
        title=title,
        description=description,
        color=color
    )


# ============================================================
# TIME
# ============================================================

def format_time(ms: Optional[int]) -> str:

    if ms is None:
        return "00:00"

    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return "00:00"

    seconds = max(0, ms // 1000)

    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    return f"{minutes:02}:{seconds:02}"


# ============================================================
# TRACK HELPERS
# ============================================================

def artwork(track):

    return getattr(track, "artwork", None)


def loop_name(mode):

    return {
        "off": "Off",
        "track": "🔂 Track",
        "queue": "🔁 Queue"
    }.get(mode, "Off")


# ============================================================
# YOUTUBE SEARCH / URL LOADING
# ============================================================

async def search_youtube(query: str):

    query = query.strip()

    if not query:
        return None

    # --------------------------------------------------------
    # DIRECT URL
    # --------------------------------------------------------

    if query.startswith(("http://", "https://")):

        print(f"🔗 Loading URL directly:")
        print(query)

        try:
            results = await wavelink.Playable.search(query)

        except Exception as e:

            print("❌ Direct URL loading failed.")
            print(f"{type(e).__name__}: {e}")

            traceback.print_exc()

            return None

        if not results:
            print("❌ Lavalink returned no result for URL.")
            return None

        # Playlist
        if isinstance(results, wavelink.Playlist):

            if not results.tracks:
                return None

            return results.tracks[0]

        # Normal track result
        return results[0]

    # --------------------------------------------------------
    # YOUTUBE SEARCH
    # --------------------------------------------------------

    print(f"🔎 YouTube search: {query}")

    try:

        results = await wavelink.Playable.search(
            query,
            source=wavelink.TrackSource.YouTube
        )

    except Exception as e:

        print("❌ YouTube search failed.")
        print(f"{type(e).__name__}: {e}")

        traceback.print_exc()

        return None

    if not results:

        print("❌ No YouTube results.")

        return None

    print(f"✅ Found {len(results)} result(s)")

    return results[0]


# ============================================================
# PLAYER / VOICE CONNECTION
# ============================================================

def get_voice_lock(guild_id: int) -> asyncio.Lock:
    lock = voice_locks.get(guild_id)

    if lock is None:
        lock = asyncio.Lock()
        voice_locks[guild_id] = lock

    return lock


async def disconnect_stale_player(guild):
    """Remove a voice client that exists locally but is no longer connected."""
    player = guild.voice_client

    if not player:
        return

    try:
        connected = player.is_connected()
    except Exception:
        connected = True

    if connected:
        return

    print(f"⚠️ Removing stale player for guild {guild.id}")

    try:
        await player.disconnect(force=True)
    except Exception:
        try:
            await player.disconnect()
        except Exception:
            pass

    await asyncio.sleep(0.5)


async def connect_voice(channel, timeout: float = 60.0):
    """
    Connect a fresh Wavelink player to Discord voice.

    The larger timeout is intentional: Discord voice negotiation can take
    longer than Wavelink's default 30 seconds on some hosts.
    """
    print(f"🔊 Connecting to voice channel: {channel.name}")

    player = await channel.connect(
        cls=wavelink.Player,
        timeout=timeout,
        reconnect=True,
        self_deaf=True,
        self_mute=False,
    )

    # Give discord.py a moment to finish registering the voice client.
    await asyncio.sleep(0.25)

    return player


async def get_player(ctx):
    if not ctx.guild:
        return None

    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send(
            embed=make_embed(
                f"{ERROR} Voice Channel Required",
                "Join a voice channel first.",
                COLOR_ERROR
            )
        )
        return None

    guild_id = ctx.guild.id
    target_channel = ctx.author.voice.channel

    async with get_voice_lock(guild_id):
        await disconnect_stale_player(ctx.guild)

        player = ctx.guild.voice_client

        # --------------------------------------------------------
        # EXISTING HEALTHY PLAYER
        # --------------------------------------------------------

        if player:
            player.home = ctx.channel

            try:
                connected = player.is_connected()
            except Exception:
                connected = False

            if connected:
                if player.channel != target_channel:
                    try:
                        print(
                            f"🔄 Moving from "
                            f"{player.channel.name} to {target_channel.name}"
                        )
                        await player.move_to(target_channel)
                    except Exception as e:
                        print(
                            f"⚠️ Move error: "
                            f"{type(e).__name__}: {e}"
                        )
                        return None

                return player

            # It existed but wasn't healthy.
            print(f"⚠️ Existing player is disconnected in guild {guild_id}")

            try:
                await player.disconnect(force=True)
            except Exception:
                pass

            await asyncio.sleep(0.5)

        # --------------------------------------------------------
        # FRESH CONNECTION
        # --------------------------------------------------------

        last_error = None

        # One retry handles transient Discord voice negotiation failures.
        for attempt in range(1, 3):
            try:
                print(
                    f"🔊 Voice connection attempt "
                    f"{attempt}/2 to {target_channel.name}"
                )

                player = await connect_voice(
                    target_channel,
                    timeout=60.0
                )

                player.home = ctx.channel

                print(
                    f"✅ Connected to voice channel: "
                    f"{target_channel.name}"
                )

                return player

            except wavelink.ChannelTimeoutException as e:
                last_error = e

                print(
                    f"⚠️ Discord voice connection timed out "
                    f"(attempt {attempt}/2)."
                )
                print(
                    "This is a Discord voice negotiation timeout, "
                    "not a Lavalink search error."
                )
                traceback.print_exc()

            except asyncio.TimeoutError as e:
                last_error = e

                print(
                    f"⚠️ Discord voice connection timed out "
                    f"(attempt {attempt}/2)."
                )
                traceback.print_exc()

            except Exception as e:
                last_error = e

                print(
                    f"❌ Voice connection attempt {attempt}/2 failed: "
                    f"{type(e).__name__}: {e}"
                )
                traceback.print_exc()

            # Clean up anything Discord/Wavelink left behind.
            stale = ctx.guild.voice_client

            if stale:
                try:
                    await stale.disconnect(force=True)
                except Exception:
                    try:
                        await stale.disconnect()
                    except Exception:
                        pass

            await asyncio.sleep(1.0)

        # --------------------------------------------------------
        # BOTH ATTEMPTS FAILED
        # --------------------------------------------------------

        print()
        print("========================================")
        print("❌ VOICE CONNECTION ERROR")
        print("========================================")

        if last_error:
            print(
                f"{type(last_error).__name__}: "
                f"{last_error}"
            )

        print("========================================")

        error_text = (
            "Discord voice connection timed out twice.\n\n"
            "Lavalink is connected, but Discord voice negotiation "
            "did not finish. Try joining/leaving the voice channel "
            "and run the command again."
        )

        if last_error and not isinstance(
            last_error,
            (
                wavelink.ChannelTimeoutException,
                asyncio.TimeoutError,
            )
        ):
            error_text = (
                f"`{type(last_error).__name__}: {last_error}`"
            )

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Voice Connection Failed",
                error_text,
                COLOR_ERROR
            )
        )

        return None


# ============================================================
# IDLE SYSTEM
# ============================================================

def cancel_idle(guild_id):

    task = idle_tasks.get(guild_id)

    if task and not task.done():

        task.cancel()

    idle_tasks.pop(guild_id, None)


def schedule_idle(player):

    if not player or not player.guild:
        return

    guild_id = player.guild.id

    if guild_247.get(guild_id, False):
        return

    cancel_idle(guild_id)

    async def disconnect_later():

        try:

            await asyncio.sleep(IDLE_TIMEOUT)

        except asyncio.CancelledError:

            return

        current = player.guild.voice_client

        if not current:
            return

        if guild_247.get(guild_id, False):
            return

        if (
            not current.playing
            and not current.current
            and not current.queue
        ):

            try:

                await current.disconnect()

                print(
                    f"👋 Auto-disconnected "
                    f"from {player.guild.name}"
                )

            except Exception:
                pass

    idle_tasks[guild_id] = asyncio.create_task(
        disconnect_later()
    )


# ============================================================
# NOW PLAYING EMBED
# ============================================================

def now_playing_embed(track, player):

    artist = getattr(
        track,
        "author",
        "Unknown Artist"
    )

    position = getattr(
        player,
        "position",
        0
    )

    length = getattr(
        track,
        "length",
        None
    )

    mode = guild_loop.get(
        player.guild.id,
        "off"
    )

    description = (
        f"## {track.title}\n\n"
        f"🎤 **Artist:** `{artist}`\n"
        f"🔁 **Loop:** `{loop_name(mode)}`\n\n"
        f"`{format_time(position)}` / "
        f"`{format_time(length)}`"
    )

    embed = discord.Embed(
        title=f"{SPOTIFY} Now Playing",
        description=description,
        color=COLOR_MUSIC
    )

    image = artwork(track)

    if image:
        embed.set_image(url=image)

    embed.set_footer(
        text="Furious Music • Playback Controls"
    )

    return embed


# ============================================================
# PLAY NEXT
# ============================================================

async def play_next(player):

    if not player or not player.guild:
        return

    guild_id = player.guild.id

    mode = guild_loop.get(
        guild_id,
        "off"
    )

    current = player.current

    # --------------------------------------------------------
    # TRACK LOOP
    # --------------------------------------------------------

    if mode == "track" and current:

        try:

            await player.play(current)

            return

        except Exception:

            traceback.print_exc()

    # --------------------------------------------------------
    # QUEUE LOOP
    # --------------------------------------------------------

    if mode == "queue" and current:

        try:

            player.queue.put(current)

        except Exception:

            traceback.print_exc()

    # --------------------------------------------------------
    # NEXT TRACK
    # --------------------------------------------------------

    if player.queue:

        try:

            next_track = player.queue.get()

            await player.play(next_track)

            return

        except Exception:

            print("❌ Failed to play next track.")

            traceback.print_exc()

    # --------------------------------------------------------
    # NOTHING LEFT
    # --------------------------------------------------------

    schedule_idle(player)


# ============================================================
# MUSIC BUTTONS
# ============================================================

class MusicControls(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=None)

    async def get_player(self, interaction):

        player = interaction.guild.voice_client

        if not player:

            await interaction.response.send_message(
                "I'm not connected to a voice channel.",
                ephemeral=True
            )

            return None

        if (
            not interaction.user.voice
            or
            interaction.user.voice.channel != player.channel
        ):

            await interaction.response.send_message(
                "You must be in my voice channel.",
                ephemeral=True
            )

            return None

        return player

    # --------------------------------------------------------
    # PAUSE
    # --------------------------------------------------------

    @discord.ui.button(
        emoji=discord.PartialEmoji(
            name="776450pause",
            id=1537702507210612786
        ),
        style=discord.ButtonStyle.secondary,
        custom_id="furious:pause"
    )
    async def pause_button(
        self,
        interaction,
        button
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        if player.paused:

            await player.pause(False)

            await interaction.response.send_message(
                "▶️ Resumed.",
                ephemeral=True
            )

        else:

            await player.pause(True)

            await interaction.response.send_message(
                f"{PAUSE} Paused.",
                ephemeral=True
            )

    # --------------------------------------------------------
    # SKIP
    # --------------------------------------------------------

    @discord.ui.button(
        emoji=discord.PartialEmoji(
            name="22838skip",
            id=1537702524218511452
        ),
        style=discord.ButtonStyle.secondary,
        custom_id="furious:skip"
    )
    async def skip_button(
        self,
        interaction,
        button
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        if not player.current:

            await interaction.response.send_message(
                "Nothing is playing.",
                ephemeral=True
            )

            return

        await player.skip()

        await interaction.response.send_message(
            f"{SKIP} Skipped.",
            ephemeral=True
        )

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    @discord.ui.button(
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id="furious:stop"
    )
    async def stop_button(
        self,
        interaction,
        button
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        player.queue.clear()

        guild_loop[
            interaction.guild.id
        ] = "off"

        save_data()

        await player.stop()

        await interaction.response.send_message(
            "⏹️ Stopped and cleared the queue.",
            ephemeral=True
        )

    # --------------------------------------------------------
    # LOOP
    # --------------------------------------------------------

    @discord.ui.button(
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        custom_id="furious:loop"
    )
    async def loop_button(
        self,
        interaction,
        button
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        modes = [
            "off",
            "track",
            "queue"
        ]

        current = guild_loop.get(
            interaction.guild.id,
            "off"
        )

        next_mode = modes[
            (modes.index(current) + 1)
            % len(modes)
        ]

        guild_loop[
            interaction.guild.id
        ] = next_mode

        save_data()

        await interaction.response.send_message(
            f"🔁 Loop: "
            f"**{loop_name(next_mode)}**",
            ephemeral=True
        )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    print()
    print("========================================")
    print(f"🤖 Logged in as {bot.user}")
    print(f"🌐 Servers: {len(bot.guilds)}")
    print(f"🐍 discord.py: {discord.__version__}")
    print(f"🎵 Wavelink: {wavelink.__version__}")
    print("========================================")
    print()


# ============================================================
# LAVALINK NODE READY
# ============================================================

@bot.event
async def on_wavelink_node_ready(payload):

    print(
        f"{TICK} Lavalink node ready: "
        f"{payload.node.identifier}"
    )


# ============================================================
# TRACK START
# ============================================================

@bot.event
async def on_wavelink_track_start(payload):

    player = payload.player

    if not player:
        return

    cancel_idle(
        player.guild.id
    )

    print(
        f"🎵 Playing: "
        f"{payload.track.title}"
    )

    channel = getattr(
        player,
        "home",
        None
    )

    if channel:

        try:

            await channel.send(
                embed=now_playing_embed(
                    payload.track,
                    player
                ),
                view=MusicControls()
            )

        except Exception:

            traceback.print_exc()


# ============================================================
# TRACK END
# ============================================================

@bot.event
async def on_wavelink_track_end(payload):

    player = payload.player

    if not player:
        return

    reason = getattr(
        payload,
        "reason",
        None
    )

    print(
        f"🏁 Track ended: "
        f"{payload.track.title} "
        f"({reason})"
    )

    if str(reason).lower() == "replaced":
        return

    await play_next(player)


# ============================================================
# TRACK EXCEPTION
# ============================================================

@bot.event
async def on_wavelink_track_exception(payload):

    player = payload.player
    track = payload.track

    print()
    print("========================================")
    print("❌ LAVALINK TRACK EXCEPTION")
    print("========================================")

    if track:

        print(
            f"Track: {track.title}"
        )

        print(
            f"URI: "
            f"{getattr(track, 'uri', None)}"
        )

    print(
        f"Exception: "
        f"{payload.exception}"
    )

    print("========================================")

    if player:

        channel = getattr(
            player,
            "home",
            None
        )

        if channel:

            try:

                await channel.send(
                    embed=make_embed(
                        f"{ERROR} Track Error",
                        (
                            f"**{track.title if track else 'Track'}** "
                            f"couldn't be played."
                        ),
                        COLOR_ERROR
                    )
                )

            except Exception:
                pass


# ============================================================
# TRACK STUCK
# ============================================================

@bot.event
async def on_wavelink_track_stuck(payload):

    player = payload.player
    track = payload.track

    print(
        f"⚠️ Track stuck: "
        f"{track.title if track else 'Unknown'}"
    )

    if player:

        await play_next(player)


# ============================================================
# VOICE STATE
# ============================================================

@bot.event
async def on_voice_state_update(
    member,
    before,
    after
):

    if member.bot:
        return

    for player in list(bot.voice_clients):

        if guild_247.get(
            player.guild.id,
            False
        ):
            continue

        channel = player.channel

        if not channel:
            continue

        humans = [
            m
            for m in channel.members
            if not m.bot
        ]

        if not humans:

            try:

                await player.disconnect()

                print(
                    f"👋 Empty VC, "
                    f"disconnected from "
                    f"{player.guild.name}"
                )

            except Exception:
                pass


# ============================================================
# PLAY
# ============================================================

@bot.command()
async def play(
    ctx,
    *,
    query: str
):

    player = await get_player(ctx)

    if not player:
        return

    cancel_idle(
        ctx.guild.id
    )

    try:

        print()
        print("========================================")
        print(f"🔎 Input: {query}")
        print("========================================")

        track = await search_youtube(
            query
        )

        if not track:

            await ctx.send(
                embed=make_embed(
                    f"{ERROR} No Results",
                    (
                        f"No YouTube results found "
                        f"for `{query}`."
                    ),
                    COLOR_ERROR
                )
            )

            return

        print(
            f"🎵 Found: "
            f"{track.title}"
        )

        print(
            f"🔗 URI: "
            f"{getattr(track, 'uri', None)}"
        )

        # ----------------------------------------------------
        # ALREADY PLAYING
        # ----------------------------------------------------

        if player.current:

            player.queue.put(track)

            position = len(player.queue)

            await ctx.send(
                embed=make_embed(
                    "🎵 Added to Queue",
                    (
                        f"**{track.title}**\n"
                        f"Position: `#{position}`"
                    ),
                    COLOR_SUCCESS
                )
            )

            return

        # ----------------------------------------------------
        # NOTHING PLAYING
        # ----------------------------------------------------

        await player.play(track)

        await ctx.send(
            embed=make_embed(
                f"{TICK} Now Playing",
                f"**{track.title}**",
                COLOR_SUCCESS
            ),
            view=MusicControls()
        )

    except Exception as e:

        print()
        print("========================================")
        print("❌ PLAY COMMAND ERROR")
        print("========================================")

        traceback.print_exc()

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Playback Error",
                f"`{type(e).__name__}: {e}`",
                COLOR_ERROR
            )
        )


# ============================================================
# SKIP
# ============================================================

@bot.command()
async def skip(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR
            )
        )

        return

    await player.skip()

    await ctx.send(
        embed=make_embed(
            f"{SKIP} Skipped",
            "Skipped the current track.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# PAUSE
# ============================================================

@bot.command()
async def pause(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR
            )
        )

        return

    if player.paused:

        await player.pause(False)

        await ctx.send(
            embed=make_embed(
                "▶️ Resumed",
                "Playback resumed.",
                COLOR_SUCCESS
            )
        )

    else:

        await player.pause(True)

        await ctx.send(
            embed=make_embed(
                f"{PAUSE} Paused",
                "Playback paused.",
                COLOR_PAUSE
            )
        )


# ============================================================
# STOP
# ============================================================

@bot.command()
async def stop(ctx):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=make_embed(
                "❌ Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR
            )
        )

        return

    player.queue.clear()

    guild_loop[
        ctx.guild.id
    ] = "off"

    save_data()

    await player.stop()

    await ctx.send(
        embed=make_embed(
            "⏹️ Stopped",
            "Playback stopped and queue cleared.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# QUEUE
# ============================================================

@bot.command()
async def queue(ctx):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=make_embed(
                "📋 Queue",
                "I'm not connected to a voice channel.",
                COLOR_ERROR
            )
        )

        return

    lines = []

    if player.current:

        lines.append(
            f"▶️ **Now:** {player.current.title}"
        )

    if player.queue:

        for index, track in enumerate(
            list(player.queue),
            start=1
        ):

            lines.append(
                f"`{index}.` {track.title}"
            )

    if not lines:

        lines.append(
            "The queue is empty."
        )

    await ctx.send(
        embed=make_embed(
            "📋 Music Queue",
            "\n".join(lines),
            COLOR_MUSIC
        )
    )


# ============================================================
# NOW PLAYING
# ============================================================

@bot.command(
    aliases=["np"]
)
async def nowplaying(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR
            )
        )

        return

    await ctx.send(
        embed=now_playing_embed(
            player.current,
            player
        ),
        view=MusicControls()
    )


# ============================================================
# LOOP
# ============================================================

@bot.command()
async def loop(
    ctx,
    mode: Optional[str] = None
):

    modes = [
        "off",
        "track",
        "queue"
    ]

    current = guild_loop.get(
        ctx.guild.id,
        "off"
    )

    if mode:

        mode = mode.lower()

        if mode not in modes:

            await ctx.send(
                embed=make_embed(
                    "❌ Invalid Loop",
                    (
                        "Use:\n"
                        "`!loop off`\n"
                        "`!loop track`\n"
                        "`!loop queue`"
                    ),
                    COLOR_ERROR
                )
            )

            return

        current = mode

    else:

        current = modes[
            (modes.index(current) + 1)
            % len(modes)
        ]

    guild_loop[
        ctx.guild.id
    ] = current

    save_data()

    await ctx.send(
        embed=make_embed(
            "🔁 Loop",
            f"Loop mode: **{loop_name(current)}**",
            COLOR_SUCCESS
        )
    )


# ============================================================
# 24/7
# ============================================================

@bot.command(name="247")
async def twenty_four_seven(ctx):

    guild_id = ctx.guild.id

    current = guild_247.get(
        guild_id,
        False
    )

    guild_247[
        guild_id
    ] = not current

    save_data()

    status = (
        "Enabled ♾️"
        if not current
        else "Disabled"
    )

    await ctx.send(
        embed=make_embed(
            "♾️ 24/7 Mode",
            f"24/7 mode: **{status}**",
            COLOR_SUCCESS
        )
    )


# ============================================================
# PREFIX
# ============================================================

@bot.command()
@commands.has_guild_permissions(
    manage_guild=True
)
async def prefix(
    ctx,
    new_prefix: Optional[str] = None
):

    if not new_prefix:

        current = guild_prefix.get(
            ctx.guild.id,
            DEFAULT_PREFIX
        )

        await ctx.send(
            embed=make_embed(
                "⚙️ Prefix",
                f"Current prefix: `{current}`",
                COLOR_MAIN
            )
        )

        return

    if len(new_prefix) > 5:

        await ctx.send(
            embed=make_embed(
                "❌ Invalid Prefix",
                "Prefix must be 5 characters or fewer.",
                COLOR_ERROR
            )
        )

        return

    guild_prefix[
        ctx.guild.id
    ] = new_prefix

    save_data()

    await ctx.send(
        embed=make_embed(
            "✅ Prefix Updated",
            f"New prefix: `{new_prefix}`",
            COLOR_SUCCESS
        )
    )


@prefix.error
async def prefix_error(ctx, error):

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            embed=make_embed(
                "❌ Permission Required",
                "You need **Manage Server** permission.",
                COLOR_ERROR
            )
        )


# ============================================================
# HELP
# ============================================================

@bot.command()
async def help(ctx):

    prefix_value = guild_prefix.get(
        ctx.guild.id,
        DEFAULT_PREFIX
    )

    description = (
        f"**🎵 Music**\n"
        f"`{prefix_value}play <song/url>`\n"
        f"`{prefix_value}skip`\n"
        f"`{prefix_value}pause`\n"
        f"`{prefix_value}stop`\n"
        f"`{prefix_value}queue`\n"
        f"`{prefix_value}nowplaying`\n"
        f"`{prefix_value}loop`\n\n"

        f"**⚙️ Settings**\n"
        f"`{prefix_value}247`\n"
        f"`{prefix_value}prefix <new prefix>`"
    )

    await ctx.send(
        embed=make_embed(
            "🔥 Furious Help",
            description,
            COLOR_MAIN
        )
    )


# ============================================================
# GENERAL COMMAND ERROR
# ============================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

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
            embed=make_embed(
                f"{ERROR} Missing Argument",
                "You didn't provide all required arguments.",
                COLOR_ERROR
            )
        )

        return

    if isinstance(
        error,
        commands.NoPrivateMessage
    ):

        return

    print()
    print("========================================")
    print("❌ COMMAND ERROR")
    print("========================================")

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__
    )

    print("========================================")


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    print("🔥 Starting Furious...")

    try:

        bot.run(TOKEN)

    except KeyboardInterrupt:

        print("🛑 Bot stopped.")

    except Exception:

        print("❌ Bot crashed.")

        traceback.print_exc()
