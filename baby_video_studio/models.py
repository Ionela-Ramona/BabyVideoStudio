from typing import Literal

from pydantic import BaseModel, Field, model_validator

FPS = 30
Motion = Literal["zoom_in", "zoom_out", "pan_left", "pan_right"]
LogoPosition = Literal["top-right", "top-left", "bottom-right", "bottom-left", "center"]


class Scene(BaseModel):
    description: str = ""
    image: str
    motion: Motion = "zoom_in"
    particles: bool = True
    clouds: bool = False
    start_frame: int = Field(ge=0)
    frames: int = Field(gt=0)
    auto_matched: bool = False
    music_cut: bool = False
    lyric_section: str = ""
    time_source: Literal["auto", "lyrics", "manual"] = "auto"

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames


class Segment(BaseModel):
    """One row of the lyrics-synchronized timeline: a lyric line, or an instrumental part."""
    text: str = ""
    section: str = ""
    start: float | None = None  # seconds, marked by the user while listening; it ends where the next row starts
    confidence: float | None = None  # 0..1 from the automatic sync; None = timed by the user (or not timed yet)
    image: str = ""
    motion: Motion = "zoom_in"
    locked: bool = False  # the image was chosen by the user; the automatic storyboard keeps it


class Subtitle(BaseModel):
    """One subtitle: a sung line and when it is on screen."""
    text: str = ""
    start: float | None = None  # seconds
    end: float | None = None
    unsure: bool = False  # the automatic sync was not sure of this line's time


class LogoSettings(BaseModel):
    file: str | None = None
    enabled: bool = False
    mode: Literal["always", "start"] = "always"  # always: a watermark over the whole video; start: only the first seconds
    seconds: float = Field(default=3, ge=1, le=10)  # how long it stays in "start" mode
    size_percent: float = Field(default=8, ge=5, le=40)  # of the video width
    position: LogoPosition = "top-right"
    fade_in: float = Field(default=0.7, ge=0, le=2)
    fade_out: float = Field(default=0.7, ge=0, le=2)  # "start" mode only
    opacity: int = Field(default=65, ge=20, le=100)

    @model_validator(mode="before")
    @classmethod
    def _saved_before_the_watermark(cls, data):
        """Logos saved before the watermark option: sizes never changed from the old defaults take the new ones."""
        if isinstance(data, dict) and data and "mode" not in data:
            data = {key: value for key, value in data.items() if (key, value) not in (("size_percent", 15), ("opacity", 85))}
        return data


class TalkSettings(BaseModel):
    """A talking-character video: which character, which voice, which backdrops, and how lively."""
    character: str = ""  # a saved profile's name
    voice: str | None = None  # in the project's media folder
    decors: list[str] = []  # in the project's media folder, in the order they appear
    mouth: float = Field(default=1.0, ge=0.5, le=1.5)
    blink: bool = True
    blink_every: float = Field(default=4.5, ge=2, le=10)
    blink_speed: Literal["rapid", "normal", "lent"] = "normal"
    sway: float = Field(default=1.0, ge=0, le=2)
    scene_seconds: float = Field(default=8, ge=3, le=60)
    crossfade: float = Field(default=0.6, ge=0.2, le=2)
    preview_start: float = 0.0


Interaction = Literal["", "apropie", "urmareste", "danseaza_impreuna", "imita"]


class Role(BaseModel):
    """One character in an animated scene: what it does, line by line, and with whom."""
    character: str
    action: str = ""  # chosen by the user for the whole scene; empty: the line-by-line choices below
    acts: list[tuple[float, float, str]] = []  # (start, end, action) in song seconds, chosen from the lyrics
    interaction: Interaction = ""
    partner: str = ""  # the other character of the interaction
    at: float | None = None  # when the interaction starts (song seconds)
    enters: float | None = None  # comes into the frame at this moment
    place: tuple[float, float] | None = None  # set by hand: across the zone (0 left, 1 right), depth (0 front, 1 back)
    size: float = Field(default=1.0, ge=0.3, le=2.0)  # set by hand: bigger or smaller than usual in this scene


class AnimScene(BaseModel):
    """A scene of the automatic animation: a stretch of the song on one decor, with its characters."""
    start: float
    end: float
    section: str = ""
    lines: list[str] = []
    decor: str = ""
    effects: list[str] = []
    roles: list[Role] = []
    camera: Literal["apropiere", "departare", "fix", "prim-plan", "aproape", "panoramare"] = "apropiere"
    focus: str = ""  # the character the camera comes close to ("prim-plan"); empty: the middle of the frame
    title: str = ""  # words shown on the screen, at the top, appearing softly (e.g. the song's name in the outro)
    seed: int = 0  # the automatic choices ("🔄 Regenerează")
    look: int = 0  # the visual variant: places, decor details, effects ("🎲 Surprinde-mă"); never the timing
    edited: bool = False  # changed by the user: generating the whole video again keeps it


class AnimationSettings(BaseModel):
    characters: list[str] = []  # from the library, the first one is the main character
    decors: list[str] = []
    singer: str = ""  # whose mouth moves with the voice
    aspect: Literal["16:9", "9:16"] = "16:9"
    energy: float = Field(default=1.0, ge=0.5, le=1.5)  # how big the motions are
    # natural: characters with a skeleton bend arms and legs, hop and walk; fara_deformare: every picture stays exactly
    # as it is (turned and moved only a little), gestures come from frames, nobody walks or hops off the floor
    style: Literal["natural", "fara_deformare"] = "natural"
    scenes: list[AnimScene] = []


class Project(BaseModel):
    name: str = Field(min_length=1)
    audio: str | None = None
    images: list[str] = []
    image_tags: dict[str, str] = {}  # what the user says is in each image
    image_seen: dict[str, dict[str, float]] = {}  # what the automatic storyboard found in each image: {concept: 0..1}
    storyboard: str = ""
    lyrics: str = ""
    mode: Literal["cinematic"] = "cinematic"
    scene_seconds: float = Field(default=15, ge=8, le=30)
    crossfade_seconds: float = Field(default=2, ge=1, le=4)
    fade_out: bool = False
    sparkles: bool = True  # twinkling stars and drifting dust over every scene made from the lyrics timeline
    sync_music: bool = True
    logo: LogoSettings = LogoSettings()
    scenes: list[Scene] = []
    timing: Literal["auto", "synced", "estimated"] = "auto"
    timeline: list[Segment] = []
    subtitles: list[Subtitle] = []  # made from the timeline, then corrected by the user
    kind: Literal["music", "talking", "animation"] = "music"
    talk: TalkSettings = TalkSettings()
    anim: AnimationSettings = AnimationSettings()
