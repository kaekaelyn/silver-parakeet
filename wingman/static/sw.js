// Wingman service worker: minimal app-shell cache so the PWA installs and
// opens with a friendly message when the box is unreachable. Everything
// live goes to the network first — this is a local-first app, not an
// offline one.
const CACHE = "wingman-v1";
const SHELL = ["/static/wingman.css", "/static/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return; // never intercept form posts
  event.respondWith(
    fetch(event.request).catch(async () => {
      const cached = await caches.match(event.request);
      if (cached) return cached;
      return new Response(
        "<h1>Wingman is unreachable</h1><p>Check that the Wingman box is on " +
          "and that your phone can reach it (same Wi-Fi or Tailscale).</p>",
        { status: 503, headers: { "Content-Type": "text/html" } }
      );
    })
  );
});
