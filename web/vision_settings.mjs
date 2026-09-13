// API settings dialog for VisionLLM. A shared modal that manages profiles
// (proxy + key + model list), tests connections, and fetches model lists.
// The API key field is write-only: it shows a masked hint and only sends a
// value when the user actually types a new key.

import { VisionAPI, ConfigEvents } from "./vision_api.mjs";
import { tr } from "./i18n.mjs";

function h(tag, props = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") {
      el.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (k in el) {
      try { el[k] = v; } catch { el.setAttribute(k, v); }
    } else el.setAttribute(k, v);
  }
  const kids = Array.isArray(children) ? children : [children];
  for (const c of kids) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

function toast(msg, type = "info") {
  const colors = { info: "#3b82f6", success: "#10b981", error: "#ef4444" };
  const t = h("div", { class: "vllm-toast vllm-toast-" + type, html: String(msg) });
  document.body.append(t);
  requestAnimationFrame(() => t.classList.add("vllm-toast-show"));
  setTimeout(() => {
    t.classList.remove("vllm-toast-show");
    setTimeout(() => t.remove(), 250);
  }, 2600);
}

let shared = null;
export function getSettingsDialog() {
  if (!shared) shared = new SettingsDialog();
  return shared;
}

class SettingsDialog {
  constructor() {
    this.root = null;
    this.config = { profiles: [], active: null };
    this.editingId = null;
    this._build();
  }

  open() {
    this.root.classList.add("vllm-open");
    document.body.classList.add("vllm-modal-open");
    this.load();
  }
  close() {
    this.root.classList.remove("vllm-open");
    document.body.classList.remove("vllm-modal-open");
  }

  _build() {
    const overlay = h("div", { class: "vllm-overlay" });
    overlay.addEventListener("mousedown", (e) => {
      if (e.target === overlay) this.close();
    });
    const win = h("div", { class: "vllm-window" });
    win.append(
      h("div", { class: "vllm-header" }, [
        h("div", { class: "vllm-title" }, [h("span", { class: "vllm-title-icon" }, "🔑"), h("span", {}, tr("API 设置", "API Settings"))]),
        h("button", { class: "vllm-icon-btn", title: "关闭", onclick: () => this.close() }, "✕"),
      ]),
      h("div", { class: "vllm-body" }, [this._buildSidebar(), this._buildEditor()])
    );
    overlay.append(win);
    this.root = overlay;
    document.body.append(overlay);
  }

  _buildSidebar() {
    this.sidebar = h("div", { class: "vllm-sidebar" });
    return this.sidebar;
  }

  _buildEditor() {
    this.editor = h("div", { class: "vllm-editor" });
    return this.editor;
  }

  async load() {
    try {
      this.config = await VisionAPI.getConfig();
      ConfigEvents.emit(this.config);
    } catch (e) {
      toast(tr("加载配置失败: ", "Load failed: ") + e.message, "error");
    }
    this._renderSidebar();
    this._renderEditor();
  }

  _renderSidebar() {
    const root = this.sidebar;
    root.innerHTML = "";
    root.append(h("div", { class: "vllm-side-title" }, tr("档案", "Profiles")));
    const list = h("div", { class: "vllm-profile-list" });
    const profiles = this.config.profiles || [];
    if (!profiles.length) {
      list.append(h("div", { class: "vllm-empty" }, tr("暂无档案，点击下方新建", "No profiles yet. Create one below.")));
    }
    for (const p of profiles) {
      const active = this.config.active === p.id;
      const item = h("div", { class: "vllm-profile" + (active ? " vllm-active" : "") + (this.editingId === p.id ? " vllm-editing" : "") }, [
        h("span", { class: "vllm-profile-name", title: p.name, onclick: () => this._edit(p.id) }, p.name || tr("未命名", "Untitled")),
        p.has_key ? h("span", { class: "vllm-key-dot", title: tr("已设置密钥", "Key set") }, "🔒") : h("span", { class: "vllm-key-dot vllm-key-missing", title: tr("未设置密钥", "No key") }, "🔓"),
        h("button", { class: "vllm-mini", title: active ? tr("当前活动", "Active") : tr("设为活动", "Set active"), onclick: (e) => { e.stopPropagation(); this._setActive(p.id); } }, active ? "●" : "○"),
        h("button", { class: "vllm-mini", title: tr("删除", "Delete"), onclick: (e) => { e.stopPropagation(); this._delete(p.id); } }, "✕"),
      ]);
      item.addEventListener("click", () => this._edit(p.id));
      list.append(item);
    }
    root.append(list);
    root.append(h("button", { class: "vllm-new-profile", onclick: () => this._newProfile() }, "+ " + tr("新建档案", "New profile")));
  }

  _renderEditor() {
    const root = this.editor;
    root.innerHTML = "";
    const p = (this.config.profiles || []).find((x) => x.id === this.editingId) || null;
    if (!p) {
      root.append(h("div", { class: "vllm-empty-full" }, [
        h("div", { class: "vllm-empty-icon" }, "🛠"),
        h("div", {}, tr("选择左侧档案编辑，或新建一个", "Select a profile on the left, or create a new one.")),
      ]));
      return;
    }

    this.form = {
      name: h("input", { class: "vllm-input", type: "text", value: p.name || "", placeholder: tr("档案名称", "Profile name") }),
      baseUrl: h("input", { class: "vllm-input", type: "text", value: p.base_url || "", placeholder: "https://api.openai.com/v1" }),
      proxyMode: h("select", { class: "vllm-input" }, [
        h("option", { value: "direct" }, tr("直连（推荐）", "Direct (recommended)")),
        h("option", { value: "system" }, tr("系统环境代理", "System environment proxy")),
        h("option", { value: "custom" }, tr("自定义代理", "Custom proxy")),
      ]),
      proxyUrl: h("input", { class: "vllm-input", type: "text", value: p.proxy_url || "", placeholder: "http://127.0.0.1:7897" }),
      apiKey: h("input", { class: "vllm-input", type: "password", value: "", placeholder: p.has_key ? (tr("留空保持不变 (", "Leave blank to keep (") + (p.api_key_masked || "")) + ")" : tr("输入 API 密钥", "Enter API key") }),
      models: h("textarea", { class: "vllm-input vllm-textarea", rows: 6, placeholder: tr("每行一个模型名", "One model per line") }),
    };
    this.form.proxyMode.value = p.proxy_mode || "direct";
    const syncProxyInput = () => {
      this.form.proxyUrl.disabled = this.form.proxyMode.value !== "custom";
    };
    this.form.proxyMode.addEventListener("change", syncProxyInput);
    syncProxyInput();
    this.form.models.value = (p.models || []).join("\n");

    const actions = h("div", { class: "vllm-form-actions" }, [
      h("button", { class: "vllm-btn", onclick: () => this._test(p) }, tr("测试模型接口", "Test models endpoint")),
      h("button", { class: "vllm-btn", onclick: () => this._fetchModels(p) }, tr("拉取模型", "Fetch models")),
      h("span", { class: "vllm-spacer" }),
      h("button", { class: "vllm-btn vllm-btn-danger", onclick: () => this._delete(p.id) }, tr("删除", "Delete")),
      h("button", { class: "vllm-btn vllm-btn-primary", onclick: () => this._save(p) }, tr("保存", "Save")),
    ]);

    root.append(
      h("div", { class: "vllm-field" }, [h("label", {}, tr("名称", "Name")), this.form.name]),
      h("div", { class: "vllm-field" }, [h("label", {}, tr("接口地址 (Base URL)", "Base URL")), this.form.baseUrl, h("div", { class: "vllm-hint" }, tr("需包含 /v1，如 https://api.openai.com/v1", "Include /v1, e.g. https://api.openai.com/v1"))]),
      h("div", { class: "vllm-field" }, [
        h("label", {}, tr("网络连接", "Network")),
        this.form.proxyMode,
        h("div", { class: "vllm-hint" }, tr("直连可避免其他插件全局注入代理", "Direct mode prevents other extensions from injecting a global proxy")),
      ]),
      h("div", { class: "vllm-field vllm-proxy-field" }, [
        h("label", {}, tr("代理地址", "Proxy URL")),
        this.form.proxyUrl,
      ]),
      h("div", { class: "vllm-field" }, [h("label", {}, tr("API 密钥", "API key")), this.form.apiKey, h("div", { class: "vllm-hint" }, p.has_key ? (tr("当前: ", "Current: ") + (p.api_key_masked || "")) : tr("未设置", "Not set"))]),
      h("div", { class: "vllm-field" }, [h("label", {}, tr("模型列表", "Models")), this.form.models, h("div", { class: "vllm-hint" }, tr("用于节点下拉候选；可手动编辑", "Used as node dropdown candidates; editable"))]),
      actions,
    );
  }

  // ---------- profile actions ----------
  _newProfile() {
    this.editingId = "__new__";
    this.config.profiles = this.config.profiles || [];
    // a temp placeholder so the editor shows an empty form
    const temp = { id: "__new__", name: "", base_url: "", has_key: false, api_key_masked: "", proxy_mode: "direct", proxy_url: "", models: [] };
    this.config.profiles = [...(this.config.profiles || []), temp];
    this._renderSidebar();
    this._renderEditor();
    setTimeout(() => this.form?.name?.focus(), 50);
  }

  _edit(id) {
    this.editingId = id;
    // discard a temp "new" placeholder if switching away
    if (this.config.profiles?.some((p) => p.id === "__new__")) {
      this.config.profiles = this.config.profiles.filter((p) => p.id !== "__new__");
    }
    this._renderSidebar();
    this._renderEditor();
  }

  async _save(p) {
    const f = this.form;
    const name = f.name.value.trim();
    const baseUrl = f.baseUrl.value.trim();
    if (!name) { toast(tr("请填写名称", "Name is required"), "error"); return; }
    if (!baseUrl) { toast(tr("请填写接口地址", "Base URL is required"), "error"); return; }
    const models = f.models.value.split("\n").map((s) => s.trim()).filter(Boolean);
    const payload = { name, base_url: baseUrl, proxy_mode: f.proxyMode.value, proxy_url: f.proxyUrl.value.trim(), models };
    // api_key: only send when the user typed something (a real new key)
    const typedKey = f.apiKey.value;
    if (typedKey) payload.api_key = typedKey;
    if (p.id && p.id !== "__new__") payload.id = p.id;
    try {
      const data = await VisionAPI.upsertProfile(payload);
      this.config = data;
      this.editingId = data.profiles?.find((x) => x.name === name)?.id || null;
      ConfigEvents.emit(data);
      this._renderSidebar();
      this._renderEditor();
      toast(tr("已保存", "Saved"), "success");
    } catch (e) {
      toast(tr("保存失败: ", "Save failed: ") + e.message, "error");
    }
  }

  async _delete(id) {
    if (id === "__new__") {
      this.editingId = null;
      this.config.profiles = (this.config.profiles || []).filter((p) => p.id !== "__new__");
      this._renderSidebar();
      this._renderEditor();
      return;
    }
    if (!confirm(tr("确定删除该档案？", "Delete this profile?"))) return;
    try {
      this.config = await VisionAPI.deleteProfile(id);
      if (this.editingId === id) this.editingId = null;
      ConfigEvents.emit(this.config);
      this._renderSidebar();
      this._renderEditor();
      toast(tr("已删除", "Deleted"), "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async _setActive(id) {
    try {
      this.config = await VisionAPI.setActive(id);
      ConfigEvents.emit(this.config);
      this._renderSidebar();
      toast(tr("已设为活动", "Set active"), "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async _test(p) {
    const f = this.form;
    const baseUrl = f.baseUrl.value.trim() || p.base_url;
    const typedKey = f.apiKey.value;
    const payload = { profile: p.id && p.id !== "__new__" ? p.id : undefined, base_url: baseUrl, api_key: typedKey || undefined, proxy_mode: f.proxyMode.value, proxy_url: f.proxyUrl.value.trim() };
    toast(tr("测试中…", "Testing…"), "info");
    try {
      const r = await VisionAPI.test(payload);
      if (r.ok) {
        toast(tr("模型接口可用，共 ", "Models endpoint connected, ") + (r.models?.length || 0) + tr(" 个模型", " models"), "success");
      } else {
        toast(tr("连接失败: ", "Failed: ") + (r.error || ""), "error");
      }
    } catch (e) {
      toast(tr("连接失败: ", "Failed: ") + e.message, "error");
    }
  }

  async _fetchModels(p) {
    const f = this.form;
    const baseUrl = f.baseUrl.value.trim() || p.base_url;
    const typedKey = f.apiKey.value;
    const payload = { profile: p.id && p.id !== "__new__" ? p.id : undefined, base_url: baseUrl, api_key: typedKey || undefined, proxy_mode: f.proxyMode.value, proxy_url: f.proxyUrl.value.trim() };
    toast(tr("拉取模型列表…", "Fetching models…"), "info");
    try {
      const r = await VisionAPI.test(payload);
      if (r.ok && Array.isArray(r.models)) {
        const existing = f.models.value.split("\n").map((s) => s.trim()).filter(Boolean);
        const merged = Array.from(new Set([...r.models, ...existing]));
        f.models.value = merged.join("\n");
        toast(tr("已拉取 ", "Fetched ") + r.models.length + tr(" 个模型", " models"), "success");
      } else {
        toast(tr("拉取失败: ", "Failed: ") + (r?.error || ""), "error");
      }
    } catch (e) {
      toast(tr("拉取失败: ", "Failed: ") + e.message, "error");
    }
  }
}
