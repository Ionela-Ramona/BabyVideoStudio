// Subtitle preview: plays the song and shows the subtitle of the current moment, as YouTube will.
const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector(".subs");
  const audio = root.querySelector("audio");
  const line = root.querySelector(".line");
  const clock = root.querySelector(".clock");
  if (audio.getAttribute("src") !== data.audio) audio.setAttribute("src", data.audio);

  const show = () => {
    const t = audio.currentTime;
    const cue = data.cues.find((c) => c.start <= t && t < c.end);
    line.textContent = cue ? cue.text : "";
    line.classList.toggle("unsure", Boolean(cue && cue.unsure));
    clock.textContent = `${fmt(t)} / ${fmt(data.total)}${cue ? `  ·  subtitrarea ${cue.n}` : ""}`;
    root.state = requestAnimationFrame(show);
  };
  cancelAnimationFrame(root.state);
  show();
  return () => cancelAnimationFrame(root.state);
}
