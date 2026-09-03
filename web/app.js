const panel = document.querySelector("#status-panel");
const mark = document.querySelector("#status-mark");
const eyebrow = document.querySelector("#eyebrow");
const headline = document.querySelector("#headline");
const detail = document.querySelector("#detail");
const client = document.querySelector("#client");
let idleTimer = null;

function scheduleIdleReset() {
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    panel.dataset.state = "idle";
    mark.textContent = "READY";
    eyebrow.textContent = "Present your access card";
    headline.textContent = "Scan to access the mountain.";
    detail.textContent = "Hold your RFID card near the reader to get started.";
    document.querySelector("#client-age").textContent = "";
    document.querySelector("#variant").textContent = "";
    document.querySelector("#client-name").textContent = "";
    const photo = document.querySelector("#client-photo");
    photo.hidden = true;
    client.hidden = true;
  }, 5000);
}

function showScanning(id) {
  panel.dataset.state = "scanning";
  mark.textContent = "CHECKING";
  eyebrow.textContent = "Card detected";
  headline.textContent = id;
  detail.textContent = "Checking your access...";
  client.hidden = true;
  document.querySelector("#last-scan").textContent = `Last scan: ${id}`;
}

function showResult(result) {
  const valid = result.valid === true;
  panel.dataset.state = valid ? "valid" : "denied";
  mark.textContent = valid ? "GOOD TO GO" : "CARD NOT VALID";
  eyebrow.textContent = valid ? "Access confirmed" : "Please contact customer service";
  headline.textContent = result.clientName || result.mediaIdentifier || "Unknown media";
  detail.textContent = valid
    ? "You're all set. Have a great day on the mountain!"
    : "Please visit customer service so we can resolve this before you head up.";
  document.querySelector("#client-age").textContent = result.clientAge == null ? "" : `${result.clientAge} years`;
  document.querySelector("#variant").textContent = result.variantName || "";
  document.querySelector("#client-name").textContent = result.clientName || "";
  client.hidden = !result.clientName && result.clientAge == null && !result.variantName;
  const photo = document.querySelector("#client-photo");
  photo.hidden = !result.clientPhotoUrl;
  if (result.clientPhotoUrl) photo.src = result.clientPhotoUrl;
  scheduleIdleReset();
}

function showError(message) {
  panel.dataset.state = "error";
  mark.textContent = "UNAVAILABLE";
  eyebrow.textContent = "Validation request failed";
  headline.textContent = "Please try again";
  detail.textContent = message;
  client.hidden = true;
  if (idleTimer) clearTimeout(idleTimer);
}

fetch("/config").then(response => response.json()).then(config => {
  document.querySelector("#device").textContent = config.hostname || "——";
  if (config.logo) {
    const logo = document.querySelector("#logo");
    logo.src = config.logo;
    logo.hidden = false;
  }
}).catch(() => showError("Kiosk configuration is unavailable"));

let events;

function connectEvents() {
  if (events) {
    events.close();
  }

  events = new EventSource("/events");
  events.onopen = () => {
    if (document.querySelector("#status-panel").dataset.state === "error") {
      const panel = document.querySelector("#status-panel");
      panel.dataset.state = "scanning";
      mark.textContent = "CHECKING";
      eyebrow.textContent = "Reconnected";
      headline.textContent = "Ready for your card";
      detail.textContent = "Connection restored.";
    }
  };

  events.onmessage = ({ data }) => {
    const event = JSON.parse(data);
    if (event.type === "scanning") {
      showScanning(event.mediaIdentifier);
      if (idleTimer) clearTimeout(idleTimer);
    }
    if (event.type === "validation") showResult(event.result);
    if (event.type === "error") showError(event.message);
  };

  events.onerror = () => {
    const panel = document.querySelector("#status-panel");
    if (events.readyState === EventSource.CONNECTING) {
      panel.dataset.state = "error";
      mark.textContent = "RECONNECTING";
      eyebrow.textContent = "Connection issue";
      headline.textContent = "Re-establishing link";
      detail.textContent = "Trying to reconnect to the gate server...";
      setTimeout(connectEvents, 2000);
    } else if (events.readyState === EventSource.CLOSED) {
      showError("Connection to the gate server was lost");
      setTimeout(connectEvents, 2000);
    }
  };
}

connectEvents();
