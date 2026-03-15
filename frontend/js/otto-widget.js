/**
 * OttO Navigation Widget
 * Floating button that links to the OttO dedicated call page (/otto).
 * The actual voice call experience lives at /otto.
 */
(function () {
  // Don't show the widget on the OttO page itself
  if (location.pathname === "/otto") return;

  const widget = document.createElement("div");
  widget.id = "otto-widget";
  widget.innerHTML = `
    <a id="otto-trigger" href="/otto" title="Talk to OttO">
      <span class="otto-tooltip">Talk to OttO</span>
      <svg class="otto-mic-svg" width="22" height="22" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="2" width="6" height="12" rx="3"/>
        <path d="M5 10a7 7 0 0 0 14 0"/>
        <line x1="12" y1="20" x2="12" y2="23"/>
        <line x1="9"  y1="23" x2="15" y2="23"/>
      </svg>
    </a>
  `;
  document.body.appendChild(widget);
})();
