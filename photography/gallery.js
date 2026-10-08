const gallery = document.querySelector("#gallery");
const quote = document.querySelector("#quote");
const announcement = document.querySelector("#announcement");

let photos = [];
let slide = 0;
let revision = 0;
let ready = false;
let manifestLoadFailed = false;
let queuedMoves = 0;
let visibleImage = null;
let loadingImage = null;
let preloadedImage = null;

function photoUrl(photo) {
  return new URL(photo.src, document.baseURI).href;
}

function preloadNext() {
  const next = (slide + 1) % (photos.length + 1);
  if (next === 0) {
    preloadedImage?.removeAttribute("src");
    preloadedImage = null;
    return;
  }

  const src = photoUrl(photos[next - 1]);
  if (preloadedImage?.src === src) return;
  preloadedImage?.removeAttribute("src");
  preloadedImage = new Image();
  preloadedImage.decoding = "async";
  preloadedImage.fetchPriority = "low";
  preloadedImage.src = src;
}

async function showSlide() {
  const thisRevision = ++revision;
  loadingImage?.removeAttribute("src");
  loadingImage = null;

  if (slide === 0) {
    visibleImage?.remove();
    visibleImage = null;
    quote.hidden = false;
    announcement.textContent = manifestLoadFailed ? "The photographs could not be loaded." : "Opening quote.";
    preloadNext();
    return;
  }

  const photo = photos[slide - 1];
  const src = photoUrl(photo);
  const image = preloadedImage?.src === src ? preloadedImage : new Image();
  if (image === preloadedImage) preloadedImage = null;
  image.className = "gallery-photo";
  image.alt = photo.alt || "Photograph";
  image.draggable = false;
  image.decoding = "async";
  image.fetchPriority = "high";
  loadingImage = image;
  if (image.src !== src) image.src = src;

  try {
    await image.decode();
    if (thisRevision !== revision) return;

    // Keep the previous slide in place until the original image is decoded.
    visibleImage?.remove();
    quote.hidden = true;
    gallery.append(image);
    visibleImage = image;
    loadingImage = null;
    announcement.textContent = `Photograph ${slide} of ${photos.length}.`;
    preloadNext();
  } catch (error) {
    if (thisRevision !== revision) return;
    loadingImage = null;
    announcement.textContent = "This photograph could not be loaded.";
    console.error("Could not load photograph:", photo.src, error);
  }
}

function move(direction) {
  if (!ready) {
    queuedMoves += direction;
    return;
  }
  if (!photos.length) return;
  const count = photos.length + 1;
  slide = ((slide + direction) % count + count) % count;
  void showSlide();
}

document.addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.target instanceof HTMLElement &&
      (event.target.isContentEditable || event.target.matches("input, textarea, select"))) return;
  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
    event.preventDefault();
    move(event.key === "ArrowRight" ? 1 : -1);
  }
});

// Swiping provides the same navigation on touch screens, with no visible UI.
// A second pointer cancels the gesture so pinch-to-zoom remains available.
const touches = new Set();
let swipe = null;
function updateZoom() {
  const zoomed = (window.visualViewport?.scale || 1) > 1.01;
  gallery.classList.toggle("is-zoomed", zoomed);
  if (zoomed) swipe = null;
}
window.visualViewport?.addEventListener("resize", updateZoom);
updateZoom();

gallery.addEventListener("pointerdown", (event) => {
  if (event.pointerType !== "touch" || gallery.classList.contains("is-zoomed")) return;
  touches.add(event.pointerId);
  swipe = touches.size === 1 ? { id: event.pointerId, x: event.clientX, y: event.clientY } : null;
});

gallery.addEventListener("pointerup", (event) => {
  touches.delete(event.pointerId);
  if (swipe?.id !== event.pointerId) return;
  const dx = event.clientX - swipe.x;
  const dy = event.clientY - swipe.y;
  swipe = null;
  if (Math.abs(dx) >= 50 && Math.abs(dx) > Math.abs(dy) * 1.25) {
    move(dx < 0 ? 1 : -1);
  }
});

gallery.addEventListener("pointercancel", (event) => {
  touches.delete(event.pointerId);
  swipe = null;
});

async function initialize() {
  try {
    const response = await fetch("photos.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Photo list returned HTTP ${response.status}.`);
    const manifest = await response.json();
    if (!Array.isArray(manifest)) throw new Error("The photo list must be an array.");
    photos = manifest.filter((photo) => photo && typeof photo.src === "string" && photo.src.length).reverse();
  } catch (error) {
    manifestLoadFailed = true;
    console.error("Could not read the photo list:", error);
    announcement.textContent = "The photographs could not be loaded.";
  }

  ready = true;
  if (queuedMoves && photos.length) {
    const count = photos.length + 1;
    slide = ((queuedMoves % count) + count) % count;
  }
  queuedMoves = 0;
  void showSlide();
}

void initialize();
