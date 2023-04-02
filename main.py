from yt_dlp import YoutubeDL
import discord
import patterns
import asyncio
from dotenv import dotenv_values
from discord.utils import get as dget
from discord import FFmpegPCMAudio
from montydb import MontyClient
from functools import partial
from validators import url as validate_url
from dataclasses import dataclass, field, asdict
from enum import IntEnum, Enum
from typing import Optional
from random import shuffle


intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Bot(intents=intents)

_db = MontyClient("klatkadb").klatka.data


class LoopState(IntEnum):
    NoLoop = 0
    Single = 1
    Queue = 2


@dataclass
class GuildSettings:
    channel_id: int
    player_id: int
    loop: LoopState


class QueryType(Enum):
    Title = 0
    Url = 1


@dataclass
class Song:
    query_type: QueryType
    query: str
    title: str
    thumbnail_url: str


@dataclass
class GuildState:
    settings: GuildSettings
    player: discord.Message
    channel: discord.TextChannel
    queue: list[Song] = field(default_factory=list)
    playing: bool = False


state: dict[str, GuildState] = {}


@client.event
async def on_ready():
    for guild_data in _db.find():
        channel = await client.fetch_channel(guild_data["settings"]["channel_id"])
        player = await channel.fetch_message(guild_data["settings"]["player_id"])
        guild_settings = GuildSettings(
            guild_data["settings"]["channel_id"],
            guild_data["settings"]["player_id"],
            LoopState(guild_data["settings"]["loop"])
        )
        guild_state = GuildState(guild_settings, player, channel)
        state[guild_data["guild_id"]] = guild_state
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    if message.guild.id in state.keys():
        if message.channel.id == state[message.guild.id].settings.channel_id:
            content, author = message.content, message.author
            await message.delete()
            await handle_new_song(message.guild.id, content, author)


@client.event
async def on_raw_reaction_add(reaction_event: discord.RawReactionActionEvent):
    if reaction_event.user_id == client.user.id:
        return
    if reaction_event.guild_id in state.keys():
        if reaction_event.message_id == state[reaction_event.guild_id].settings.player_id:
            await state[reaction_event.guild_id].player.remove_reaction(reaction_event.emoji, reaction_event.member)
            await handle_reaction(reaction_event.emoji.name, reaction_event.guild_id)


@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member == client.user and (before.channel != after.channel) and before.channel:
        if after.channel:
            await member.move_to(None)
        state[member.guild.id].queue = []
        await update_player(member.guild.id)


async def handle_play_pause(guild_id: int):
    voice: discord.VoiceClient = dget(client.voice_clients, guild__id=guild_id)

    if voice and voice.is_connected():
        if voice.is_playing():
            voice.pause()
        else:
            voice.resume()


async def handle_stop(guild_id: int):
    voice: discord.VoiceClient = dget(client.voice_clients, guild__id=guild_id)

    if voice and voice.is_connected():
        state[guild_id].queue = []
        await voice.disconnect()
        await update_player(guild_id)


async def handle_skip(guild_id: int):
    voice: discord.VoiceClient = dget(client.voice_clients, guild__id=guild_id)

    if voice and voice.is_connected():
        voice.stop()


async def handle_loop(guild_id: int):
    state_changes = {
        LoopState.NoLoop: LoopState.Queue,
        LoopState.Queue: LoopState.Single,
        LoopState.Single: LoopState.NoLoop
    }
    state[guild_id].settings.loop = state_changes[state[guild_id].settings.loop]
    await update_player(guild_id)


async def handle_shuffle(guild_id: int):
    queue = state[guild_id].queue
    if len(queue) > 1:
        current_song = queue[0]
        if current_song in queue[1:]:
            queue.pop(0)
        shuffle(queue)
        queue.insert(0, current_song)
        await update_player(guild_id)


player_controls = {
    "⏯️": handle_play_pause,
    "⏭️": handle_skip,
    "⏹️": handle_stop,
    "🔄": handle_loop,
    "🔀": handle_shuffle,
}


async def handle_reaction(emoji: str, guild_id: int):
    if emoji in player_controls.keys():
        await player_controls[emoji](guild_id)
    else:
        return


@client.slash_command()
async def init(ctx: discord.ApplicationContext, channel_name: str):
    guild = ctx.interaction.guild
    if guild.id in state.keys():
        channel_id = state[guild.id].settings.channel_id
        await ctx.respond(f"Bot już prężnie działa na <#{channel_id}>", ephemeral=True)
    else:
        new_channel = await guild.create_text_channel(channel_name)
        player_message = get_empty_player(guild.id)
        player = await new_channel.send(player_message[0], embed=player_message[1])
        for emoji in player_controls:
            await player.add_reaction(emoji)
        new_guild_settings = GuildSettings(new_channel.id, player.id, LoopState.NoLoop)
        new_guild_state = GuildState(new_guild_settings, player, new_channel)
        state[guild.id] = new_guild_state
        _db.insert_one({"guild_id": guild.id, "settings": asdict(new_guild_settings)})
        await ctx.respond(f"Stworzyłem nowy kanał - <#{new_channel.id}>. Użyj go, aby puścić muzykę!", ephemeral=True)


@client.slash_command()
async def wavify(ctx: discord.ApplicationContext, message: str):
    if len(message) > 9:
        await ctx.respond("Message too long!", ephemeral=True)
    else:
        result = patterns.converge(message)
        await ctx.respond("\n".join(result))


@client.slash_command()
async def remove(ctx: discord.ApplicationContext, song_id: int):
    guild = ctx.interaction.guild
    if guild.id not in state.keys():
        await ctx.respond(f"Wpierw aktywuj bota za pomocą komendy /init!", ephemeral=True)
    else:
        queue = state[guild.id].queue
        if len(queue) - 1 < song_id:
            await ctx.respond(f"W kolejce nie ma takiej piosenki!", ephemeral=True)
        else:
            queue.pop(song_id)
            await update_player(guild.id)


loop_indicators = {
    LoopState.NoLoop: "Brak ❌",
    LoopState.Queue: "Kolejka ♾️",
    LoopState.Single: "Piosnka 1️⃣"
}


def get_empty_player(guild_id) -> tuple[str, discord.Embed]:
    return (get_empty_queue(), get_empty_embed(guild_id))


def get_empty_queue() -> str:
    return "**__Kolejka:__**\n     -"


def get_empty_embed(guild_id) -> discord.Embed:
    loop_state = state[guild_id].settings.loop
    embed = discord.Embed(
        color = discord.Color.from_rgb(3, 188, 255),
        title = "Cicho tu...",
        description = f"**Loop:** {loop_indicators[loop_state]}\nWyślij tytuł albo URL piosnki aby dodać ją do kolejki!"
    )
    embed.set_image(url="https://i.imgur.com/jIlHGic.png")
    return embed


def get_active_player(guild_id: int) -> tuple[str, discord.Embed]:
    return (get_active_queue(guild_id), get_active_embed(guild_id))


def get_active_queue(guild_id: int) -> str:
    queue = state[guild_id].queue
    if len(queue) > 1:
        queue_text = "**__Kolejka:__**\n"
        for counter, song in reversed(list(enumerate(queue[1:], 1))):
            title = song.title
            queue_text += f"**{counter:>6}.** {title}\n"
        return queue_text
    else:
        return get_empty_queue()


def get_active_embed(guild_id: int) -> discord.Embed:
    song = state[guild_id].queue[0]
    loop_state = state[guild_id].settings.loop
    embed = discord.Embed(
        color = discord.Color.from_rgb(3, 188, 255),
        title = song.title,
        description = f"**Loop:** {loop_indicators[loop_state]}\nWyślij tytuł albo URL piosnki aby dodać ją do kolejki!"
    )
    embed.set_image(url=song.thumbnail_url)
    return embed
            

async def update_player(guild_id: int):
    player = state[guild_id].player
    if len(state[guild_id].queue) == 0:
        await player.edit(*get_empty_player(guild_id))
    else:
        await player.edit(*get_active_player(guild_id))


async def search(query: str) -> tuple[Song, str]:
    with YoutubeDL({"format": "bestaudio", "noplaylist": True, "skip_download": True}) as ydl:
        if validate_url(query) and ("youtube.com" in query or "youtu.be" in query):
            extraction = partial(ydl.extract_info, url=query, download=False)
            info = await client.loop.run_in_executor(None, extraction)
            url = sorted(filter(lambda x: x["audio_ext"] != "none" and x["video_ext"] == "none", info["formats"]), key=lambda x: x["quality"])[-1]["url"]
            return Song(QueryType.Url, query, info["title"], info["thumbnail"]), url
        else:
            extraction = partial(ydl.extract_info, url=f"ytsearch:{query}", download=False)
            info = await client.loop.run_in_executor(None, extraction)
            info = info["entries"][0]
            url = sorted(filter(lambda x: x["audio_ext"] != "none" and x["video_ext"] == "none", info["formats"]), key=lambda x: x["quality"])[-1]["url"]
            return Song(QueryType.Title, query, info["title"], info["thumbnail"]), url


async def handle_new_song(guild_id: int, query: str, user: discord.Member):
    song, stream = await search(query)
    channel = user.voice.channel
    if channel:
        state[guild_id].queue.append(song)

        voice: discord.VoiceClient = dget(client.voice_clients, guild__id=guild_id)

        if not state[guild_id].playing:
            state[guild_id].playing = True
            if not voice or not voice.is_connected():
                voice = await channel.connect()
            await asyncio.gather(play_next_song(guild_id, voice, stream), update_player(guild_id))
        else:
            await update_player(guild_id)


async def wait_for_song(guild_id):
    while not state[guild_id].playing:
        await asyncio.sleep(0.1)
    return


async def play_next_song(guild_id: str, voice: discord.VoiceClient, stream: Optional[str] = None):
    FFMPEG_OPTS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
    handle_song_end = lambda _: asyncio.run_coroutine_threadsafe(play_next_song(guild_id, voice), client.loop).result()
    if stream and voice and voice.is_connected():
        voice.play(
            FFmpegPCMAudio(stream, **FFMPEG_OPTS),
            after = handle_song_end
        )
    else:
        _db.update_one({"guild_id": guild_id}, {"$set": {"settings.loop": state[guild_id].settings.loop}})
        queue = state[guild_id].queue
        if state[guild_id].settings.loop != LoopState.Single and len(queue) != 0:
            last_song = queue.pop(0)
            if state[guild_id].settings.loop == LoopState.Queue:
                queue.append(last_song)
        if len(state[guild_id].queue) > 0 and voice and voice.is_connected():
            await update_player(guild_id)

            _, stream = await search(queue[0].query)

            voice.play(
                FFmpegPCMAudio(stream, **FFMPEG_OPTS),
                after = handle_song_end
            )
        else:
            await update_player(guild_id)
            state[guild_id].playing = False
            try:
                await asyncio.wait_for(wait_for_song(guild_id), 300)
            except asyncio.TimeoutError:
                if voice.is_connected():
                    await voice.disconnect()
                    await state[guild_id].channel.send("Rozłączam się bo mi się nudzi", delete_after=10)


@client.event
async def on_disconnect():
    print("Disconnected!")


api_token = dotenv_values(".env")["API_KEY"]

client.run(api_token)
    


        
    
