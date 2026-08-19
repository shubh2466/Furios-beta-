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
    "furiouslavalink-production.up.railway.app"
)
LAVALINK_PORT = os.getenv("LAVALINK_PORT", "443")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

LAVALINK_URI = os.getenv("LAVALINK_URI")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not LAVALINK_PASSWORD:
    raise RuntimeError("LAVALINK_PASSWORD is missing.")

if not LAVALINK_URI:
    LAVALINK_URI = f"https://{LAVALINK_HOST}:{LAVALINK_PORT}"


DEFAULT_PREFIX = "!"
IDLE_TIMEOUT = 300
DATA_FILE = "guild_data.json"


# ============================================================
# STORAGE
# ============================================================

guild_prefix: dict[int, str] = {}
guild_loop: dict[int, str] = {}
guild_247: dict[int, bool] = {}

idle_tasks: dict[int, asyncio.Task] = {}
voice_locks: dict[int, asyncio.Lock] = {}


# ============================================================
# DATA
# ============================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        guild_prefix.update({int(k): v for k, v in data.get("prefix", {}).items()})
        guild_loop.update({int(k): v for k, v in data.get("loop", {}).items()})
        guild_247.update({int(k): v for k, v in data.get("247", {}).items()})

        print("Guild settings loaded.")
    except Exception:
        print("Failed to load guild_data.json")
        traceback.print_exc()


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "prefix": {str(k): v for k, v in guild_prefix.items()},
                    "loop": {str(k): v for k, v in guild_loop.items()},
                    "247": {str(k): v for k, v in guild_247.items()},
                },
                file,
                indent=4,
            )
    except Exception:
        print("Failed to save guild_data.json")
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

def make_embed(title: str, description: str = "", color: discord.Color = COLOR_MAIN):
    return discord.Embed(title=title, description=description, color=color)


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
# HELPERS
# ============================================================

def get_voice_lock(guild_id: int):
    lock = voice_locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        voice_locks[guild_id] = lock
    return lock


def cancel_idle(guild_id: int):
    task = idle_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()


def artwork(track):
    return getattr(track, "artwork", None)


def loop_name(mode: str):
    return {"off": "Off", "track": "Track", "queue": "Queue"}.get(mode, "Off")


# ============================================================
# BOT
# ============================================================

class Furious(commands.Bot):

    async def setup_hook(self):
        print()
        print("=" * 60)
        print("CONNECTING TO LAVALINK")
        print("=" * 60)
        print(f"URI: {LAVALINK_URI}")
        print("Node: Furious-Lavalink")
        print("=" * 60)

        node = wavelink.Node(
            identifier="Furious-Lavalink",
            uri=LAVALINK_URI,
            password=LAVALINK_PASSWORD,
        )

        try:
            await wavelink.Pool.connect(nodes=[node], client=self)
            print("Lavalink connection established.")
        except Exception as error:
            print("Lavalink connection failed.")
            print(f"{type(error).__name__}: {error}")
            traceback.print_exc()
            raise

        self.add_view(MusicControls())

        print("=" * 60)
        print()


bot = Furious(
    command_prefix=lambda bot, message: (
        guild_prefix.get(message.guild.id, DEFAULT_PREFIX)
        if message.guild
        else DEFAULT_PREFIX
    ),
    intents=intents,
    help_command=None,
)


# ============================================================
# YOUTUBE SEARCH
# ============================================================

async def search_youtube(query: str):
    query = query.strip()
    if not query:
        return None

    print()
    print("=" * 60)
    print("SEARCH")
    print("=" * 60)
    print(f"Input: {query}")

    try:
        if query.startswith(("http://", "https://")):
            print("Searching direct URL")
            results = await wavelink.Playable.search(query)
        else:
            print("Searching YouTube")
            results = await wavelink.Playable.search(
                query, source=wavelink.TrackSource.YouTube
            )
    except Exception as error:
        print("Lavalink search failed.")
        print(f"{type(error).__name__}: {error}")
        traceback.print_exc()
        return None

    if not results:
        print("No results.")
        return None

    if isinstance(results, wavelink.Playlist):
        print(f"Playlist found: {len(results.tracks)} tracks")
        if not results.tracks:
            return None
        return results.tracks[0]

    track = results[0]
    print(f"Found: {track.title}")
    print(f"URI: {getattr(track, 'uri', None)}")

    return track


# ============================================================
# VOICE CONNECTION
# ============================================================

async def connect_to_voice(ctx):
    if not ctx.author.voice:
        await ctx.send(
            embed=make_embed(
                f"{ERROR} Voice Channel Required",
                "Join a voice channel first.",
                COLOR_ERROR,
            )
        )
        return None

    channel = ctx.author.voice.channel
    guild = ctx.guild

    lock = get_voice_lock(guild.id)

    async with lock:
        print()
        print("=" * 60)
        print("VOICE CONNECTION")
        print("=" * 60)
        print(f"Guild:   {guild.name}")
        print(f"Guild ID: {guild.id}")
        print(f"Channel: {channel.name}")
        print(f"Channel ID: {channel.id}")
        print("=" * 60)

        player = guild.voice_client

        # ----------------------------------------------------
        # EXISTING PLAYER
        # ----------------------------------------------------

        if player:
            print(f"Existing voice client: {type(player).__name__}")
            try:
                if player.channel:
                    print(f"Current channel: {player.channel.name}")

                    if player.channel.id != channel.id:
                        print("Moving player...")
                        await player.move_to(channel)

                    player.home = ctx.channel
                    cancel_idle(guild.id)

                    print("Existing player reused.")
                    return player
            except Exception:
                print("Existing player is invalid.")
                traceback.print_exc()

        # ----------------------------------------------------
        # STALE PLAYER
        # ----------------------------------------------------

        if player:
            print("Cleaning stale player...")
            try:
                await player.disconnect(force=True)
            except Exception:
                pass
            await asyncio.sleep(1)

        # ----------------------------------------------------
        # CREATE NEW PLAYER
        # ----------------------------------------------------

        print("Creating new Wavelink Player...")

        try:
            player = await channel.connect(
                cls=wavelink.Player,
                timeout=60.0,
                reconnect=True,
                self_deaf=True,
            )
        except asyncio.TimeoutError:
            print("Voice connection timed out.")
            await ctx.send(
                embed=make_embed(
                    f"{ERROR} Voice Timeout",
                    "Discord voice connection timed out.",
                    COLOR_ERROR,
                )
            )
            return None
        except wavelink.ChannelTimeoutException:
            print("Wavelink ChannelTimeoutException.")
            await ctx.send(
                embed=make_embed(
                    f"{ERROR} Voice Connection Failed",
                    (
                        "Discord voice negotiation timed out.\n\n"
                        "Lavalink is reachable, but Discord voice "
                        "connection did not complete."
                    ),
                    COLOR_ERROR,
                )
            )
            return None
        except Exception as error:
            print("Voice connection failed.")
            print(f"{type(error).__name__}: {error}")
            traceback.print_exc()
            await ctx.send(
                embed=make_embed(
                    f"{ERROR} Voice Connection Failed",
                    f"`{type(error).__name__}: {error}`",
                    COLOR_ERROR,
                )
            )
            return None

        if not player:
            print("Wavelink returned no player.")
            return None

        player.home = ctx.channel
        cancel_idle(guild.id)

        print()
        print("WAVELINK PLAYER CREATED")
        print(f"Player: {player}")
        print(f"Channel: {channel.name}")
        print("=" * 60)

        return player


# ============================================================
# IDLE
# ============================================================

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

        try:
            if (
                not current.playing
                and not current.current
                and not current.queue
            ):
                print(f"Idle disconnect: {player.guild.name}")
                await current.disconnect(force=True)
        except Exception:
            traceback.print_exc()

    idle_tasks[guild_id] = asyncio.create_task(disconnect_later())


# ============================================================
# NOW PLAYING
# ============================================================

def now_playing_embed(track, player):
    artist = getattr(track, "author", "Unknown Artist")
    position = getattr(player, "position", 0)
    length = getattr(track, "length", None)
    mode = guild_loop.get(player.guild.id, "off")

    description = (
        f"## {track.title}\n\n"
        f"Artist: `{artist}`\n"
        f"Loop: `{loop_name(mode)}`\n\n"
        f"`{format_time(position)}` / `{format_time(length)}`"
    )

    embed = discord.Embed(
        title=f"{SPOTIFY} Now Playing",
        description=description,
        color=COLOR_MUSIC,
    )

    image = artwork(track)
    if image:
        embed.set_image(url=image)

    embed.set_footer(text="Furious Music - Playback Controls")

    return embed


# ============================================================
# PLAY NEXT
# ============================================================

async def play_next(player):
    if not player or not player.guild:
        return

    guild_id = player.guild.id
    mode = guild_loop.get(guild_id, "off")
    current = player.current

    # --------------------------------------------------------
    # TRACK LOOP
    # --------------------------------------------------------

    if mode == "track" and current:
        try:
            print(f"Track loop: {current.title}")
            await player.play(current, replace=True)
            return
        except Exception:
            print("Track loop failed.")
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
            print(f"Next track: {next_track.title}")
            await player.play(next_track, replace=True)
            return
        except Exception:
            print("Failed to play next track.")
            traceback.print_exc()

    schedule_idle(player)


# ============================================================
# MUSIC BUTTONS
# ============================================================

class MusicControls(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    async def get_player(self, interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "This button can only be used in a server.", ephemeral=True
            )
            return None

        player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "I'm not connected to a voice channel.", ephemeral=True
            )
            return None

        if not interaction.user.voice:
            await interaction.response.send_message(
                "Join my voice channel first.", ephemeral=True
            )
            return None

        if interaction.user.voice.channel != player.channel:
            await interaction.response.send_message(
                "You must be in my voice channel.", ephemeral=True
            )
            return None

        return player

    # --------------------------------------------------------
    # PAUSE
    # --------------------------------------------------------

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="776450pause", id=1537702507210612786),
        style=discord.ButtonStyle.secondary,
        custom_id="furious:pause",
    )
    async def pause_button(self, interaction, button):
        player = await self.get_player(interaction)
        if not player:
            return

        if not player.current:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return

        if player.paused:
            await player.pause(False)
            await interaction.response.send_message("Resumed.", ephemeral=True)
        else:
            await player.pause(True)
            await interaction.response.send_message(
                f"{PAUSE} Paused.", ephemeral=True
            )

    # --------------------------------------------------------
    # SKIP
    # --------------------------------------------------------

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="22838skip", id=1537702524218511452),
        style=discord.ButtonStyle.secondary,
        custom_id="furious:skip",
    )
    async def skip_button(self, interaction, button):
        player = await self.get_player(interaction)
        if not player:
            return

        if not player.current:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return

        await player.skip()
        await interaction.response.send_message(f"{SKIP} Skipped.", ephemeral=True)

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    @discord.ui.button(
        emoji="\u23f9\ufe0f",
        style=discord.ButtonStyle.danger,
        custom_id="furious:stop",
    )
    async def stop_button(self, interaction, button):
        player = await self.get_player(interaction)
        if not player:
            return

        player.queue.clear()
        guild_loop[interaction.guild.id] = "off"
        save_data()

        await player.stop()
        schedule_idle(player)

        await interaction.response.send_message(
            "Stopped and cleared the queue.", ephemeral=True
        )

    # --------------------------------------------------------
    # LOOP
    # --------------------------------------------------------

    @discord.ui.button(
        emoji="\U0001f501",
        style=discord.ButtonStyle.secondary,
        custom_id="furious:loop",
    )
    async def loop_button(self, interaction, button):
        player = await self.get_player(interaction)
        if not player:
            return

        modes = ["off", "track", "queue"]
        current = guild_loop.get(interaction.guild.id, "off")
        next_mode = modes[(modes.index(current) + 1) % len(modes)]
        guild_loop[interaction.guild.id] = next_mode
        save_data()

        await interaction.response.send_message(
            f"Loop: **{loop_name(next_mode)}**", ephemeral=True
        )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print()
    print("=" * 60)
    print("FURIOUS ONLINE")
    print("=" * 60)
    print(f"User:       {bot.user}")
    print(f"Servers:    {len(bot.guilds)}")
    print(f"discord.py: {discord.__version__}")
    print(f"Wavelink:   {wavelink.__version__}")
    print(f"Lavalink:   {LAVALINK_URI}")
    print("=" * 60)
    print()


# ============================================================
# LAVALINK NODE READY
# ============================================================

@bot.event
async def on_wavelink_node_ready(payload):
    print()
    print("=" * 60)
    print("LAVALINK NODE READY")
    print("=" * 60)
    print(f"Node: {payload.node.identifier}")
    print("=" * 60)


# ============================================================
# TRACK START
# ============================================================

@bot.event
async def on_wavelink_track_start(payload):
    player = payload.player
    track = payload.track

    if not player:
        return

    cancel_idle(player.guild.id)

    print()
    print("=" * 60)
    print("TRACK STARTED")
    print("=" * 60)
    print(f"Title: {track.title}")
    print(f"URI:   {getattr(track, 'uri', None)}")
    print("=" * 60)

    channel = getattr(player, "home", None)

    if channel:
        try:
            await channel.send(
                embed=now_playing_embed(track, player), view=MusicControls()
            )
        except Exception:
            traceback.print_exc()


# ============================================================
# TRACK END
# ============================================================

@bot.event
async def on_wavelink_track_end(payload):
    player = payload.player
    track = payload.track

    if not player:
        return

    reason = getattr(payload, "reason", None)

    print(
        f"Track ended: "
        f"{track.title if track else 'Unknown'} "
        f"reason={reason}"
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
    print("=" * 60)
    print("TRACK EXCEPTION")
    print("=" * 60)
    print(f"Track: {track.title if track else 'Unknown'}")
    print(f"URI: {getattr(track, 'uri', None)}")
    print(f"Exception: {payload.exception}")
    print("=" * 60)

    if not player:
        return

    channel = getattr(player, "home", None)

    if channel:
        try:
            await channel.send(
                embed=make_embed(
                    f"{ERROR} Track Error",
                    (
                        f"**{track.title if track else 'Track'}** "
                        "couldn't be played."
                    ),
                    COLOR_ERROR,
                )
            )
        except Exception:
            pass

    await play_next(player)


# ============================================================
# TRACK STUCK
# ============================================================

@bot.event
async def on_wavelink_track_stuck(payload):
    print(
        f"Track stuck: "
        f"{payload.track.title if payload.track else 'Unknown'}"
    )

    if payload.player:
        await play_next(payload.player)


# ============================================================
# VOICE STATE
# ============================================================

@bot.event
async def on_voice_state_update(member, before, after):
    # IMPORTANT:
    #
    # Do not disconnect/reconnect Lavalink here.
    #
    # Discord generates multiple voice-state events
    # during connection negotiation.
    #
    # The previous code could create:
    #
    # PATCH voice
    # DELETE player
    # PATCH voice
    # DELETE player
    #
    # We intentionally leave this event alone.
    return


# ============================================================
# PLAY
# ============================================================

@bot.command()
async def play(ctx, *, query: str):
    player = await connect_to_voice(ctx)
    if not player:
        return

    cancel_idle(ctx.guild.id)

    print()
    print("=" * 60)
    print("PLAY COMMAND")
    print("=" * 60)
    print(f"Input: {query}")
    print("=" * 60)

    track = await search_youtube(query)

    if not track:
        await ctx.send(
            embed=make_embed(
                f"{ERROR} No Results",
                f"No results found for `{query}`.",
                COLOR_ERROR,
            )
        )
        return

    print(f"Track: {track.title}")
    print(f"URI:   {getattr(track, 'uri', None)}")

    # --------------------------------------------------------
    # QUEUE
    # --------------------------------------------------------

    if player.current:
        player.queue.put(track)
        position = len(player.queue)

        print(f"Added to queue at #{position}")

        await ctx.send(
            embed=make_embed(
                "Added to Queue",
                f"**{track.title}**\nPosition: `#{position}`",
                COLOR_SUCCESS,
            )
        )
        return

    # --------------------------------------------------------
    # PLAY
    # --------------------------------------------------------

    try:
        print()
        print("SENDING TRACK TO LAVALINK")
        print("=" * 60)

        await player.play(track, replace=True)

        print("player.play() completed.")
        print("=" * 60)

        await ctx.send(
            embed=make_embed(
                f"{TICK} Loading",
                f"**{track.title}**\nLavalink is starting playback...",
                COLOR_SUCCESS,
            ),
            view=MusicControls(),
        )
    except Exception as error:
        print()
        print("=" * 60)
        print("PLAY ERROR")
        print("=" * 60)
        print(f"Type: {type(error).__name__}")
        print(f"Error: {error}")
        traceback.print_exc()
        print("=" * 60)

        await ctx.send(
            embed=make_embed(
                f"{ERROR} Playback Error",
                f"`{type(error).__name__}: {error}`",
                COLOR_ERROR,
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
                "Nothing Playing", "There is no track playing.", COLOR_ERROR
            )
        )
        return

    await player.skip()

    await ctx.send(
        embed=make_embed(
            f"{SKIP} Skipped", "Skipped the current track.", COLOR_SUCCESS
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
                "Nothing Playing", "There is no track playing.", COLOR_ERROR
            )
        )
        return

    if player.paused:
        await player.pause(False)
        await ctx.send(
            embed=make_embed("Resumed", "Playback resumed.", COLOR_SUCCESS)
        )
    else:
        await player.pause(True)
        await ctx.send(
            embed=make_embed(f"{PAUSE} Paused", "Playback paused.", COLOR_PAUSE)
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
                "Not Connected", "I'm not in a voice channel.", COLOR_ERROR
            )
        )
        return

    player.queue.clear()
    guild_loop[ctx.guild.id] = "off"
    save_data()

    await player.stop()
    schedule_idle(player)

    await ctx.send(
        embed=make_embed(
            "Stopped", "Playback stopped and queue cleared.", COLOR_SUCCESS
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
                "Queue", "I'm not connected to a voice channel.", COLOR_ERROR
            )
        )
        return

    lines = []

    if player.current:
        lines.append(f"Now: {player.current.title}")

    if player.queue:
        for index, track in enumerate(list(player.queue), start=1):
            lines.append(f"`{index}.` {track.title}")

    if not lines:
        lines.append("The queue is empty.")

    await ctx.send(
        embed=make_embed("Music Queue", "\n".join(lines), COLOR_MUSIC)
    )


# ============================================================
# NOW PLAYING
# ============================================================

@bot.command(aliases=["np"])
async def nowplaying(ctx):
    player = ctx.guild.voice_client

    if not player or not player.current:
        await ctx.send(
            embed=make_embed(
                "Nothing Playing", "There is no track playing.", COLOR_ERROR
            )
        )
        return

    await ctx.send(
        embed=now_playing_embed(player.current, player), view=MusicControls()
    )


# ============================================================
# LOOP
# ============================================================

@bot.command()
async def loop(ctx, mode: Optional[str] = None):
    modes = ["off", "track", "queue"]
    current = guild_loop.get(ctx.guild.id, "off")

    if mode:
        mode = mode.lower()

        if mode not in modes:
            await ctx.send(
                embed=make_embed(
                    "Invalid Loop",
                    "Use:\n`!loop off`\n`!loop track`\n`!loop queue`",
                    COLOR_ERROR,
                )
            )
            return

        current = mode
    else:
        current = modes[(modes.index(current) + 1) % len(modes)]

    guild_loop[ctx.guild.id] = current
    save_data()

    await ctx.send(
        embed=make_embed(
            "Loop", f"Loop mode: **{loop_name(current)}**", COLOR_SUCCESS
        )
    )


# ============================================================
# 24/7
# ============================================================

@bot.command(name="247")
async def twenty_four_seven(ctx):
    guild_id = ctx.guild.id
    current = guild_247.get(guild_id, False)
    guild_247[guild_id] = not current
    save_data()

    status = "Enabled" if not current else "Disabled"

    await ctx.send(
        embed=make_embed("24/7 Mode", f"24/7 mode: **{status}**", COLOR_SUCCESS)
    )


# ============================================================
# PREFIX
# ============================================================

@bot.command()
@commands.has_guild_permissions(manage_guild=True)
async def prefix(ctx, new_prefix: Optional[str] = None):
    if not new_prefix:
        current = guild_prefix.get(ctx.guild.id, DEFAULT_PREFIX)
        await ctx.send(
            embed=make_embed("Prefix", f"Current prefix: `{current}`", COLOR_MAIN)
        )
        return

    if len(new_prefix) > 5:
        await ctx.send(
            embed=make_embed(
                "Invalid Prefix",
                "Prefix must be 5 characters or fewer.",
                COLOR_ERROR,
            )
        )
        return

    guild_prefix[ctx.guild.id] = new_prefix
    save_data()

    await ctx.send(
        embed=make_embed(
            "Prefix Updated", f"New prefix: `{new_prefix}`", COLOR_SUCCESS
        )
    )


@prefix.error
async def prefix_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            embed=make_embed(
                "Permission Required",
                "You need **Manage Server** permission.",
                COLOR_ERROR,
            )
        )


# ============================================================
# HELP
# ============================================================

@bot.command()
async def help(ctx):
    prefix_value = guild_prefix.get(ctx.guild.id, DEFAULT_PREFIX)

    description = (
        f"**Music**\n"
        f"`{prefix_value}play <song/url>`\n"
        f"`{prefix_value}skip`\n"
        f"`{prefix_value}pause`\n"
        f"`{prefix_value}stop`\n"
        f"`{prefix_value}queue`\n"
        f"`{prefix_value}nowplaying`\n"
        f"`{prefix_value}loop`\n\n"
        f"**Settings**\n"
        f"`{prefix_value}247`\n"
        f"`{prefix_value}prefix <new prefix>`"
    )

    await ctx.send(embed=make_embed("Furious Help", description, COLOR_MAIN))


# ============================================================
# COMMAND ERRORS
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            embed=make_embed(
                f"{ERROR} Missing Argument",
                "You didn't provide all required arguments.",
                COLOR_ERROR,
            )
        )
        return

    print()
    print("=" * 60)
    print("COMMAND ERROR")
    print("=" * 60)
    print(f"{type(error).__name__}: {error}")
    traceback.print_exc()
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    print("Starting Furious...")

    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("Bot stopped.")
    except Exception:
        print("Bot crashed.")
        traceback.print_exc()
