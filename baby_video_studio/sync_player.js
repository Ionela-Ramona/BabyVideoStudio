// Lyrics sync player: plays the song, shows the time and the picture on screen, marks where each row starts,
// and corrects one row at a time (hear it, move its start or end, change its picture, confirm it).
// Changes are kept here and sent to Python as whole lists, so quick taps are never lost between reruns.
const fmt = (t) => {
  if (t == null) return "—";
  const tenths = Math.round(t * 10);
  return `${Math.floor(tenths / 600)}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
};

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  const root = parentElement.querySelector(".sync");
  const $ = (selector) => root.querySelector(selector);
  const audio = $("audio");
  const rows = data.rows;
  const thumbs = data.thumbs;
  const s = (root.state ||= { rev: null, times: [], images: [], ok: [], undo: [], target: 1, current: -1, stopAt: null });

  if (audio.getAttribute("src") !== data.audio) audio.setAttribute("src", data.audio);
  const unsure = (i) => rows[i] && rows[i].unsure && !s.ok.includes(i);
  const nextUnsure = (from) => {
    for (let k = 1; k <= rows.length; k++) if (unsure((from + k) % rows.length)) return (from + k) % rows.length;
    return -1;
  };
  if (s.rev !== data.rev || s.times.length !== rows.length) {
    // The table or the lyrics changed the rows: start again from what Python has.
    s.rev = data.rev;
    s.times = rows.map((r, i) => (i ? r.start : 0));
    s.ok = [];
    s.undo = [];
    const open = s.times.findIndex((t, n) => n > 0 && t == null);
    s.target = open >= 0 ? open : Math.max(nextUnsure(0), 1);
  }
  s.images = rows.map((r) => r.image); // Python applies every change, so its rows are always the latest

  const send = () => setStateValue("marks", { rev: s.rev, times: s.times, images: s.images, ok: s.ok });
  const end = (i) => (i + 1 < rows.length && s.times[i + 1] != null ? s.times[i + 1] : data.total);
  const currentRow = (t) => {
    let found = 0;
    for (let i = 1; i < rows.length; i++) if (s.times[i] != null && s.times[i] <= t) found = i;
    return found;
  };
  const list = $(".rows");

  const showCurrent = () => {
    [...list.children].forEach((li, i) => li.classList.toggle("current", i === s.current));
    const row = rows[s.current];
    $(".preview").src = thumbs[s.images[s.current]] || "";
    $(".lyric").textContent = row.text;
    $(".next").textContent = rows[s.current + 1] ? `Urmează: ${rows[s.current + 1].text}` : "Final";
  };

  const drawButtons = () => {
    const mark = $(".mark");
    const open = s.target < rows.length;
    mark.disabled = !open || s.target === 0;
    mark.textContent = open ? `⏱️ M — aici începe rândul ${s.target + 1}` : "✅ Toate rândurile au timp";
    $(".undo").disabled = !s.undo.length;
    $(".hint").textContent = open
      ? `Rândul ales: ${s.target + 1}, „${rows[s.target].text}” (${rows[s.target].section || "fără secțiune"}). Marcajul încheie și rândul de dinainte.`
      : "Ascultă din nou ca să verifici: imaginea de sus se schimbă la timpii marcați. Apasă pe un rând ca să-l marchezi din nou.";
    const t = s.target;
    const timed = open && s.times[t] != null;
    $(".selected").textContent = open
      ? `${t + 1}. ${fmt(s.times[t])} – ${fmt(end(t))}  ${rows[t].text}` +
        (unsure(t) ? `  ·  ⚠️ nesigur (${Math.round(rows[t].confidence * 100)}%)` : "")
      : "";
    $(".play").disabled = !timed;
    root.querySelectorAll(".start button").forEach((b) => (b.disabled = !open || t === 0));
    root.querySelectorAll(".end button").forEach((b) => (b.disabled = !open || t + 1 >= rows.length));
    $(".ok").disabled = !unsure(t);
    $(".next-unsure").disabled = nextUnsure(t) < 0;
    const select = $(".image");
    select.disabled = !open;
    if (open) select.value = s.images[t];
  };

  const drawList = () => {
    list.replaceChildren(...rows.map((row, i) => {
      const li = document.createElement("li");
      li.classList.toggle("target", i === s.target);
      li.classList.toggle("current", i === s.current);
      li.classList.toggle("unsure", unsure(i));
      li.innerHTML = '<img class="mini" alt=""><span class="time"></span><span class="section"></span><span class="text"></span>';
      const img = li.querySelector("img");
      if (thumbs[s.images[i]]) img.src = thumbs[s.images[i]];
      li.querySelector(".time").textContent = `${unsure(i) ? "⚠️ " : ""}${i + 1}. ${fmt(s.times[i])} – ${fmt(end(i))}`;
      li.querySelector(".section").textContent = row.section;
      li.querySelector(".text").textContent = row.text;
      li.onclick = () => select(i);
      return li;
    }));
  };

  const redraw = () => {
    drawList();
    drawButtons();
  };
  const playRow = (i) => {
    if (s.times[i] == null) return;
    audio.currentTime = Math.max(0, s.times[i] - 1);
    s.stopAt = Math.min(end(i) + 0.5, data.total);
    audio.play();
  };
  const select = (i) => {
    s.target = i;
    redraw();
    list.children[i].scrollIntoView({ block: "nearest" });
    playRow(i);
  };

  const mark = () => {
    if (s.target < 1 || s.target >= rows.length) return;
    const i = s.target;
    s.undo.push([i, i, s.times[i]]);
    s.times[i] = Math.round(audio.currentTime * 100) / 100;
    s.target = i + 1;
    send();
    redraw();
    list.children[Math.min(s.target, rows.length - 1)].scrollIntoView({ block: "nearest" });
  };
  const undo = () => {
    const last = s.undo.pop();
    if (!last) return;
    s.target = last[0];
    s.times[last[1]] = last[2];
    send();
    redraw();
  };
  const nudge = (edge, seconds) => {
    // edge 0 moves the selected row's start; edge 1 moves its end, which is the next row's start
    const t = s.target;
    const i = t + edge;
    if (i < 1 || i >= rows.length) return;
    const from = s.times[i] ?? audio.currentTime;
    s.undo.push([t, i, s.times[i]]);
    s.times[i] = Math.max(0, Math.round((from + seconds) * 100) / 100);
    send();
    redraw();
    playRow(t);
  };
  const press = (action) => (e) => {
    e.currentTarget.blur(); // a focused button would also react to the space bar
    action(e);
  };
  $(".mark").onclick = press(mark);
  $(".undo").onclick = press(undo);
  $(".back").onclick = press(() => (audio.currentTime = Math.max(0, audio.currentTime - 3)));
  $(".play").onclick = press(() => playRow(s.target));
  root.querySelectorAll(".start button").forEach((b) => (b.onclick = press(() => nudge(0, Number(b.dataset.d)))));
  root.querySelectorAll(".end button").forEach((b) => (b.onclick = press(() => nudge(1, Number(b.dataset.d)))));
  $(".ok").onclick = press(() => {
    s.ok.push(s.target);
    send();
    const next = nextUnsure(s.target);
    if (next > 0) select(next); else redraw();
  });
  $(".next-unsure").onclick = press(() => {
    const next = nextUnsure(s.target);
    if (next > 0) select(next);
  });
  const picker = $(".image");
  picker.replaceChildren(...data.images.map((name) => new Option(name, name)));
  picker.onchange = () => {
    s.images[s.target] = picker.value;
    send();
    redraw();
    s.current = -1; // refresh the big picture
  };
  $(".rate").onchange = (e) => (audio.playbackRate = Number(e.target.value));
  audio.onratechange = () => ($(".rate").value = String(audio.playbackRate));
  audio.onpause = () => (s.stopAt = null);

  const host = parentElement.host || parentElement;
  const onKey = (e) => {
    const active = document.activeElement;
    if ((active && active !== document.body && active !== host) || e.ctrlKey || e.metaKey || e.altKey) return;
    const inner = e.composedPath()[0];
    if (["INPUT", "TEXTAREA", "SELECT"].includes(inner.tagName)) return;
    if (e.key === "m" || e.key === "M") {
      e.preventDefault();
      mark();
    } else if (e.key === " " && !["AUDIO", "BUTTON"].includes(inner.tagName)) {
      e.preventDefault();
      if (audio.paused) audio.play(); else audio.pause();
    }
  };
  if (s.onKey) document.removeEventListener("keydown", s.onKey);
  document.addEventListener("keydown", (s.onKey = onKey));

  const tick = () => {
    $(".clock").textContent = `${fmt(audio.currentTime)} / ${fmt(data.total)}`;
    if (s.stopAt != null && audio.currentTime >= s.stopAt) audio.pause();
    const current = currentRow(audio.currentTime);
    if (current !== s.current) {
      s.current = current;
      showCurrent();
    }
    s.frame = requestAnimationFrame(tick);
  };
  cancelAnimationFrame(s.frame);
  redraw();
  s.current = -1;
  tick();

  return () => {
    cancelAnimationFrame(s.frame);
    document.removeEventListener("keydown", onKey);
  };
}
