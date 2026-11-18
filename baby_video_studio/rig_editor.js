// Skeleton editor: the character's picture with its joints as dots joined by bones; drag a dot to move it.
// The new places go to Python when a dot is let go (fractions of the picture), so a slow drag is never lost.
const NS = "http://www.w3.org/2000/svg";

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  const root = parentElement.querySelector(".rig");
  const img = root.querySelector("img");
  const svg = root.querySelector("svg");
  const hint = root.querySelector(".hint");
  const s = (root.state ||= { rev: null, points: {}, drag: null });
  if (img.getAttribute("src") !== data.image) img.setAttribute("src", data.image);
  if (s.rev !== data.rev) {
    s.rev = data.rev;
    s.points = JSON.parse(JSON.stringify(data.points));
  }
  svg.setAttribute("viewBox", `0 0 ${data.width} ${data.height}`);
  const r = data.height / 70;

  const draw = () => {
    svg.replaceChildren();
    for (const [a, b] of data.bones) {
      const line = document.createElementNS(NS, "line");
      const [x1, y1] = s.points[a], [x2, y2] = s.points[b];
      line.setAttribute("x1", x1 * data.width); line.setAttribute("y1", y1 * data.height);
      line.setAttribute("x2", x2 * data.width); line.setAttribute("y2", y2 * data.height);
      line.setAttribute("stroke-width", r / 2.5);
      svg.append(line);
    }
    for (const [name, [x, y]] of Object.entries(s.points)) {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", x * data.width); dot.setAttribute("cy", y * data.height); dot.setAttribute("r", r);
      dot.dataset.name = name;
      if (s.drag === name) dot.classList.add("active");
      const title = document.createElementNS(NS, "title");
      title.textContent = data.labels[name];
      dot.append(title);
      svg.append(dot);
    }
  };
  const at = (event) => {
    const box = svg.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
            Math.min(1, Math.max(0, (event.clientY - box.top) / box.height))];
  };
  svg.onpointerdown = (event) => {
    const name = event.target.dataset && event.target.dataset.name;
    if (!name) return;
    s.drag = name;
    svg.setPointerCapture(event.pointerId);
    hint.textContent = `Muți: ${data.labels[name]}`;
    draw();
  };
  svg.onpointermove = (event) => {
    if (!s.drag) return;
    s.points[s.drag] = at(event);
    draw();
  };
  svg.onpointerup = () => {
    if (!s.drag) return;
    hint.textContent = `Pus: ${data.labels[s.drag]}. Pozele de mai jos se refac.`;
    s.drag = null;
    draw();
    setStateValue("points", { rev: s.rev, points: s.points });
  };
  svg.onmouseover = (event) => {
    const name = event.target.dataset && event.target.dataset.name;
    if (name && !s.drag) hint.textContent = data.labels[name];
  };
  draw();
}
