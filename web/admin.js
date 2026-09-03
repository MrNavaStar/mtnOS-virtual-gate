const form = document.querySelector("#config-form");
const message = document.querySelector("#message");
let fields = {};

function addField(container, key, definition, value) {
  const wrapper = document.createElement("label");
  wrapper.className = "field";
  wrapper.htmlFor = `field-${key}`;
  wrapper.textContent = definition.label;
  const input = document.createElement("input");
  if (definition.type === "boolean") {
    input.type = "checkbox";
    input.checked = value === true;
  } else {
    input.type = definition.secret ? "password" : definition.type === "number" ? "number" : "text";
    input.step = definition.type === "number" ? "any" : "1";
    input.value = value ?? "";
  }
  input.id = `field-${key}`;
  input.name = key;
  input.dataset.type = definition.type;
  wrapper.append(input);
  container.append(wrapper);
  fields[key] = input;
}

function addCategory(category, values, definitions) {
  const section = document.createElement("section");
  section.className = "config-section";
  const heading = document.createElement("h2");
  heading.textContent = category.label;
  section.append(heading);
  const grid = document.createElement("div");
  grid.className = "config-grid";
  let connectionGroup;
  let credentialGroup;
  category.fields.forEach(key => {
    if (category.key === "mtnos" && ["mtnos-server", "control-device"].includes(key)) {
      if (!connectionGroup) {
        connectionGroup = document.createElement("div");
        connectionGroup.className = "config-group";
        const connectionHeading = document.createElement("h3");
        connectionHeading.textContent = "Connection";
        connectionGroup.append(connectionHeading);
        grid.append(connectionGroup);
      }
      addField(connectionGroup, key, definitions[key], values[key]);
      return;
    }
    if (category.key === "mtnos" && ["mtnos-username", "mtnos-password"].includes(key)) {
      if (!credentialGroup) {
        credentialGroup = document.createElement("div");
        credentialGroup.className = "config-group";
        const credentialHeading = document.createElement("h3");
        credentialHeading.textContent = "Credentials";
        credentialGroup.append(credentialHeading);
        grid.append(credentialGroup);
      }
      addField(credentialGroup, key, definitions[key], values[key]);
      return;
    }
    addField(grid, key, definitions[key], values[key]);
  });
  section.append(grid);
  form.append(section);
}

fetch("/admin/config").then(response => response.json().then(data => {
  if (!response.ok) throw new Error(data.error || "Could not load configuration");
  data.categories.forEach(category => addCategory(category, data.values, data.fields));
})).catch(error => { message.textContent = error.message; message.className = "error"; });

form.addEventListener("submit", async event => {
  event.preventDefault();
  const values = {};
  for (const [key, input] of Object.entries(fields)) {
    if (input.dataset.type === "boolean") values[key] = input.checked;
    else if (input.dataset.type === "integer") values[key] = input.value === "" ? "" : Number.parseInt(input.value, 10);
    else if (input.dataset.type === "number") values[key] = input.value === "" ? "" : Number(input.value);
    else values[key] = input.value;
  }
  message.textContent = "Saving...";
  message.className = "";
  const response = await fetch("/admin/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
  const result = await response.json();
  message.textContent = response.ok ? "Saved. Restart the server to apply connection changes." : result.error;
  message.className = response.ok ? "success" : "error";
});
