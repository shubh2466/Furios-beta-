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
# PERSISTENT DATA
# ============================================================

guild_prefix: dict[int, str] = {}
guild_loop: dict[int, str] = {}
guild_247: dict[int, bool] = {}

idle_tasks: dict[int, asyncio.Task] = {}

# One tracked player per guild.
players: dict[int, wavelink.Player] = {}

# Prevent two !play commands from modifying the same player
# simultaneously.
player_locks: dict[int, asyncio.Lock] = {}


def get_lock(guild_id: int) -> asyncio.Lock:
    lock = player_locks.get(guild_id)

    if lock is None:
        lock = asyncio.Lock()
        player_locks[guild_id] = lock

    return lock


def load_data():
    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        guild_prefix.update(
            {
                int(guild_id): prefix
                for guild_id, prefix in data.get("prefix", {}).items()
            }
        )

        guild_loop.update(
            {
                int(guild_id): mode
                for guild_id, mode in data.get("loop", {}).items()
            }
        )

        guild_247.update(
            {
                int(guild_id): enabled
                for guild_id, enabled in data.get("247", {}).items()
            }
        )

        print("💾 Guild settings loaded.")

    except Exception:
        print("⚠️ Failed to load guild_data.json")
        traceback.print_exc()


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "prefix": {
                        str(guild_id): prefix
                        for guild_id, prefix in guild_prefix.items()
                    },
                    "loop": {
                        str(guild_id): mode
                        for guild_id, mode in guild_loop.items()
                    },
                    "247": {
                        str(guild_id): enabled
                        for guild_id, enabled in guild_247.items()
                    },
                },
                file,
                indent=4,
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
# EMBEDS
# ============================================================

def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = COLOR_MAIN,
) -> discord.Embed:

    return discord.Embed(
        title=title,
        description=description,
        color=color,
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
# LOOP
# ============================================================

def loop_name(mode: str) -> str:

    return {
        "off": "Off",
        "track": "🔂 Track",
        "queue": "🔁 Queue",
    }.get(mode, "Off")


# ============================================================
# ARTWORK
# ============================================================

def get_artwork(track):

    return getattr(track, "artwork", None)


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

        print(f"🌐 Lavalink URI: {uri}")

        node = wavelink.Node(
            identifier="Furious-Lavalink",
            uri=uri,
            password=LAVALINK_PASSWORD,
        )

        try:

            await wavelink.Pool.connect(
                nodes=[node],
                client=self,
            )

            print("✅ Lavalink connection established.")

        except Exception as error:

            print("❌ Lavalink connection failed.")
            print(f"{type(error).__name__}: {error}")

            traceback.print_exc()

            raise

        # Persistent buttons.
        self.add_view(MusicControls())


bot = Furious(
    command_prefix=lambda _bot, message: (
        guild_prefix.get(
            message.guild.id,
            DEFAULT_PREFIX,
        )
        if message.guild
        else DEFAULT_PREFIX
    ),
    intents=intents,
    help_command=None,
)


# ============================================================
# YOUTUBE SEARCH
# ============================================================

async def search_track(query: str):

    query = query.strip()

    if not query:
        return None

    # --------------------------------------------------------
    # DIRECT URL
    # --------------------------------------------------------

    if query.startswith(("http://", "https://")):

        print()
        print("🔗 Direct URL")
        print(query)

        try:

            results = await wavelink.Playable.search(query)

        except Exception as error:

            print("❌ Direct URL search failed.")
            print(f"{type(error).__name__}: {error}")

            traceback.print_exc()

            return None

        if not results:
            return None

        # Playlist result.
        if isinstance(results, wavelink.Playlist):

            if not results.tracks:
                return None

            return results.tracks[0]

        return results[0]

    # --------------------------------------------------------
    # YOUTUBE SEARCH
    # --------------------------------------------------------

    print()
    print("🔎 YouTube search")
    print(query)

    try:

        results = await wavelink.Playable.search(
            query,
            source=wavelink.TrackSource.YouTube,
        )

    except Exception as error:

        print("❌ YouTube search failed.")
        print(f"{type(error).__name__}: {error}")

        traceback.print_exc()

        return None

    if not results:

        print("❌ No YouTube results.")

        return None

    print(f"✅ Found {len(results)} result(s)")

    return results[0]


# ============================================================
# PLAYER VALIDATION
# ============================================================

def is_valid_player(
    player: Optional[wavelink.Player],
    guild: discord.Guild,
) -> bool:

    if player is None:
        return False

    if player.guild is None:
        return False

    if player.guild.id != guild.id:
        return False

    # Discord-side voice connection.
    try:

        if not player.is_connected():
            return False

    except Exception:

        return False

    # Make sure this is still the guild's active voice client.
    current_voice = guild.voice_client

    if current_voice is not player:
        return False

    return True


# ============================================================
# REMOVE PLAYER
# ============================================================

async def remove_player(
    guild_id: int,
    disconnect: bool = True,
):

    player = players.pop(guild_id, None)

    cancel_idle(guild_id)

    if not player:
        return

    if disconnect:

        try:

            await player.disconnect()

        except Exception:

            pass


# ============================================================
# CONNECT / GET PLAYER
# ============================================================

async def get_player(ctx):

    guild = ctx.guild

    if guild is None:
        return None

    # --------------------------------------------------------
    # USER MUST BE IN VC
    # --------------------------------------------------------

    if not ctx.author.voice or not ctx.author.voice.channel:

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Voice Channel Required",
                "Join a voice channel first.",
                COLOR_ERROR,
            )
        )

        return None

    target_channel = ctx.author.voice.channel

    # --------------------------------------------------------
    # CHECK OUR TRACKED PLAYER
    # --------------------------------------------------------

    player = players.get(guild.id)

    if player:

        if is_valid_player(player, guild):

            player.home = ctx.channel

            # Move if user is in another channel.
            if player.channel != target_channel:

                try:

                    await player.move_to(target_channel)

                except Exception as error:

                    print(
                        f"⚠️ Failed to move player: "
                        f"{type(error).__name__}: {error}"
                    )

            return player

        # Old/stale player.
        print(
            f"⚠️ Removing stale player for guild {guild.id}"
        )

        await remove_player(guild.id)


    # --------------------------------------------------------
    # CHECK DISCORD VOICE CLIENT
    # --------------------------------------------------------

    existing = guild.voice_client

    if existing:

        try:
            await existing.disconnect()
        except Exception:
            pass

        players.pop(guild.id, None)


    # --------------------------------------------------------
    # CONNECT
    # --------------------------------------------------------

    try:

        print(
            f"🔊 Connecting to voice channel: "
            f"{target_channel.name}"
        )

        player = await target_channel.connect(
            cls=wavelink.Player
        )

        player.home = ctx.channel

        players[guild.id] = player

        print(
            f"✅ Connected to {target_channel.name}"
        )

        return player

    except Exception as error:

        print()
        print("========================================")
        print("❌ VOICE CONNECTION ERROR")
        print("========================================")

        traceback.print_exc()

        print("========================================")

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Voice Connection Failed",
                f"`{type(error).__name__}: {error}`",
                COLOR_ERROR,
            )
        )

        return None


# ============================================================
# RECONNECT PLAYER
# ============================================================

async def reconnect_player(ctx):

    guild_id = ctx.guild.id

    print(
        f"🔄 Rebuilding Lavalink player "
        f"for guild {guild_id}"
    )

    old_player = players.pop(guild_id, None)

    cancel_idle(guild_id)

    if old_player:

        try:
            await old_player.disconnect()
        except Exception:
            pass

    # Give Discord/Lavalink a moment to clean the old session.
    await asyncio.sleep(1)

    return await get_player(ctx)


# ============================================================
# PLAY WITH RECOVERY
# ============================================================

async def play_track(
    ctx,
    player: wavelink.Player,
    track,
):

    try:

        await player.play(track)

        return True

    except Exception as first_error:

        error_text = str(first_error).lower()

        # ----------------------------------------------------
        # LAVALINK 404 / DEAD PLAYER SESSION
        # ----------------------------------------------------

        if (
            "404" in error_text
            or "not found" in error_text
            or "/v4/sessions/" in error_text
        ):

            print()
            print("========================================")
            print("⚠️ LAVALINK PLAYER SESSION LOST")
            print("========================================")

            print(
                f"{type(first_error).__name__}: "
                f"{first_error}"
            )

            print("🔄 Reconnecting player...")

            traceback.print_exc()

            new_player = await reconnect_player(ctx)

            if not new_player:

                return False

            try:

                await new_player.play(track)

                print("✅ Playback recovered.")

                return True

            except Exception as second_error:

                print("❌ Playback recovery failed.")

                print(
                    f"{type(second_error).__name__}: "
                    f"{second_error}"
                )

                traceback.print_exc()

                return False

        # ----------------------------------------------------
        # OTHER ERROR
        # ----------------------------------------------------

        print("❌ Playback failed.")

        traceback.print_exc()

        return False


# ============================================================
# IDLE DISCONNECT
# ============================================================

def cancel_idle(guild_id: int):

    task = idle_tasks.pop(guild_id, None)

    if task and not task.done():

        task.cancel()


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

        current = players.get(guild_id)

        if not current:
            return

        if guild_247.get(guild_id, False):
            return

        try:

            if (
                not current.playing
                and not current.current
                and not current.queue
            ):

                print(
                    f"👋 Idle timeout: "
                    f"disconnecting from "
                    f"{player.guild.name}"
                )

                await remove_player(guild_id)

        except Exception:

            traceback.print_exc()

    idle_tasks[guild_id] = asyncio.create_task(
        disconnect_later()
    )


# ============================================================
# NOW PLAYING EMBED
# ============================================================

def now_playing_embed(
    track,
    player,
):

    artist = getattr(
        track,
        "author",
        "Unknown Artist",
    )

    position = getattr(
        player,
        "position",
        0,
    )

    length = getattr(
        track,
        "length",
        None,
    )

    mode = guild_loop.get(
        player.guild.id,
        "off",
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
        color=COLOR_MUSIC,
    )

    image = get_artwork(track)

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

    # Player must still be valid.
    if not is_valid_player(player, player.guild):

        print(
            f"⚠️ play_next ignored: invalid player "
            f"for guild {guild_id}"
        )

        return

    mode = guild_loop.get(
        guild_id,
        "off",
    )

    current = player.current

    # --------------------------------------------------------
    # TRACK LOOP
    # --------------------------------------------------------

    if mode == "track" and current:

        success = await play_track(
            player.home,
            player,
            current,
        )

        if success:
            return

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

    while player.queue:

        try:

            next_track = player.queue.get()

        except Exception:

            traceback.print_exc()

            break

        success = await play_track(
            player.home,
            player,
            next_track,
        )

        if success:

            return

        # If this track failed, continue with next one.
        print(
            f"⚠️ Skipping failed track: "
            f"{getattr(next_track, 'title', 'Unknown')}"
        )

    # --------------------------------------------------------
    # NOTHING LEFT
    # --------------------------------------------------------

    schedule_idle(player)


# ============================================================
# MUSIC BUTTONS
# ============================================================

class MusicControls(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    async def get_player(self, interaction):

        guild = interaction.guild

        if guild is None:

            await interaction.response.send_message(
                "This button can only be used in a server.",
                ephemeral=True,
            )

            return None

        player = players.get(guild.id)

        if not player or not is_valid_player(
            player,
            guild,
        ):

            await interaction.response.send_message(
                "I'm not connected to a voice channel.",
                ephemeral=True,
            )

            return None

        if (
            not interaction.user.voice
            or interaction.user.voice.channel != player.channel
        ):

            await interaction.response.send_message(
                "You must be in my voice channel.",
                ephemeral=True,
            )

            return None

        return player


    # ========================================================
    # PAUSE
    # ========================================================

    @discord.ui.button(
        emoji=discord.PartialEmoji(
            name="776450pause",
            id=1537702507210612786,
        ),
        style=discord.ButtonStyle.secondary,
        custom_id="furious:pause",
    )
    async def pause_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        try:

            if player.paused:

                await player.pause(False)

                await interaction.response.send_message(
                    "▶️ Resumed.",
                    ephemeral=True,
                )

            else:

                await player.pause(True)

                await interaction.response.send_message(
                    f"{PAUSE} Paused.",
                    ephemeral=True,
                )

        except Exception as error:

            await interaction.response.send_message(
                f"{ERROR} Failed to change playback state.",
                ephemeral=True,
            )

            print(
                f"Pause error: {type(error).__name__}: {error}"
            )


    # ========================================================
    # SKIP
    # ========================================================

    @discord.ui.button(
        emoji=discord.PartialEmoji(
            name="22838skip",
            id=1537702524218511452,
        ),
        style=discord.ButtonStyle.secondary,
        custom_id="furious:skip",
    )
    async def skip_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        if not player.current:

            await interaction.response.send_message(
                "Nothing is playing.",
                ephemeral=True,
            )

            return

        try:

            await player.skip()

            await interaction.response.send_message(
                f"{SKIP} Skipped.",
                ephemeral=True,
            )

        except Exception as error:

            await interaction.response.send_message(
                f"{ERROR} Skip failed.",
                ephemeral=True,
            )

            print(
                f"Skip error: {type(error).__name__}: {error}"
            )


    # ========================================================
    # STOP
    # ========================================================

    @discord.ui.button(
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id="furious:stop",
    )
    async def stop_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        guild_id = interaction.guild.id

        player.queue.clear()

        guild_loop[guild_id] = "off"

        save_data()

        try:

            await player.stop()

        except Exception:

            traceback.print_exc()

        await interaction.response.send_message(
            "⏹️ Stopped and cleared the queue.",
            ephemeral=True,
        )

        schedule_idle(player)


    # ========================================================
    # LOOP
    # ========================================================

    @discord.ui.button(
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        custom_id="furious:loop",
    )
    async def loop_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        player = await self.get_player(
            interaction
        )

        if not player:
            return

        modes = [
            "off",
            "track",
            "queue",
        ]

        guild_id = interaction.guild.id

        current = guild_loop.get(
            guild_id,
            "off",
        )

        next_mode = modes[
            (modes.index(current) + 1)
            % len(modes)
        ]

        guild_loop[guild_id] = next_mode

        save_data()

        await interaction.response.send_message(
            f"🔁 Loop: "
            f"**{loop_name(next_mode)}**",
            ephemeral=True,
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

    guild_id = player.guild.id

    cancel_idle(guild_id)

    players[guild_id] = player

    print(
        f"🎵 Playing: "
        f"{payload.track.title}"
    )

    # Send Now Playing only here.
    # This prevents duplicate messages.
    channel = getattr(
        player,
        "home",
        None,
    )

    if not channel:
        return

    try:

        await channel.send(
            embed=now_playing_embed(
                payload.track,
                player,
            ),
            view=MusicControls(),
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
        None,
    )

    print(
        f"🏁 Track ended: "
        f"{payload.track.title} "
        f"({reason})"
    )

    # Don't advance when another track replaced it.
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
            f"URI: {getattr(track, 'uri', None)}"
        )

    print(
        f"Exception: {payload.exception}"
    )

    print("========================================")

    if player:

        channel = getattr(
            player,
            "home",
            None,
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
                        COLOR_ERROR,
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
    after,
):

    if member.bot:
        return

    # Only inspect players Furious actually manages.
    for guild_id, player in list(players.items()):

        if guild_247.get(
            guild_id,
            False,
        ):
            continue

        if not is_valid_player(
            player,
            player.guild,
        ):
            continue

        channel = player.channel

        if not channel:
            continue

        humans = [
            member
            for member in channel.members
            if not member.bot
        ]

        # Nobody remains in VC.
        if not humans:

            print(
                f"👋 Empty VC: "
                f"{player.guild.name}"
            )

            await remove_player(
                guild_id
            )


# ============================================================
# PLAY
# ============================================================

@bot.command()
async def play(
    ctx,
    *,
    query: str,
):

    if ctx.guild is None:
        return

    guild_id = ctx.guild.id

    lock = get_lock(guild_id)

    async with lock:

        player = await get_player(ctx)

        if not player:
            return

        cancel_idle(guild_id)

        print()
        print("========================================")
        print(f"🔎 Input: {query}")
        print("========================================")

        track = await search_track(query)

        if not track:

            await ctx.send(
                embed=make_embed(
                    f"{ERROR} No Results",
                    (
                        f"No YouTube results found "
                        f"for `{query}`."
                    ),
                    COLOR_ERROR,
                )
            )

            return

        print(
            f"🎵 Found: {track.title}"
        )

        print(
            f"🔗 URI: "
            f"{getattr(track, 'uri', None)}"
        )

        # ----------------------------------------------------
        # ALREADY PLAYING
        # ----------------------------------------------------

        if player.current:

            try:

                player.queue.put(track)

                position = len(player.queue)

            except Exception as error:

                print(
                    f"❌ Queue error: "
                    f"{type(error).__name__}: {error}"
                )

                traceback.print_exc()

                await ctx.send(
                    embed=make_embed(
                        f"{ERROR} Queue Error",
                        "I couldn't add that track to the queue.",
                        COLOR_ERROR,
                    )
                )

                return

            await ctx.send(
                embed=make_embed(
                    "🎵 Added to Queue",
                    (
                        f"**{track.title}**\n"
                        f"Position: `#{position}`"
                    ),
                    COLOR_SUCCESS,
                )
            )

            return

        # ----------------------------------------------------
        # NOTHING PLAYING
        # ----------------------------------------------------

        success = await play_track(
            ctx,
            player,
            track,
        )

        if not success:

            await ctx.send(
                embed=make_embed(
                    f"{ERROR} Playback Error",
                    (
                        "I couldn't start this track. "
                        "The Lavalink player session may "
                        "have been recreated."
                    ),
                    COLOR_ERROR,
                )
            )

            return

        # Now Playing is sent by on_wavelink_track_start.


# ============================================================
# SKIP
# ============================================================

@bot.command()
async def skip(ctx):

    if ctx.guild is None:
        return

    player = players.get(
        ctx.guild.id
    )

    if not player or not is_valid_player(
        player,
        ctx.guild,
    ):

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no active player.",
                COLOR_ERROR,
            )
        )

        return

    if not player.current:

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR,
            )
        )

        return

    try:

        await player.skip()

        await ctx.send(
            embed=make_embed(
                f"{SKIP} Skipped",
                "Skipped the current track.",
                COLOR_SUCCESS,
            )
        )

    except Exception as error:

        print(
            f"❌ Skip error: "
            f"{type(error).__name__}: {error}"
        )

        traceback.print_exc()

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Skip Failed",
                f"`{type(error).__name__}: {error}`",
                COLOR_ERROR,
            )
        )


# ============================================================
# PAUSE
# ============================================================

@bot.command()
async def pause(ctx):

    if ctx.guild is None:
        return

    player = players.get(
        ctx.guild.id
    )

    if not player or not player.current:

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR,
            )
        )

        return

    try:

        if player.paused:

            await player.pause(False)

            await ctx.send(
                embed=make_embed(
                    "▶️ Resumed",
                    "Playback resumed.",
                    COLOR_SUCCESS,
                )
            )

        else:

            await player.pause(True)

            await ctx.send(
                embed=make_embed(
                    f"{PAUSE} Paused",
                    "Playback paused.",
                    COLOR_PAUSE,
                )
            )

    except Exception as error:

        traceback.print_exc()

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Pause Failed",
                f"`{type(error).__name__}: {error}`",
                COLOR_ERROR,
            )
        )


# ============================================================
# STOP
# ============================================================

@bot.command()
async def stop(ctx):

    if ctx.guild is None:
        return

    guild_id = ctx.guild.id

    player = players.get(
        guild_id
    )

    if not player:

        await ctx.send(
            embed=make_embed(
                "❌ Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR,
            )
        )

        return

    try:

        player.queue.clear()

    except Exception:

        pass

    guild_loop[guild_id] = "off"

    save_data()

    try:

        await player.stop()

    except Exception:

        traceback.print_exc()

    await ctx.send(
        embed=make_embed(
            "⏹️ Stopped",
            "Playback stopped and queue cleared.",
            COLOR_SUCCESS,
        )
    )

    schedule_idle(player)


# ============================================================
# QUEUE
# ============================================================

@bot.command()
async def queue(ctx):

    if ctx.guild is None:
        return

    player = players.get(
        ctx.guild.id
    )

    if not player:

        await ctx.send(
            embed=make_embed(
                "📋 Queue",
                "I'm not connected to a voice channel.",
                COLOR_ERROR,
            )
        )

        return

    lines = []

    if player.current:

        lines.append(
            f"▶️ **Now:** {player.current.title}"
        )

    try:

        queued_tracks = list(
            player.queue
        )

    except Exception:

        queued_tracks = []

    for index, track in enumerate(
        queued_tracks,
        start=1,
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
            COLOR_MUSIC,
        )
    )


# ============================================================
# NOW PLAYING
# ============================================================

@bot.command(
    aliases=["np"]
)
async def nowplaying(ctx):

    if ctx.guild is None:
        return

    player = players.get(
        ctx.guild.id
    )

    if not player or not player.current:

        await ctx.send(
            embed=make_embed(
                "❌ Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR,
            )
        )

        return

    await ctx.send(
        embed=now_playing_embed(
            player.current,
            player,
        ),
        view=MusicControls(),
    )


# ============================================================
# LOOP
# ============================================================

@bot.command()
async def loop(
    ctx,
    mode: Optional[str] = None,
):

    if ctx.guild is None:
        return

    guild_id = ctx.guild.id

    modes = [
        "off",
        "track",
        "queue",
    ]

    current = guild_loop.get(
        guild_id,
        "off",
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
                    COLOR_ERROR,
                )
            )

            return

        current = mode

    else:

        current = modes[
            (modes.index(current) + 1)
            % len(modes)
        ]

    guild_loop[guild_id] = current

    save_data()

    await ctx.send(
        embed=make_embed(
            "🔁 Loop",
            f"Loop mode: **{loop_name(current)}**",
            COLOR_SUCCESS,
        )
    )


# ============================================================
# 24/7
# ============================================================

@bot.command(name="247")
async def twenty_four_seven(ctx):

    if ctx.guild is None:
        return

    guild_id = ctx.guild.id

    current = guild_247.get(
        guild_id,
        False,
    )

    guild_247[guild_id] = not current

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
            COLOR_SUCCESS,
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
    new_prefix: Optional[str] = None,
):

    if not new_prefix:

        current = guild_prefix.get(
            ctx.guild.id,
            DEFAULT_PREFIX,
        )

        await ctx.send(
            embed=make_embed(
                "⚙️ Prefix",
                f"Current prefix: `{current}`",
                COLOR_MAIN,
            )
        )

        return

    if len(new_prefix) > 5:

        await ctx.send(
            embed=make_embed(
                "❌ Invalid Prefix",
                "Prefix must be 5 characters or fewer.",
                COLOR_ERROR,
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
            COLOR_SUCCESS,
        )
    )


@prefix.error
async def prefix_error(
    ctx,
    error,
):

    if isinstance(
        error,
        commands.MissingPermissions,
    ):

        await ctx.send(
            embed=make_embed(
                "❌ Permission Required",
                "You need **Manage Server** permission.",
                COLOR_ERROR,
            )
        )


# ============================================================
# HELP
# ============================================================

@bot.command()
async def help(ctx):

    prefix_value = guild_prefix.get(
        ctx.guild.id,
        DEFAULT_PREFIX,
    )

    description = (
        "**🎵 Music**\n"
        f"`{prefix_value}play <song/url>`\n"
        f"`{prefix_value}skip`\n"
        f"`{prefix_value}pause`\n"
        f"`{prefix_value}stop`\n"
        f"`{prefix_value}queue`\n"
        f"`{prefix_value}nowplaying`\n"
        f"`{prefix_value}loop`\n\n"

        "**⚙️ Settings**\n"
        f"`{prefix_value}247`\n"
        f"`{prefix_value}prefix <new prefix>`"
    )

    await ctx.send(
        embed=make_embed(
            "🔥 Furious Help",
            description,
            COLOR_MAIN,
        )
    )


# ============================================================
# COMMAND ERROR
# ============================================================

@bot.event
async def on_command_error(
    ctx,
    error,
):

    if isinstance(
        error,
        commands.CommandNotFound,
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument,
    ):

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Missing Argument",
                "You didn't provide all required arguments.",
                COLOR_ERROR,
            )
        )

        return

    if isinstance(
        error,
        commands.NoPrivateMessage,
    ):
        return

    if isinstance(
        error,
        commands.MissingPermissions,
    ):

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Permission Required",
                "You don't have permission to use this command.",
                COLOR_ERROR,
            )
        )

        return

    print()
    print("========================================")
    print("❌ COMMAND ERROR")
    print("========================================")

    traceback.print_exception(
        type(error),
        error,
        error.__traceback__,
    )

    print("========================================")


# ============================================================
# SHUTDOWN CLEANUP
# ============================================================

async def cleanup_players():

    print("🧹 Cleaning up players...")

    for guild_id, player in list(
        players.items()
    ):

        try:

            await player.disconnect()

        except Exception:

            pass

    players.clear()


# ============================================================
# START
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
