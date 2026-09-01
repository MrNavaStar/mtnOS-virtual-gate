const panel = document.querySelector("#status-panel");
const mark = document.querySelector("#status-mark");
const eyebrow = document.querySelector("#eyebrow");
const headline = document.querySelector("#headline");
const detail = document.querySelector("#detail");
const client = document.querySelector("#client");

function showScanning(id) {
  panel.dataset.state = "scanning";
  mark.textContent = "CHECKING";
  eyebrow.textContent = "Media detected";
  headline.textContent = id;
  detail.textContent = "Contacting access control...";
  client.hidden = true;
  document.querySelector("#last-scan").textContent = `Last scan: ${id}`;
}

function showResult(result) {
  const valid = result.valid === true;
  panel.dataset.state = valid ? "valid" : "denied";
  mark.textContent = valid ? "ACCESS GRANTED" : "ACCESS DENIED";
  eyebrow.textContent = result.validationCode || "Validation result";
  headline.textContent = result.clientName || result.mediaIdentifier || "Unknown media";
  detail.textContent = result.reason || (valid ? "Permission verified" : "No permission available");
  document.querySelector("#client-age").textContent = result.clientAge == null ? "" : `${result.clientAge} years`;
  document.querySelector("#variant").textContent = result.variantName || "";
  document.querySelector("#client-name").textContent = result.clientName || "";
  client.hidden = !result.clientName && result.clientAge == null && !result.variantName;
  const photo = document.querySelector("#client-photo");
  photo.hidden = !result.clientPhotoUrl;
  if (result.clientPhotoUrl) photo.src = result.clientPhotoUrl;
}

function showError(message) {
  panel.dataset.state = "error";
  mark.textContent = "UNAVAILABLE";
  eyebrow.textContent = "Validation request failed";
  headline.textContent = "Please try again";
  detail.textContent = message;
  client.hidden = true;
}

fetch("/config").then(response => response.json()).then(config => {
  document.querySelector("#device").textContent = config.controlDevice || "";
  if (config.logo) {
    const logo = document.querySelector("#logo");
    logo.src = config.logo;
    logo.hidden = false;
    document.querySelector("#brand").hidden = true;
  }
}).catch(() => showError("Kiosk configuration is unavailable"));

const events = new EventSource("/events");
events.onmessage = ({ data }) => {
  const event = JSON.parse(data);
  if (event.type === "scanning") showScanning(event.mediaIdentifier);
  if (event.type === "validation") showResult(event.result);
  if (event.type === "error") showError(event.message);
};
events.onerror = () => showError("Connection to the gate server was lost");
