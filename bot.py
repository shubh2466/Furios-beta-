import asyncio
import os
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
    "lavalink-2026-production-8c44.up.railway.app"
)

LAVALINK_PORT = int(
    os.getenv("LAVALINK_PORT", "443")
)

LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing from .env"
    )

if not LAVALINK_PASSWORD:
    raise RuntimeError(
        "LAVALINK_PASSWORD is missing from .env"
    )


# ============================================================
# CONFIG
# ============================================================

DEFAULT_PREFIX = "!"
IDLE_TIMEOUT = 300

# Per-guild settings
guild_prefix = {}
guild_loop = {}
guild_247 = {}
idle_tasks = {}


# ============================================================
# DISCORD INTENTS
# ============================================================

intents = discord.Intents.default()

intents.message_content = True
intents.voice_states = True


# ============================================================
# BOT CLASS
# ============================================================

class Furious(commands.Bot):

    async def setup_hook(self):

        print()
        print("========================================")
        print("🔌 Connecting to Lavalink...")
        print("========================================")

        # Railway HTTPS endpoint
        uri = f"https://{LAVALINK_HOST}:{LAVALINK_PORT}"

        node = wavelink.Node(
            uri=uri,
            password=LAVALINK_PASSWORD,
            identifier="Furious-Lavalink"
        )

        try:

            await wavelink.Pool.connect(
                nodes=[node],
                client=self
            )

            print("✅ Lavalink connection established.")

        except Exception as e:

            print("❌ Lavalink connection failed.")
            print(f"   {type(e).__name__}: {e}")


bot = Furious(
    command_prefix=lambda bot, message: guild_prefix.get(
        message.guild.id,
        DEFAULT_PREFIX
    ) if message.guild else DEFAULT_PREFIX,
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
# CUSTOM EMOJIS
# ============================================================

SPOTIFY = "<:214004pixelspotify:1537699774596386926>"
SKIP = "<:22838skip:1537702524218511452>"
PAUSE = "<:776450pause:1537702507210612786>"
TICK = "<:763305tick:1537700918722691133>"
ERROR = "<a:880726error:1537700477955735622>"


# ============================================================
# EMBED HELPER
# ============================================================

def embed(
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

    if not ms:
        return "00:00"

    seconds = int(ms / 1000)

    minutes, seconds = divmod(seconds, 60)

    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    return f"{minutes:02}:{seconds:02}"


# ============================================================
# ARTWORK
# ============================================================

def artwork(track):

    return getattr(
        track,
        "artwork",
        None
    )


# ============================================================
# LOOP
# ============================================================

def loop_name(mode):

    names = {
        "off": "Off",
        "track": "🔂 Track",
        "queue": "🔁 Queue"
    }

    return names.get(
        mode,
        "Off"
    )


# ============================================================
# PLAYER
# ============================================================

async def get_player(ctx):

    player = ctx.guild.voice_client

    # Already connected
    if player:

        player.home = ctx.channel

        return player

    # User must be in voice
    if not ctx.author.voice:

        await ctx.send(
            embed(
                f"{ERROR} Voice Channel Required",
                "Join a voice channel first.",
                COLOR_ERROR
            )
        )

        return None

    channel = ctx.author.voice.channel

    try:

        player = await channel.connect(
            cls=wavelink.Player
        )

        player.home = ctx.channel

        return player

    except Exception as e:

        print(
            f"❌ Voice connection error: "
            f"{type(e).__name__}: {e}"
        )

        await ctx.send(
            embed(
                f"{ERROR} Voice Connection Failed",
                f"`{type(e).__name__}`",
                COLOR_ERROR
            )
        )

        return None


# ============================================================
# IDLE DISCONNECT
# ============================================================

def cancel_idle(guild_id):

    task = idle_tasks.get(guild_id)

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

        current = player.guild.voice_client

        if not current:
            return

        if guild_247.get(guild_id, False):
            return

        if (
            not current.playing
            and not current.queue
        ):

            try:

                await current.disconnect()

                print(
                    f"👋 Auto-disconnected from "
                    f"{player.guild.name}"
                )

            except Exception:
                pass

    idle_tasks[guild_id] = asyncio.create_task(
        disconnect_later()
    )


# ============================================================
# QUEUE ADVANCEMENT
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

    # ----------------------------------------
    # TRACK LOOP
    # ----------------------------------------

    if (
        mode == "track"
        and current
    ):

        try:

            await player.play(current)

            return

        except Exception as e:

            print(
                f"❌ Track loop error: {e}"
            )


    # ----------------------------------------
    # QUEUE LOOP
    # ----------------------------------------

    if (
        mode == "queue"
        and current
    ):

        player.queue.put(
            current
        )


    # ----------------------------------------
    # NEXT TRACK
    # ----------------------------------------

    if player.queue:

        try:

            next_track = player.queue.get()

            await player.play(
                next_track
            )

            return

        except Exception as e:

            print(
                f"❌ Queue playback error: {e}"
            )

            await play_next(player)

            return

    # Nothing left
    schedule_idle(player)


# ============================================================
# NOW PLAYING EMBED
# ============================================================

def now_playing_embed(
    track,
    player
):

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
        f"`{format_time(position)}` "
        f"/ `{format_time(length)}`"
    )

    e = discord.Embed(
        title=f"{SPOTIFY} Now Playing",
        description=description,
        color=COLOR_MUSIC
    )

    image = artwork(track)

    if image:

        e.set_image(
            url=image
        )

    e.set_footer(
        text="Furious Music • Playback Controls"
    )

    return e


# ============================================================
# MUSIC BUTTONS
# ============================================================

class MusicControls(discord.ui.View):

    def __init__(self, guild_id):

        super().__init__(
            timeout=None
        )

        self.guild_id = guild_id


    async def get_player(
        self,
        interaction
    ):

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
    # PAUSE / RESUME
    # --------------------------------------------------------

    @discord.ui.button(
        emoji=discord.PartialEmoji(
            name="776450pause",
            id=1537702507210612786
        ),
        style=discord.ButtonStyle.secondary
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

            await player.pause(
                False
            )

            button.emoji = discord.PartialEmoji(
                name="776450pause",
                id=1537702507210612786
            )

            await interaction.response.send_message(
                "▶️ Resumed.",
                ephemeral=True
            )

        else:

            await player.pause(
                True
            )

            button.emoji = "▶️"

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
        style=discord.ButtonStyle.secondary
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
        style=discord.ButtonStyle.danger
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
            self.guild_id
        ] = "off"

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
        style=discord.ButtonStyle.secondary
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
            self.guild_id,
            "off"
        )

        next_mode = modes[
            (
                modes.index(current) + 1
            )
            % len(modes)
        ]

        guild_loop[
            self.guild_id
        ] = next_mode

        await interaction.response.send_message(
            f"🔁 Loop: **{loop_name(next_mode)}**",
            ephemeral=True
        )


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():

    print()
    print("========================================")
    print(f"🤖 Logged in as {bot.user}")
    print(f"🌐 Servers: {len(bot.guilds)}")
    print("========================================")
    print()


@bot.event
async def on_wavelink_node_ready(payload):

    print(
        f"{TICK} Lavalink node ready: "
        f"{payload.node.identifier}"
    )


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

    # Don't advance when manually replaced
    if str(reason).lower() == "replaced":
        return

    await play_next(
        player
    )


@bot.event
async def on_wavelink_track_exception(payload):

    player = payload.player
    track = payload.track

    print()
    print("❌ TRACK EXCEPTION")
    print(
        f"Track: "
        f"{track.title if track else 'Unknown'}"
    )
    print(
        f"Exception: "
        f"{payload.exception}"
    )
    print()

    if player:

        channel = getattr(
            player,
            "home",
            None
        )

        if channel:

            try:

                await channel.send(
                    embed=embed(
                        f"{ERROR} Track Error",
                        (
                            f"**{track.title if track else 'Track'}** "
                            "couldn't be played and was skipped."
                        ),
                        COLOR_ERROR
                    )
                )

            except discord.HTTPException:
                pass

        await play_next(
            player
        )


@bot.event
async def on_wavelink_track_stuck(payload):

    player = payload.player
    track = payload.track

    print(
        f"⚠️ Track stuck: "
        f"{track.title if track else 'Unknown'}"
    )

    if player:

        await play_next(
            player
        )


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

    for player in list(
        bot.voice_clients
    ):

        if guild_247.get(
            player.guild.id,
            False
        ):
            continue

        channel = player.channel

        if not channel:
            continue

        humans = [
            m for m in channel.members
            if not m.bot
        ]

        if not humans:

            try:

                await player.disconnect()

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

    player = await get_player(
        ctx
    )

    if not player:
        return

    cancel_idle(
        ctx.guild.id
    )

    try:

        print(
            f"🔎 Searching: {query}"
        )

        tracks = await wavelink.Playable.search(
            query
        )

        if not tracks:

            await ctx.send(
                embed=embed(
                    f"{ERROR} No Results",
                    f"No results found for `{query}`.",
                    COLOR_ERROR
                )
            )

            return

        # Wavelink can return a playlist
        if isinstance(
            tracks,
            wavelink.Search
        ):

            track = tracks[0]

        else:

            track = tracks[0]


        # ----------------------------------------------------
        # ALREADY PLAYING
        # ----------------------------------------------------

        if player.current:

            player.queue.put(
                track
            )

            position = len(
                player.queue
            )

            e = embed(
                "➕ Added to Queue",
                (
                    f"## {track.title}\n\n"
                    f"🎤 **Artist:** "
                    f"`{getattr(track, 'author', 'Unknown')}`\n"
                    f"📍 **Position:** `{position}`"
                ),
                COLOR_WARNING
            )

            image = artwork(
                track
            )

            if image:

                e.set_thumbnail(
                    url=image
                )

            await ctx.send(
                embed=e
            )

            return


        # ----------------------------------------------------
        # PLAY
        # ----------------------------------------------------

        await player.play(
            track
        )

        await ctx.send(
            embed=now_playing_embed(
                track,
                player
            ),
            view=MusicControls(
                ctx.guild.id
            )
        )

        print(
            f"▶️ Started: {track.title}"
        )

    except Exception as e:

        print()
        print("❌ PLAY ERROR")
        print(
            f"{type(e).__name__}: {e}"
        )
        print()

        await ctx.send(
            embed=embed(
                f"{ERROR} Playback Error",
                (
                    f"Something went wrong:\n"
                    f"`{type(e).__name__}: {e}`"
                ),
                COLOR_ERROR
            )
        )


# ============================================================
# JOIN
# ============================================================

@bot.command()
async def join(ctx):

    if not ctx.author.voice:

        await ctx.send(
            embed=embed(
                f"{ERROR} Voice Required",
                "Join a voice channel first.",
                COLOR_ERROR
            )
        )

        return

    channel = ctx.author.voice.channel

    try:

        player = ctx.guild.voice_client

        if not player:

            player = await channel.connect(
                cls=wavelink.Player
            )

        elif player.channel != channel:

            await player.move_to(
                channel
            )

        player.home = ctx.channel

        await ctx.send(
            embed=embed(
                "🔊 Connected",
                f"Joined **{channel.name}**.",
                COLOR_SUCCESS
            )
        )

    except Exception as e:

        print(
            f"❌ Join error: {e}"
        )

        await ctx.send(
            embed=embed(
                f"{ERROR} Failed to Join",
                f"`{type(e).__name__}`",
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
            embed=embed(
                f"{ERROR} Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR
            )
        )

        return

    try:

        await player.skip()

        await ctx.send(
            embed=embed(
                f"{SKIP} Skipped",
                "The current track was skipped.",
                COLOR_SUCCESS
            )
        )

    except Exception as e:

        await ctx.send(
            embed=embed(
                f"{ERROR} Skip Failed",
                f"`{type(e).__name__}`",
                COLOR_ERROR
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
            embed=embed(
                f"{ERROR} Nothing Playing",
                "There is no track playing.",
                COLOR_ERROR
            )
        )

        return

    await player.pause(
        True
    )

    await ctx.send(
        embed=embed(
            f"{PAUSE} Paused",
            f"Paused **{player.current.title}**.",
            COLOR_PAUSE
        )
    )


# ============================================================
# RESUME
# ============================================================

@bot.command()
async def resume(ctx):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=embed(
                f"{ERROR} Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR
            )
        )

        return

    await player.pause(
        False
    )

    title = (
        player.current.title
        if player.current
        else "Music"
    )

    await ctx.send(
        embed=embed(
            "▶️ Resumed",
            f"Resumed **{title}**.",
            COLOR_SUCCESS
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
            embed=embed(
                f"{ERROR} Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR
            )
        )

        return

    player.queue.clear()

    guild_loop[
        ctx.guild.id
    ] = "off"

    await player.stop()

    schedule_idle(
        player
    )

    await ctx.send(
        embed=embed(
            "⏹️ Stopped",
            "Playback stopped and the queue was cleared.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# QUEUE
# ============================================================

@bot.command(
    name="queue"
)
async def queue_cmd(ctx):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=embed(
                "📭 Queue Empty",
                "I'm not connected to a voice channel.",
                COLOR_WARNING
            )
        )

        return

    tracks = list(
        player.queue
    )

    if not tracks:

        await ctx.send(
            embed=embed(
                "📭 Queue Empty",
                "There are no upcoming tracks.",
                COLOR_WARNING
            )
        )

        return

    lines = []

    for index, track in enumerate(
        tracks[:10],
        start=1
    ):

        lines.append(
            f"`{index}.` **{track.title}**"
        )

    e = embed(
        f"{SPOTIFY} Furious Queue",
        "\n".join(lines),
        COLOR_MUSIC
    )

    if len(tracks) > 10:

        e.set_footer(
            text=f"Showing 10 of {len(tracks)} tracks"
        )

    else:

        e.set_footer(
            text=f"{len(tracks)} track(s) queued"
        )

    await ctx.send(
        embed=e
    )


# ============================================================
# CLEAR
# ============================================================

@bot.command()
async def clear(ctx):

    player = ctx.guild.voice_client

    if not player or not player.queue:

        await ctx.send(
            embed=embed(
                "📭 Queue Empty",
                "There is nothing to clear.",
                COLOR_WARNING
            )
        )

        return

    player.queue.clear()

    await ctx.send(
        embed=embed(
            "🧹 Queue Cleared",
            "All upcoming tracks were removed.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# REMOVE
# ============================================================

@bot.command()
async def remove(
    ctx,
    index: int
):

    player = ctx.guild.voice_client

    if not player or not player.queue:

        await ctx.send(
            embed=embed(
                "📭 Queue Empty",
                "There is nothing to remove.",
                COLOR_WARNING
            )
        )

        return

    tracks = list(
        player.queue
    )

    if index < 1 or index > len(tracks):

        await ctx.send(
            embed=embed(
                "⚠️ Invalid Position",
                (
                    f"Choose a number from "
                    f"`1` to `{len(tracks)}`."
                ),
                COLOR_WARNING
            )
        )

        return

    removed = tracks.pop(
        index - 1
    )

    player.queue.clear()

    for track in tracks:

        player.queue.put(
            track
        )

    await ctx.send(
        embed=embed(
            "🗑️ Removed",
            f"Removed **{removed.title}**.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# SHUFFLE
# ============================================================

@bot.command()
async def shuffle(ctx):

    player = ctx.guild.voice_client

    if not player or not player.queue:

        await ctx.send(
            embed=embed(
                "📭 Queue Empty",
                "There is nothing to shuffle.",
                COLOR_WARNING
            )
        )

        return

    player.queue.shuffle()

    await ctx.send(
        embed=embed(
            "🔀 Queue Shuffled",
            "The upcoming tracks were shuffled.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# LOOP
# ============================================================

@bot.command(
    name="loop"
)
async def loop_cmd(
    ctx,
    mode: Optional[str] = None
):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=embed(
                f"{ERROR} Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR
            )
        )

        return

    if mode is None:

        current = guild_loop.get(
            ctx.guild.id,
            "off"
        )

        await ctx.send(
            embed=embed(
                "🔁 Loop Status",
                f"Current mode: **{loop_name(current)}**",
                COLOR_MAIN
            )
        )

        return

    mode = mode.lower()

    if mode not in {
        "off",
        "track",
        "queue"
    }:

        await ctx.send(
            embed=embed(
                "⚠️ Invalid Loop",
                "Use `off`, `track`, or `queue`.",
                COLOR_WARNING
            )
        )

        return

    guild_loop[
        ctx.guild.id
    ] = mode

    await ctx.send(
        embed=embed(
            "🔁 Loop Updated",
            f"Loop mode: **{loop_name(mode)}**",
            COLOR_SUCCESS
        )
    )


# ============================================================
# NOW PLAYING
# ============================================================

@bot.command()
async def nowplaying(ctx):

    player = ctx.guild.voice_client

    if not player or not player.current:

        await ctx.send(
            embed=embed(
                f"{ERROR} Nothing Playing",
                "There is currently no music playing.",
                COLOR_ERROR
            )
        )

        return

    await ctx.send(
        embed=now_playing_embed(
            player.current,
            player
        ),
        view=MusicControls(
            ctx.guild.id
        )
    )


# ============================================================
# VOLUME
# ============================================================

@bot.command()
async def volume(
    ctx,
    value: int
):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=embed(
                f"{ERROR} Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR
            )
        )

        return

    if not 0 <= value <= 100:

        await ctx.send(
            embed=embed(
                "⚠️ Invalid Volume",
                "Volume must be between `0` and `100`.",
                COLOR_WARNING
            )
        )

        return

    await player.set_volume(
        value
    )

    await ctx.send(
        embed=embed(
            "🔊 Volume Updated",
            f"Volume is now **{value}%**.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# LEAVE
# ============================================================

@bot.command()
async def leave(ctx):

    player = ctx.guild.voice_client

    if not player:

        await ctx.send(
            embed=embed(
                f"{ERROR} Not Connected",
                "I'm not in a voice channel.",
                COLOR_ERROR
            )
        )

        return

    cancel_idle(
        ctx.guild.id
    )

    player.queue.clear()

    guild_loop[
        ctx.guild.id
    ] = "off"

    await player.disconnect()

    await ctx.send(
        embed=embed(
            "👋 Disconnected",
            "Left the voice channel.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# 24/7
# ============================================================

@bot.command(
    name="247"
)
async def mode_247(ctx):

    guild_id = ctx.guild.id

    enabled = guild_247.get(
        guild_id,
        False
    )

    enabled = not enabled

    guild_247[
        guild_id
    ] = enabled

    if enabled:

        cancel_idle(
            guild_id
        )

        message = (
            "I'll stay in the voice channel "
            "even while idle."
        )

        color = COLOR_SUCCESS

        title = "♾️ 24/7 Enabled"

    else:

        message = (
            "24/7 mode is disabled. "
            "Normal auto-disconnect is active."
        )

        color = COLOR_WARNING

        title = "♾️ 24/7 Disabled"

        player = ctx.guild.voice_client

        if (
            player
            and not player.current
            and not player.queue
        ):

            schedule_idle(
                player
            )

    await ctx.send(
        embed=embed(
            title,
            message,
            color
        )
    )


# ============================================================
# PREFIX
# ============================================================

@bot.command()
@commands.has_permissions(
    manage_guild=True
)
async def prefix(
    ctx,
    new_prefix: Optional[str] = None
):

    current = guild_prefix.get(
        ctx.guild.id,
        DEFAULT_PREFIX
    )

    if new_prefix is None:

        await ctx.send(
            embed=embed(
                "⚙️ Prefix",
                f"Current prefix: `{current}`",
                COLOR_MAIN
            )
        )

        return

    if len(new_prefix) > 5:

        await ctx.send(
            embed=embed(
                "⚠️ Invalid Prefix",
                "Prefix must be 5 characters or fewer.",
                COLOR_WARNING
            )
        )

        return

    guild_prefix[
        ctx.guild.id
    ] = new_prefix

    await ctx.send(
        embed=embed(
            f"{TICK} Prefix Updated",
            f"My new prefix is `{new_prefix}`.",
            COLOR_SUCCESS
        )
    )


# ============================================================
# PING
# ============================================================

@bot.command()
async def ping(ctx):

    latency = round(
        bot.latency * 1000
    )

    player = ctx.guild.voice_client

    description = (
        f"🌐 **Bot:** `{latency}ms`"
    )

    if player and player.node:

        heartbeat = getattr(
            player.node,
            "heartbeat",
            None
        )

        if heartbeat is not None:

            description += (
                f"\n🎧 **Lavalink:** "
                f"`{round(heartbeat)}ms`"
            )

    await ctx.send(
        embed=embed(
            "🏓 Pong!",
            description,
            COLOR_MAIN
        )
    )


# ============================================================
# BOT STATS
# ============================================================

@bot.command(
    name="user",
    aliases=[
        "stats",
        "botinfo"
    ]
)
async def bot_stats(ctx):

    servers = len(
        bot.guilds
    )

    users = sum(
        guild.member_count or 0
        for guild in bot.guilds
    )

    players = len(
        bot.voice_clients
    )

    e = embed(
        "📊 Furious Stats",
        (
            f"🌐 **Servers:** `{servers}`\n"
            f"👥 **Users:** `{users}`\n"
            f"🎧 **Active Players:** `{players}`"
        ),
        COLOR_MAIN
    )

    if bot.user:

        e.set_thumbnail(
            url=bot.user.display_avatar.url
        )

    await ctx.send(
        embed=e
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

    e = discord.Embed(
        title="⚡ Furious Music",
        description=(
            "Music system powered by Lavalink.\n"
            f"Use `{prefix_value}play <song>` to start."
        ),
        color=COLOR_MAIN
    )

    e.add_field(
        name=f"{SPOTIFY} Playback",
        value=(
            f"`{prefix_value}play <song>`\n"
            f"`{prefix_value}pause`\n"
            f"`{prefix_value}resume`\n"
            f"`{prefix_value}skip`\n"
            f"`{prefix_value}stop`"
        ),
        inline=True
    )

    e.add_field(
        name="📋 Queue",
        value=(
            f"`{prefix_value}queue`\n"
            f"`{prefix_value}nowplaying`\n"
            f"`{prefix_value}remove <#>`\n"
            f"`{prefix_value}clear`\n"
            f"`{prefix_value}shuffle`"
        ),
        inline=True
    )

    e.add_field(
        name="🔊 Voice",
        value=(
            f"`{prefix_value}join`\n"
            f"`{prefix_value}leave`\n"
            f"`{prefix_value}volume <0-100>`\n"
            f"`{prefix_value}247`"
        ),
        inline=True
    )

    e.add_field(
        name="🔁 Loop",
        value=(
            f"`{prefix_value}loop off`\n"
            f"`{prefix_value}loop track`\n"
            f"`{prefix_value}loop queue`"
        ),
        inline=True
    )

    e.add_field(
        name="🛠️ Utility",
        value=(
            f"`{prefix_value}ping`\n"
            f"`{prefix_value}prefix <new>`\n"
            f"`{prefix_value}user`"
        ),
        inline=True
    )

    e.add_field(
        name="🎧 Example",
        value=f"`{prefix_value}play Tu`",
        inline=False
    )

    e.set_footer(
        text="Furious • Music & Moderation"
    )

    await ctx.send(
        embed=e
    )


# ============================================================
# COMMAND ERROR
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
            embed=embed(
                "⚠️ Missing Argument",
                f"Missing `{error.param.name}`.",
                COLOR_WARNING
            )
        )

        return

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            embed=embed(
                "⚠️ Invalid Argument",
                "Check the command arguments.",
                COLOR_WARNING
            )
        )

        return

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            embed=embed(
                f"{ERROR} Missing Permissions",
                "You don't have permission to use this command.",
                COLOR_ERROR
            )
        )

        return

    print(
        f"❌ Command error: "
        f"{type(error).__name__}: {error}"
    )

    try:

        await ctx.send(
            embed=embed(
                f"{ERROR} Unexpected Error",
                f"`{type(error).__name__}`",
                COLOR_ERROR
            )
        )

    except discord.HTTPException:
        pass


@bot.command()
async def testsearch(ctx):
    try:
        print("Wavelink version:", wavelink.__version__)
        print("Discord version:", discord.__version__)

        result = await wavelink.Playable.search(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        print("RESULT TYPE:", type(result))
        print("RESULT:", result)

        await ctx.send(f"✅ Search worked: `{type(result).__name__}`")

    except Exception:
        import traceback
        traceback.print_exc()

        await ctx.send("❌ Search test failed. Check Railway logs.")
# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print()
    print("🚀 Starting Furious...")
    print()

    bot.run(
        TOKEN
    )
