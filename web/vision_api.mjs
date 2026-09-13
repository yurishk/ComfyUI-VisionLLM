// API client for the VisionLLM backend routes (/visionllm/*).

import { api } from "../../scripts/api.js";

const PREFIX = "/visionllm";

async function call(path, options = {}) {
  const resp = await api.fetchApi(`${PREFIX}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await resp.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!resp.ok) {
    const msg = (data && data.error) || `HTTP ${resp.status}`;
    const err = new Error(msg);
    err.data = data;
    throw err;
  }
  return data;
}

export const VisionAPI = {
  getConfig() {
    return call("/config").then((r) => r.data);
  },
  saveConfig(config) {
    return call("/config", {
      method: "POST",
      body: JSON.stringify(config),
    }).then((r) => r.data);
  },
  upsertProfile(profile) {
    return call("/profile", {
      method: "POST",
      body: JSON.stringify(profile),
    }).then((r) => r.data);
  },
  deleteProfile(id) {
    return call("/profile/delete", {
      method: "POST",
      body: JSON.stringify({ id }),
    }).then((r) => r.data);
  },
  setActive(id) {
    return call("/active", {
      method: "POST",
      body: JSON.stringify({ id }),
    }).then((r) => r.data);
  },
  test(payload) {
    return call("/test", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listModels(profile) {
    const q = profile ? `?profile=${encodeURIComponent(profile)}` : "";
    return call(`/models${q}`);
  },
};

// Tiny in-memory event bus so node panels + the settings dialog stay in sync.
const listeners = new Set();
export const ConfigEvents = {
  on(cb) {
    listeners.add(cb);
    return () => listeners.delete(cb);
  },
  emit(config = null) {
    listeners.forEach((cb) => {
      try {
        cb(config);
      } catch (e) {
        console.error("config listener error", e);
      }
    });
  },
};
