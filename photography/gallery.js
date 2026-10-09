const gallery = document.querySelector("#gallery");
const navigation = document.querySelector("#gallery-nav");
const announcement = document.querySelector("#announcement");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const frames = [document.querySelector("#quote")];
const links = [navigation.querySelector("a")];
const photographs = new Map();
let activeFrame = -1;
let manifestFailed = false;
let scrollUpdate = null;

function announceCurrent() {
  if (activeFrame === 0) {
    announcement.textContent = manifestFailed
      ? "The photographs could not be loaded."
      : "Opening quote.";
    return;
  }
  const photograph = photographs.get(frames[activeFrame]);
  if (!photograph) return;
  const description = `Photograph ${activeFrame} of ${frames.length - 1}`;
  announcement.textContent = photograph.failed
    ? `${description} could not be loaded.`
    : photograph.loaded ? `${description}.` : `${description} is loading.`;
}

async function loadPhotograph(frame, priority = "low") {
  const photograph = photographs.get(frame);
  if (!photograph) return;
  const { image, status, photo } = photograph;
  if (priority === "high") image.fetchPriority = "high";
  if (photograph.started) return;
  photograph.started = true;
  image.fetchPriority = priority;
  frame.setAttribute("aria-busy", "true");
  status.hidden = false;

  try {
    image.src = new URL(photo.src, document.baseURI).href;
    // Decode the original directly. No resized or recompressed versions exist.
    await image.decode();
    photograph.loaded = true;
    image.hidden = false;
    status.hidden = true;
  } catch (error) {
    photograph.failed = true;
    status.textContent = "This photograph could not be loaded.";
    console.error("Could not load photograph:", photo.src, error);
  }
  frame.setAttribute("aria-busy", "false");
  if (frames[activeFrame] === frame) announceCurrent();
}

function updateCurrentFrame() {
  const viewport = gallery.getBoundingClientRect();
  const center = viewport.top + gallery.clientTop + gallery.clientHeight / 2;
  let nearest = 0;
  let distance = Infinity;
  frames.forEach((frame, index) => {
    const bounds = frame.getBoundingClientRect();
    const candidate = Math.abs(bounds.top + bounds.height / 2 - center);
    if (candidate < distance) {
      nearest = index;
      distance = candidate;
    }
  });

  if (nearest !== activeFrame) {
    activeFrame = nearest;
    links.forEach((link, index) => {
      if (index === nearest) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
    announceCurrent();
  }
  void loadPhotograph(frames[nearest], "high");
  void loadPhotograph(frames[nearest + 1]);
}

function scheduleScrollUpdate() {
  if (scrollUpdate !== null) return;
  scrollUpdate = requestAnimationFrame(() => {
    scrollUpdate = null;
    updateCurrentFrame();
  });
}

function scrollToFrame(frame, smooth = true) {
  const top = gallery.scrollTop + frame.getBoundingClientRect().top
    - gallery.getBoundingClientRect().top - gallery.clientTop;
  gallery.scrollTo({
    top,
    behavior: smooth && !reducedMotion.matches ? "smooth" : "auto",
  });
}

function scrollToHash() {
  const frame = frames.find((candidate) => `#${candidate.id}` === location.hash)
    || (location.hash ? null : frames[0]);
  if (frame) scrollToFrame(frame, false);
}

navigation.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest("a");
  if (!link || !navigation.contains(link)) return;
  const frame = frames.find((candidate) => `#${candidate.id}` === link.getAttribute("href"));
  if (!frame) return;
  event.preventDefault();
  if (location.hash !== `#${frame.id}`) history.pushState(null, "", `#${frame.id}`);
  scrollToFrame(frame);
});

// Scrolling, touch gestures, pinch zoom, and keyboard scrolling stay native.
gallery.addEventListener("scroll", scheduleScrollUpdate, { passive: true });
window.addEventListener("resize", scheduleScrollUpdate);
window.addEventListener("hashchange", scrollToHash);

async function initialize() {
  updateCurrentFrame();
  try {
    const response = await fetch("photos.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Photo list returned HTTP ${response.status}.`);
    const manifest = await response.json();
    if (!Array.isArray(manifest)) throw new Error("The photo list must be an array.");
    const photos = manifest.filter((photo) => photo && typeof photo.src === "string" && photo.src.length).reverse();

    photos.forEach((photo, index) => {
      const number = String(index + 1).padStart(2, "0");
      const description = `Photograph ${index + 1} of ${photos.length}`;
      const frame = document.createElement("section");
      frame.id = `photo-${number}`;
      frame.className = "frame photo-frame";
      frame.setAttribute("aria-label", description);

      const image = new Image();
      image.className = "gallery-photo";
      image.alt = typeof photo.alt === "string" && photo.alt ? photo.alt : description;
      image.draggable = false;
      image.decoding = "async";
      image.hidden = true;

      const status = document.createElement("p");
      status.className = "photo-status";
      status.textContent = "Loading photograph…";
      status.setAttribute("aria-hidden", "true");
      frame.append(image, status);
      gallery.append(frame);

      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `#${frame.id}`;
      link.textContent = number;
      link.setAttribute("aria-label", description);
      item.append(link);
      navigation.append(item);

      frames.push(frame);
      links.push(link);
      photographs.set(frame, { photo, image, status, started: false, loaded: false, failed: false });
    });

    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          void loadPhotograph(entry.target, frames[activeFrame] === entry.target ? "high" : "low");
          observer.unobserve(entry.target);
        }
      }, { root: gallery, rootMargin: "0px 0px 200px 0px" });
      photographs.forEach((_, frame) => observer.observe(frame));
    }
    scrollToHash();
    updateCurrentFrame();
  } catch (error) {
    manifestFailed = true;
    announcement.textContent = "The photographs could not be loaded.";
    console.error("Could not read the photo list:", error);
  }
}

void initialize();
