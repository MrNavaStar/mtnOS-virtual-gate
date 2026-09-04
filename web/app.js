const panel = document.querySelector("#status-panel");
const mark = document.querySelector("#status-mark");
const eyebrow = document.querySelector("#eyebrow");
const headline = document.querySelector("#headline");
const detail = document.querySelector("#detail");
const gateStatus = document.querySelector("#gate-status");
const gateStatusText = document.querySelector("#gate-status-text");
let idleTimer = null;

function setGateStatus(state, text) {
  gateStatus.dataset.state = state;
  gateStatusText.textContent = text;
}

function scheduleIdleReset() {
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    panel.dataset.state = "idle";
    mark.textContent = "READY";
    eyebrow.textContent = "Present your access card";
    headline.textContent = "Scan to access the mountain.";
    detail.textContent = "Hold your RFID card near the reader to get started.";
  }, 5000);
}

function showScanning() {
  setGateStatus("scanning", "Access Gate (checking)");
  panel.dataset.state = "scanning";
  mark.textContent = "CHECKING";
  eyebrow.textContent = "Card detected";
  headline.textContent = "Checking your access.";
  detail.textContent = "Checking your access...";
}

function showResult(result) {
  const valid = result.valid === true;
  panel.dataset.state = valid ? "valid" : "denied";
  mark.textContent = valid ? "GOOD TO GO" : "CARD NOT VALID";
  eyebrow.textContent = valid ? "Access confirmed" : "Please contact customer service";
  headline.textContent = valid
    ? "You're all set!"
    : "Please visit customer service.";
  detail.textContent = valid
    ? "Have a great day on the mountain!"
    : "Our team can help resolve your card issue.";
  scheduleIdleReset();
}

function showError() {
  setGateStatus("error", "Unavailable");
  panel.dataset.state = "error";
  mark.textContent = "UNAVAILABLE";
  eyebrow.textContent = "Validation request failed";
  headline.textContent = "Please try again";
  detail.textContent = "Please wait a moment and try again.";
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
      setGateStatus("idle", "Awaiting scan");
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
      showScanning();
      if (idleTimer) clearTimeout(idleTimer);
    }
    if (event.type === "validation") {
      setGateStatus(
        event.authenticated === true ? "authenticated" : "unauthenticated",
        event.authenticated === true ? "Access Gate" : "Access Gate (not authenticated)",
      );
      showResult(event.result);
    }
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
