// VisionLLM frontend extension.
// Hides the configuration widgets and replaces them with a compact panel:
// profile selector, model autocomplete, a settings button, and collapsible
// sampling / reasoning / advanced sections. text_prompt, system_prompt,
// pre_prompt and seed stay as native widgets (so seed keeps its
// control_after_generate behaviour).

import { app } from "../../scripts/app.js";
import { VisionAPI, ConfigEvents } from "./vision_api.mjs";
import { getSettingsDialog } from "./vision_settings.mjs";
import { tr } from "./i18n.mjs";

const NODE_NAME = "VisionLLM";

const HIDDEN_WIDGETS = [
  "model",
  "profile",
  "temperature",
  "temperature_enabled",
  "max_tokens",
  "max_tokens_enabled",
  "strip_reasoning",
  "reasoning_tag_open",
  "reasoning_tag_close",
  "image_detail",
  "sleep",
];

function ensureStyles() {
  const id = "vision-llm-css";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = new URL("./vision_llm.css", import.meta.url).href;
  document.head.append(link);
}

function el(tag, className, children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  const list = Array.isArray(children) ? children : [children];
  for (const c of list) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

function getWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}
function widgetValue(node, name, fallback) {
  const w = getWidget(node, name);
  return w ? w.value : fallback;
}
function setWidget(node, name, value) {
  const w = getWidget(node, name);
  if (!w) return;
  w.value = value;
  w.callback?.(value);
}
function hideWidget(node, name) {
  const w = getWidget(node, name);
  if (!w) return;
  w.hidden = true;
  w.computeSize = () => [0, -4];
  if (!w.options) w.options = {};
  w.options.serialize = true;
}

const sharedConfig = { profiles: [], active: null, ready: null };

function applyConfig(data) {
  sharedConfig.profiles = data?.profiles || [];
  sharedConfig.active = data?.active || null;
  sharedConfig.ready = true;
}

async function loadConfig() {
  try {
    const data = await VisionAPI.getConfig();
    applyConfig(data);
  } catch {
    applyConfig(null);
  }
  ConfigEvents.emit(sharedConfig);
  return sharedConfig;
}

function modelsForProfile(profileSelector) {
  const profiles = sharedConfig.profiles || [];
  let prof = null;
  const sel = (profileSelector || "auto").trim();
  if (sel === "auto" || !sel) {
    prof = profiles.find((p) => p.id === sharedConfig.active) || profiles[0];
  } else {
    prof = profiles.find((p) => p.id === sel || p.name === sel) || profiles[0];
  }
  return (prof && prof.models) || [];
}

function buildPanel(node) {
  node.serialize_widgets = true;
  for (const name of HIDDEN_WIDGETS) hideWidget(node, name);

  const root = el("div", "vllm-panel");

  // ---- top row: profile + settings ----
  const profileSelect = el("select", "vllm-select");
  profileSelect.append(el("option", null, tr("自动（活动档案）", "Auto (active profile)")));
  const modelInput = el("input", "vllm-input vllm-model");
  modelInput.type = "text";
  modelInput.placeholder = tr("输入或选择模型", "Enter or select a model");
  const datalistId = `vllm-models-${Math.random().toString(36).slice(2, 8)}`;
  modelInput.setAttribute("list", datalistId);
  const datalist = el("datalist");
  datalist.id = datalistId;
  const settingsBtn = el("button", "vllm-btn vllm-settings", "⚙ " + tr("设置", "Settings"));
  settingsBtn.addEventListener("click", () => {
    getSettingsDialog().open();
  });

  const topRow = el("div", "vllm-row", [
    el("span", "vllm-label", tr("档案", "Profile")),
    profileSelect,
    settingsBtn,
  ]);
  const modelRow = el("div", "vllm-row", [
    el("span", "vllm-label", tr("模型", "Model")),
    modelInput,
  ]);

  // ---- sampling (collapsible) ----
  const tempEnable = el("input", "vllm-check");
  tempEnable.type = "checkbox";
  const tempInput = el("input", "vllm-input vllm-num");
  tempInput.type = "number";
  tempInput.step = "0.05";
  tempInput.min = "0";
  tempInput.max = "2";
  const maxEnable = el("input", "vllm-check");
  maxEnable.type = "checkbox";
  const maxInput = el("input", "vllm-input vllm-num");
  maxInput.type = "number";
  maxInput.min = "1";
  maxInput.step = "1";
  const sampling = el("details", "vllm-details", [
    el("summary", "vllm-summary", tr("生成参数", "Generation")),
    el("div", "vllm-row", [el("label", "vllm-check-label", [tempEnable, tr("指定温度", "Set temperature")]), tempInput]),
    el("div", "vllm-row", [el("label", "vllm-check-label", [maxEnable, tr("限制输出长度", "Limit output tokens")]), maxInput]),
  ]);

  // ---- reasoning (collapsible) ----
  const stripCheck = el("input", "vllm-check");
  stripCheck.type = "checkbox";
  const tagOpen = el("input", "vllm-input vllm-mono");
  const tagClose = el("input", "vllm-input vllm-mono");
  const reasoning = el("details", "vllm-details", [
    el("summary", "vllm-summary", tr("推理内容", "Reasoning")),
    el("div", "vllm-row", [el("label", "vllm-check-label", [stripCheck, tr("从正文分离推理内容", "Separate reasoning from text")])]),
    el("div", "vllm-grid-2", [
      el("div", "vllm-field", [el("span", "vllm-mini-label", tr("开始标签", "Open tag")), tagOpen]),
      el("div", "vllm-field", [el("span", "vllm-mini-label", tr("结束标签", "Close tag")), tagClose]),
    ]),
  ]);

  // ---- advanced (collapsible) ----
  const detailSelect = el("select", "vllm-select");
  for (const v of ["auto", "low", "high"]) detailSelect.append(el("option", { value: v }, v));
  const sleepInput = el("input", "vllm-input vllm-num");
  sleepInput.type = "number";
  sleepInput.min = "0";
  sleepInput.step = "1";
  const advanced = el("details", "vllm-details", [
    el("summary", "vllm-summary", tr("高级设置", "Advanced")),
    el("div", "vllm-row", [el("span", "vllm-label", tr("图像精度", "Image detail")), detailSelect]),
    el("div", "vllm-row", [el("span", "vllm-label", tr("完成后等待", "Sleep (s)")), sleepInput]),
  ]);

  root.append(topRow, modelRow, sampling, reasoning, advanced, datalist);

  // ---- sync helpers ----
  function refreshModelList() {
    const models = modelsForProfile(widgetValue(node, "profile", "auto"));
    datalist.innerHTML = "";
    for (const m of models) datalist.append(el("option", { value: m }));
  }

  function refreshProfileOptions() {
    const profiles = sharedConfig.profiles || [];
    const current = widgetValue(node, "profile", "auto");
    profileSelect.innerHTML = "";
    profileSelect.append(el("option", { value: "auto" }, tr("自动（活动档案）", "Auto (active profile)")));
    for (const p of profiles) {
      const opt = el("option", { value: p.id }, p.name);
      profileSelect.append(opt);
    }
    profileSelect.value = (current && profiles.some((p) => p.id === current)) ? current : "auto";
  }

  function syncFromWidgets() {
    refreshProfileOptions();
    modelInput.value = widgetValue(node, "model", "");
    tempEnable.checked = widgetValue(node, "temperature_enabled", false) !== false;
    tempInput.value = widgetValue(node, "temperature", 1.0);
    tempInput.disabled = !tempEnable.checked;
    maxEnable.checked = widgetValue(node, "max_tokens_enabled", false) !== false;
    maxInput.value = widgetValue(node, "max_tokens", 1024);
    maxInput.disabled = !maxEnable.checked;
    stripCheck.checked = widgetValue(node, "strip_reasoning", true) !== false;
    tagOpen.value = widgetValue(node, "reasoning_tag_open", "");
    tagClose.value = widgetValue(node, "reasoning_tag_close", "");
    detailSelect.value = widgetValue(node, "image_detail", "auto");
    sleepInput.value = widgetValue(node, "sleep", 0);
    refreshModelList();
  }

  // ---- wire events ----
  profileSelect.addEventListener("change", () => {
    setWidget(node, "profile", profileSelect.value || "auto");
    refreshModelList();
  });
  modelInput.addEventListener("input", () => setWidget(node, "model", modelInput.value));
  tempEnable.addEventListener("change", () => {
    setWidget(node, "temperature_enabled", tempEnable.checked);
    tempInput.disabled = !tempEnable.checked;
  });
  tempInput.addEventListener("input", () => {
    const v = parseFloat(tempInput.value);
    if (!Number.isNaN(v)) setWidget(node, "temperature", v);
  });
  maxEnable.addEventListener("change", () => {
    setWidget(node, "max_tokens_enabled", maxEnable.checked);
    maxInput.disabled = !maxEnable.checked;
  });
  maxInput.addEventListener("input", () => {
    const v = parseInt(maxInput.value, 10);
    if (!Number.isNaN(v)) setWidget(node, "max_tokens", v);
  });
  stripCheck.addEventListener("change", () => setWidget(node, "strip_reasoning", stripCheck.checked));
  tagOpen.addEventListener("input", () => setWidget(node, "reasoning_tag_open", tagOpen.value));
  tagClose.addEventListener("input", () => setWidget(node, "reasoning_tag_close", tagClose.value));
  detailSelect.addEventListener("change", () => setWidget(node, "image_detail", detailSelect.value));
  sleepInput.addEventListener("input", () => {
    const v = parseInt(sleepInput.value, 10);
    if (!Number.isNaN(v)) setWidget(node, "sleep", v);
  });

  node._vllmRefresh = () => {
    syncFromWidgets();
    requestLayout(true);
  };

  // keep config in sync (profiles/models may change in the settings dialog)
  const unsub = ConfigEvents.on((config) => {
    if (config) applyConfig(config);
    refreshProfileOptions();
    refreshModelList();
  });
  if (!sharedConfig.ready) loadConfig();

  // Off-screen DOM widgets can temporarily report zero height. Retain the last
  // valid measurement so moving the node out of view cannot collapse its UI.
  let cachedPanelHeight = 150;
  function panelHeight() {
    const measured = Math.ceil(root.scrollHeight || 0);
    if (measured >= 120) cachedPanelHeight = measured;
    return cachedPanelHeight;
  }
  const widget = node.addDOMWidget("vision_llm_panel", "vision-llm", root, {
    serialize: false,
    getMinHeight: panelHeight,
    getMaxHeight: panelHeight,
  });
  // Keep a stable slot in widgets_values (constant placeholder) so the native
  // widgets that follow cannot shift into a sparse value on save/load/resize.
  // The actual UI state lives in the hidden serialized widgets, not here.
  widget.serialize = true;
  widget.serializeValue = () => "vllm-panel-v1";

  // place the panel above the native text widgets
  const widgetIndex = node.widgets.indexOf(widget);
  if (widgetIndex > 0) {
    node.widgets.splice(widgetIndex, 1);
    node.widgets.unshift(widget);
  }

  let layoutFrame = 0;
  function requestLayout(grow = false) {
    cancelAnimationFrame(layoutFrame);
    layoutFrame = requestAnimationFrame(() => {
      panelHeight();
      if (grow) {
        const computed = node.computeSize?.();
        if (computed) {
          const width = Math.max(node.size?.[0] || 0, computed[0], 340);
          const height = Math.max(node.size?.[1] || 0, computed[1]);
          if (width > (node.size?.[0] || 0) + 1 || height > (node.size?.[1] || 0) + 1) {
            node.setSize([width, height]);
          }
        }
      }
      app.graph?.setDirtyCanvas?.(true, true);
    });
  }

  // Opening a section may require more room. Closing it never shrinks the node,
  // preserving the user's chosen size and preventing resize feedback loops.
  for (const det of [sampling, reasoning, advanced]) {
    det.addEventListener("toggle", () => requestLayout(det.open));
  }

  const onRemoved = node.onRemoved;
  node.onRemoved = function () {
    cancelAnimationFrame(layoutFrame);
    unsub();
    onRemoved?.apply(this, arguments);
  };

  syncFromWidgets();
  requestAnimationFrame(() => requestLayout(true));
}

app.registerExtension({
  name: "Comfy.VisionLLM",
  init() {
    ensureStyles();
    loadConfig();
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      buildPanel(this);
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      requestAnimationFrame(() => this._vllmRefresh?.());
    };

    const onAdded = nodeType.prototype.onAdded;
    nodeType.prototype.onAdded = function () {
      onAdded?.apply(this, arguments);
      requestAnimationFrame(() => this._vllmRefresh?.());
    };
  },
});
