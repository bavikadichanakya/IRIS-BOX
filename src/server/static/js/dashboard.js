/**
 * IRIS-BOX Control Center (Air-Gapped Dashboard Engine)
 * Strictly local vanilla JavaScript with zero external CDN dependencies.
 */

(function () {
  const STORAGE_KEY = "iris_master_token";
  let pollInterval = null;

  // DOM Elements
  const tokenInput = document.getElementById("master-token-input");
  const saveTokenBtn = document.getElementById("save-token-btn");
  const heartbeatBadge = document.getElementById("heartbeat-status");
  const heartbeatDot = document.getElementById("heartbeat-dot");
  const heartbeatText = document.getElementById("heartbeat-text");

  // Metrics Elements
  const metricRequests = document.getElementById("metric-total-requests");
  const metricSuccessRate = document.getElementById("metric-success-rate");
  const metricLatency = document.getElementById("metric-avg-latency");
  const metricTools = document.getElementById("metric-tool-invocations");

  // Subsystem Cards Container
  const subsystemGrid = document.getElementById("subsystem-grid");

  // Plans Container
  const plansContainer = document.getElementById("plans-container");
  const plansCountBadge = document.getElementById("plans-count-badge");

  // Skills Container
  const skillsContainer = document.getElementById("skills-container");
  const skillsCountBadge = document.getElementById("skills-count-badge");

  // Memory Elements
  const prefsTableBody = document.getElementById("prefs-table-body");
  const prefKeyInput = document.getElementById("pref-key-input");
  const prefValInput = document.getElementById("pref-val-input");
  const prefCatInput = document.getElementById("pref-cat-input");
  const addPrefBtn = document.getElementById("add-pref-btn");
  const factsList = document.getElementById("facts-list");

  // Toast System
  const toastContainer = document.getElementById("toast-container");

  function showToast(message, type = "success") {
    if (!toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(100%)";
      toast.style.transition = "all 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  function getStoredToken() {
    return localStorage.getItem(STORAGE_KEY) || "";
  }

  function setStoredToken(token) {
    if (token) {
      localStorage.setItem(STORAGE_KEY, token.trim());
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  async function apiFetch(url, options = {}) {
    const token = getStoredToken();
    const headers = {
      ...(options.headers || {}),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
      headers["X-API-Key"] = token;
    }
    if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    try {
      const response = await fetch(url, { ...options, headers });
      if (response.status === 401) {
        showToast("Authentication required or invalid token.", "error");
      }
      return response;
    } catch (err) {
      console.warn("API request failed:", url, err);
      throw err;
    }
  }

  // 1. Live Telemetry & Subsystem Matrix
  async function fetchStatusAndTelemetry() {
    const startTime = performance.now();
    try {
      const res = await apiFetch("/api/dashboard/status");
      const elapsed = Math.round(performance.now() - startTime);

      if (!res.ok) {
        setHeartbeatOffline();
        return;
      }

      const data = await res.json();
      setHeartbeatOnline(elapsed);

      // Render Telemetry
      if (data.metrics) {
        if (metricRequests) metricRequests.textContent = data.metrics.total_requests ?? "0";
        if (metricSuccessRate) metricSuccessRate.textContent = `${data.metrics.success_rate ?? 100}%`;
        if (metricLatency) metricLatency.textContent = `${data.metrics.avg_latency_ms ?? 0} ms`;
        if (metricTools) metricTools.textContent = data.metrics.tool_invocations ?? "0";
      }

      // Render Subsystem Matrix
      if (data.subsystems) {
        renderSubsystems(data.subsystems);
      }
    } catch (err) {
      setHeartbeatOffline();
    }
  }

  function setHeartbeatOnline(latencyMs) {
    if (!heartbeatDot || !heartbeatText) return;
    heartbeatDot.className = "pulse-dot";
    heartbeatText.textContent = `ONLINE • ${latencyMs}ms`;
  }

  function setHeartbeatOffline() {
    if (!heartbeatDot || !heartbeatText) return;
    heartbeatDot.className = "pulse-dot offline";
    heartbeatText.textContent = "DISCONNECTED";
  }

  function renderSubsystems(subsystems) {
    if (!subsystemGrid) return;
    subsystemGrid.innerHTML = "";

    const keys = ["llm", "wakeword", "stt", "tts", "database", "fleet"];
    keys.forEach((key) => {
      const sub = subsystems[key];
      if (!sub) return;

      const card = document.createElement("div");
      card.className = "subsystem-card";

      const statusClass = (sub.status || "HEALTHY").toLowerCase();
      const statusLabel = sub.status || "HEALTHY";

      let metaDetail = `${sub.latency_ms || 0} ms latency`;
      if (key === "fleet" && typeof sub.connected_count === "number") {
        metaDetail = `${sub.connected_count} device(s) online`;
      }

      card.innerHTML = `
        <div class="subsystem-header">
          <div>
            <div class="subsystem-name">${escapeHtml(sub.name || key)}</div>
            <div class="subsystem-component">${escapeHtml(sub.component || "")}</div>
          </div>
          <span class="status-badge ${statusClass}">${statusLabel}</span>
        </div>
        <div class="subsystem-meta">
          <span>${escapeHtml(sub.message || "Ready")}</span>
          <span class="latency-indicator">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            ${metaDetail}
          </span>
        </div>
      `;
      subsystemGrid.appendChild(card);
    });
  }

  // 2. Interactive Approval Center
  async function fetchPlans() {
    if (!plansContainer) return;
    try {
      const res = await apiFetch("/api/plans/active");
      if (!res.ok) {
        plansContainer.innerHTML = `<div class="empty-state">Unable to load plans (Auth token required)</div>`;
        return;
      }
      const data = await res.json();
      const plans = data.plans || [];

      if (plansCountBadge) {
        plansCountBadge.textContent = `${plans.length} Staged`;
      }

      if (plans.length === 0) {
        plansContainer.innerHTML = `<div class="empty-state">No pending plans requiring review. System ready.</div>`;
        return;
      }

      plansContainer.innerHTML = "";
      plans.forEach((plan) => {
        const planCard = document.createElement("div");
        planCard.className = "plan-card";

        const stepsHtml = (plan.steps || [])
          .map((step) => {
            const permClass = (step.permission_level || "public").toLowerCase();
            const paramsStr = JSON.stringify(step.parameters || {});
            return `
              <div class="plan-step-item">
                <span class="step-num">#${step.step_id}</span>
                <div class="step-body">
                  <div class="step-desc">
                    <strong>[${escapeHtml(step.tool_name)}]</strong> ${escapeHtml(step.description || "")}
                  </div>
                  <div class="step-params">Params: ${escapeHtml(paramsStr)}</div>
                </div>
                <span class="permission-badge ${permClass}">${step.permission_level}</span>
              </div>
            `;
          })
          .join("");

        planCard.innerHTML = `
          <div class="plan-header">
            <div>
              <span class="plan-id">${escapeHtml(plan.plan_id)}</span>
              <div class="plan-prompt">${escapeHtml(plan.user_prompt || "Multi-step Task")}</div>
            </div>
            <span class="status-badge degraded">${plan.status}</span>
          </div>
          <div class="plan-steps-container">
            ${stepsHtml}
          </div>
          <div class="plan-actions">
            <button class="btn-success approve-plan-btn" data-id="${plan.plan_id}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              Approve Plan
            </button>
            <button class="btn-danger reject-plan-btn" data-id="${plan.plan_id}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
              Reject
            </button>
          </div>
        `;

        plansContainer.appendChild(planCard);
      });

      // Bind actions
      document.querySelectorAll(".approve-plan-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const planId = btn.getAttribute("data-id");
          await approvePlan(planId);
        });
      });

      document.querySelectorAll(".reject-plan-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const planId = btn.getAttribute("data-id");
          await rejectPlan(planId);
        });
      });
    } catch (err) {
      plansContainer.innerHTML = `<div class="empty-state">Failed to fetch plans. Check connection.</div>`;
    }
  }

  async function approvePlan(planId) {
    try {
      const res = await apiFetch(`/api/plans/${planId}/approve`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (res.ok) {
        showToast(`Plan ${planId} approved successfully.`);
        await fetchPlans();
      } else {
        const err = await res.json();
        showToast(`Approval failed: ${err.detail || "Error"}`, "error");
      }
    } catch (e) {
      showToast(`Network error approving plan.`, "error");
    }
  }

  async function rejectPlan(planId) {
    try {
      const res = await apiFetch(`/api/plans/${planId}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: "User rejected from dashboard" }),
      });
      if (res.ok) {
        showToast(`Plan ${planId} rejected.`);
        await fetchPlans();
      } else {
        const err = await res.json();
        showToast(`Reject failed: ${err.detail || "Error"}`, "error");
      }
    } catch (e) {
      showToast(`Network error rejecting plan.`, "error");
    }
  }

  // 3. Skills Explorer
  async function fetchSkills() {
    if (!skillsContainer) return;
    try {
      const res = await apiFetch("/api/skills");
      if (!res.ok) {
        skillsContainer.innerHTML = `<div class="empty-state">Unable to load skills (Auth token required)</div>`;
        return;
      }
      const data = await res.json();
      const skills = data.skills || [];

      if (skillsCountBadge) {
        skillsCountBadge.textContent = `${skills.length} Loaded`;
      }

      skillsContainer.innerHTML = "";
      skills.forEach((skill) => {
        const skillCard = document.createElement("div");
        skillCard.className = "skill-card";

        const netTag = skill.requires_network
          ? `<span class="tag-badge network">REQUIRES-NETWORK</span>`
          : `<span class="tag-badge offline-only">OFFLINE-ONLY</span>`;

        const permClass = (skill.default_permission_level || "public").toLowerCase();

        skillCard.innerHTML = `
          <div class="skill-card-top">
            <div>
              <div class="skill-title">${escapeHtml(skill.name)}</div>
              <div class="skill-desc">${escapeHtml(skill.description || "")}</div>
            </div>
            <span class="permission-badge ${permClass}">${skill.default_permission_level}</span>
          </div>
          <div class="skill-tags">
            <span class="tag-badge">${escapeHtml(skill.category || "GENERAL")}</span>
            <span class="tag-badge">v${escapeHtml(skill.version || "1.0.0")}</span>
            ${netTag}
          </div>
          <div class="skill-health-row">
            <span class="skill-health-status" id="health-status-${skill.name}">Health: Unchecked</span>
            <button class="btn-secondary check-skill-health-btn" data-name="${skill.name}">
              Check Health
            </button>
          </div>
        `;
        skillsContainer.appendChild(skillCard);
      });

      // Bind health check buttons
      document.querySelectorAll(".check-skill-health-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const name = btn.getAttribute("data-name");
          await checkSkillHealth(name);
        });
      });
    } catch (err) {
      skillsContainer.innerHTML = `<div class="empty-state">Failed to load skills.</div>`;
    }
  }

  async function checkSkillHealth(name) {
    const statusElem = document.getElementById(`health-status-${name}`);
    if (statusElem) statusElem.textContent = "Probing...";

    try {
      const res = await apiFetch(`/api/skills/${name}/health`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (statusElem) {
          statusElem.textContent = `${data.status} (${data.latency_ms}ms)`;
          statusElem.style.color = data.status === "HEALTHY" ? "var(--emerald-neon)" : "var(--amber-neon)";
        }
        showToast(`Skill '${name}': ${data.status} (${data.latency_ms}ms)`);
      } else {
        if (statusElem) statusElem.textContent = "Check Failed";
        showToast(`Failed to check health for ${name}`, "error");
      }
    } catch (e) {
      if (statusElem) statusElem.textContent = "Error";
      showToast(`Network error checking skill health`, "error");
    }
  }

  // 4. Memory & Preferences Inspector
  async function fetchPreferences() {
    if (!prefsTableBody) return;
    try {
      const res = await apiFetch("/api/memory/preferences");
      if (!res.ok) {
        prefsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Auth token required to load preferences</td></tr>`;
        return;
      }
      const data = await res.json();
      const items = data.items || [];

      if (items.length === 0) {
        prefsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">No explicit preferences stored.</td></tr>`;
        return;
      }

      prefsTableBody.innerHTML = "";
      items.forEach((item) => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td><strong>${escapeHtml(item.key)}</strong></td>
          <td><code>${escapeHtml(JSON.stringify(item.value))}</code></td>
          <td><span class="tag-badge">${escapeHtml(item.category || "general")}</span></td>
          <td style="text-align: right;">
            <button class="btn-danger delete-pref-btn" data-key="${item.key}" style="padding: 4px 8px; font-size: 0.72rem;">
              Delete
            </button>
          </td>
        `;
        prefsTableBody.appendChild(row);
      });

      document.querySelectorAll(".delete-pref-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const key = btn.getAttribute("data-key");
          await deletePreference(key);
        });
      });
    } catch (err) {
      prefsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Failed to load preferences</td></tr>`;
    }
  }

  async function savePreference() {
    const key = (prefKeyInput.value || "").trim();
    const val = (prefValInput.value || "").trim();
    const cat = (prefCatInput.value || "").trim() || "general";

    if (!key || !val) {
      showToast("Key and Value are required.", "error");
      return;
    }

    let parsedVal = val;
    try {
      parsedVal = JSON.parse(val);
    } catch (e) {
      // Keep as string
    }

    try {
      const res = await apiFetch("/api/memory/preferences", {
        method: "POST",
        body: JSON.stringify({ key, value: parsedVal, category: cat }),
      });
      if (res.ok) {
        showToast(`Preference '${key}' saved.`);
        prefKeyInput.value = "";
        prefValInput.value = "";
        await fetchPreferences();
      } else {
        showToast("Failed to save preference.", "error");
      }
    } catch (e) {
      showToast("Network error saving preference.", "error");
    }
  }

  async function deletePreference(key) {
    try {
      const res = await apiFetch(`/api/memory/preferences/${encodeURIComponent(key)}`, {
        method: "DELETE",
      });
      if (res.ok) {
        showToast(`Deleted preference '${key}'.`);
        await fetchPreferences();
      } else {
        showToast(`Failed to delete preference '${key}'.`, "error");
      }
    } catch (e) {
      showToast(`Network error deleting preference.`, "error");
    }
  }

  async function fetchFacts() {
    if (!factsList) return;
    try {
      const res = await apiFetch("/api/memory/facts");
      if (!res.ok) {
        factsList.innerHTML = `<div class="empty-state">Auth token required to load facts</div>`;
        return;
      }
      const data = await res.json();
      const facts = data.facts || [];

      if (facts.length === 0) {
        factsList.innerHTML = `<div class="empty-state">No model-inferred facts observed yet.</div>`;
        return;
      }

      factsList.innerHTML = "";
      facts.forEach((fact) => {
        const factElem = document.createElement("div");
        factElem.className = "fact-item";
        const pct = Math.round((fact.confidence || 1.0) * 100);

        factElem.innerHTML = `
          <div class="fact-content">
            <div class="fact-text">${escapeHtml(fact.fact)}</div>
            <div class="fact-meta">
              <span class="confidence-badge">${pct}% Conf</span>
              <span>Observed: ${new Date((fact.timestamp || Date.now() / 1000) * 1000).toLocaleTimeString()}</span>
              ${fact.confirmed ? '<span style="color:var(--emerald-neon)">✓ Confirmed</span>' : ""}
            </div>
          </div>
          <div style="display: flex; gap: 6px;">
            ${
              !fact.confirmed
                ? `<button class="btn-success confirm-fact-btn" data-id="${fact.id}">Confirm</button>`
                : ""
            }
            <button class="btn-danger delete-fact-btn" data-id="${fact.id}">Delete</button>
          </div>
        `;
        factsList.appendChild(factElem);
      });

      document.querySelectorAll(".confirm-fact-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-id");
          await confirmFact(id);
        });
      });

      document.querySelectorAll(".delete-fact-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-id");
          await deleteFact(id);
        });
      });
    } catch (err) {
      factsList.innerHTML = `<div class="empty-state">Failed to load facts.</div>`;
    }
  }

  async function confirmFact(id) {
    try {
      const res = await apiFetch(`/api/memory/facts/${id}/confirm`, { method: "POST" });
      if (res.ok) {
        showToast("Fact confirmed and promoted.");
        await fetchFacts();
      } else {
        showToast("Failed to confirm fact.", "error");
      }
    } catch (e) {
      showToast("Network error confirming fact.", "error");
    }
  }

  async function deleteFact(id) {
    try {
      const res = await apiFetch(`/api/memory/facts/${id}`, { method: "DELETE" });
      if (res.ok) {
        showToast("Fact deleted.");
        await fetchFacts();
      } else {
        showToast("Failed to delete fact.", "error");
      }
    } catch (e) {
      showToast("Network error deleting fact.", "error");
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initialization
  async function init() {
    // 1. Setup Token Field
    const savedToken = getStoredToken();
    if (tokenInput && savedToken) {
      tokenInput.value = savedToken;
    }

    if (saveTokenBtn && tokenInput) {
      saveTokenBtn.addEventListener("click", () => {
        setStoredToken(tokenInput.value);
        showToast("Master Auth Token saved to localStorage.");
        refreshAll();
      });
      tokenInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          setStoredToken(tokenInput.value);
          showToast("Master Auth Token saved to localStorage.");
          refreshAll();
        }
      });
    }

    // 2. Setup Memory Form
    if (addPrefBtn) {
      addPrefBtn.addEventListener("click", savePreference);
    }

    // 3. Initial Load
    await refreshAll();

    // 4. Polling loop every 3.5 seconds
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async () => {
      await fetchStatusAndTelemetry();
      await fetchPlans();
    }, 3500);
  }

  async function refreshAll() {
    await fetchStatusAndTelemetry();
    await fetchPlans();
    await fetchSkills();
    await fetchPreferences();
    await fetchFacts();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
