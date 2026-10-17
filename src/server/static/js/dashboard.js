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

  // Project Operator Elements
  const operatorProjectPath = document.getElementById("operator-project-path");
  const operatorTestCommand = document.getElementById("operator-test-command");
  const operatorDiagnoseBtn = document.getElementById("operator-diagnose-btn");
  const operatorSnapshotBtn = document.getElementById("operator-snapshot-btn");
  const operatorIntelContainer = document.getElementById("operator-intel-container");
  const operatorInfoPills = document.getElementById("operator-info-pills");
  const operatorDiagnosticContainer = document.getElementById("operator-diagnostic-container");
  const diagnosticSummaryBadge = document.getElementById("diagnostic-summary-badge");
  const diagnosticOutputText = document.getElementById("diagnostic-output-text");

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

  function renderDiffHtml(diffText) {
    if (!diffText) return "";
    const lines = diffText.split("\n");
    const formatted = lines.map(line => {
      let cls = "info";
      if (line.startsWith("+") && !line.startsWith("+++")) {
        cls = "add";
      } else if (line.startsWith("-") && !line.startsWith("---")) {
        cls = "del";
      } else if (line.startsWith("@@")) {
        cls = "hunk";
      }
      return `<div class="diff-line ${cls}">${escapeHtml(line)}</div>`;
    }).join("");

    return `
      <div class="diff-preview-container">
        <div class="diff-header">
          <span>Unified Diff Preview</span>
          <span style="color: var(--cyan-neon);">Surgical Patch</span>
        </div>
        <div class="diff-content">${formatted}</div>
      </div>
    `;
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

            let statusBadge = "";
            if (step.status === "COMPLETED") {
              statusBadge = `<span class="badge-pass">PASS</span>`;
            } else if (step.status === "FAILED") {
              statusBadge = `<span class="badge-fail">FAIL</span>`;
            } else {
              statusBadge = `<span class="permission-badge ${permClass}">${step.status || step.permission_level}</span>`;
            }

            let testLogHtml = "";
            if (step.result && step.result.output && typeof step.result.output === "object") {
              const out = step.result.output;
              const stdout = out.stdout || "";
              const stderr = out.stderr || "";
              const exitCode = out.returncode !== undefined ? out.returncode : out.exit_code;
              if (stdout || stderr || exitCode !== undefined) {
                const combined = (stdout + "\n" + stderr).trim();
                const codeColor = (exitCode === 0) ? "var(--emerald-neon)" : "var(--rose-neon)";
                testLogHtml = `
                  <div class="test-output-box">
                    <div style="font-weight: 700; margin-bottom: 4px; color: ${codeColor};">
                      Execution Verification Output (Exit Code: ${exitCode !== undefined ? exitCode : '0'})
                    </div>
                    <div>${escapeHtml(combined || "(Process returned no output)")}</div>
                  </div>
                `;
              }
            }

            return `
              <div class="plan-step-item">
                <span class="step-num">#${step.step_id}</span>
                <div class="step-body">
                  <div class="step-desc">
                    <strong>[${escapeHtml(step.tool_name)}]</strong> ${escapeHtml(step.description || "")}
                  </div>
                  <div class="step-params">Params: ${escapeHtml(paramsStr)}</div>
                  ${testLogHtml}
                </div>
                ${statusBadge}
              </div>
            `;
          })
          .join("");

        const diffHtml = plan.diff_preview ? renderDiffHtml(plan.diff_preview) : "";
        const chkId = plan.checkpoint_id || (plan.metadata && plan.metadata.checkpoint_id);
        const chkBadge = chkId ? `<span class="badge-checkpoint" title="Recovery Checkpoint">Chk: ${escapeHtml(chkId.slice(0, 16))}</span>` : "";
        const rollbackBtn = chkId ? `
          <button class="btn-rollback rollback-plan-btn" data-id="${plan.plan_id}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="1 4 1 10 7 10"></polyline>
              <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
            </svg>
            Rollback
          </button>
        ` : "";

        planCard.innerHTML = `
          <div class="plan-header">
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="plan-id">${escapeHtml(plan.plan_id)}</span>
                ${chkBadge}
              </div>
              <div class="plan-prompt">${escapeHtml(plan.user_prompt || plan.summary || "Multi-step Task")}</div>
            </div>
            <span class="status-badge ${plan.status === 'COMPLETED' ? 'healthy' : (plan.status === 'FAILED' ? 'unavailable' : 'degraded')}">${plan.status}</span>
          </div>
          ${diffHtml}
          <div class="plan-steps-container">
            ${stepsHtml}
          </div>
          <div class="plan-actions">
            ${rollbackBtn}
            <button class="btn-success approve-plan-btn" data-id="${plan.plan_id}" ${plan.status !== 'STAGED' ? 'disabled style="opacity: 0.5;"' : ''}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              Approve Plan
            </button>
            <button class="btn-danger reject-plan-btn" data-id="${plan.plan_id}" ${plan.status !== 'STAGED' ? 'disabled style="opacity: 0.5;"' : ''}>
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

      document.querySelectorAll(".rollback-plan-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const planId = btn.getAttribute("data-id");
          await rollbackPlan(planId);
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

  async function rollbackPlan(planId) {
    try {
      const res = await apiFetch(`/api/plans/${planId}/rollback`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Workspace reverted to checkpoint ${data.checkpoint_id}.`, "success");
        await fetchPlans();
      } else {
        const err = await res.json();
        showToast(`Rollback failed: ${err.detail || "Error"}`, "error");
      }
    } catch (e) {
      showToast(`Network error triggering rollback.`, "error");
    }
  }

  // Operator Actions
  async function runOperatorSnapshot() {
    if (!operatorProjectPath) return;
    const path = operatorProjectPath.value.trim();
    if (!path) {
      showToast("Please enter a project repository path", "error");
      return;
    }
    try {
      if (operatorSnapshotBtn) {
        operatorSnapshotBtn.disabled = true;
        operatorSnapshotBtn.textContent = "Inspecting...";
      }
      const res = await apiFetch("/api/operator/snapshot", {
        method: "POST",
        body: JSON.stringify({ project_path: path }),
      });
      if (!res.ok) {
        const err = await res.json();
        showToast(`Inspect failed: ${err.detail || "Error"}`, "error");
        return;
      }
      const data = await res.json();
      const pt = data.project_type || {};
      const git = pt.git || {};

      if (operatorIntelContainer) operatorIntelContainer.style.display = "block";
      if (operatorInfoPills) {
        operatorInfoPills.innerHTML = `
          <span class="info-pill active">Lang: ${escapeHtml(pt.language || "unknown")}</span>
          <span class="info-pill">Framework: ${escapeHtml(pt.framework || "none")}</span>
          <span class="info-pill active">Runner: ${escapeHtml(pt.test_runner || "none")}</span>
          <span class="info-pill">Pkg: ${escapeHtml(pt.package_manager || "none")}</span>
          <span class="info-pill ${git.is_clean ? 'clean' : 'dirty'}">Git: ${git.is_git ? (git.is_clean ? 'Clean (' + git.branch + ')' : 'Dirty') : 'Non-Git'}</span>
          <span class="info-pill">Files: ${data.files ? data.files.length : 0}</span>
        `;
      }
      showToast(`Discovered ${pt.language} workspace (${data.files ? data.files.length : 0} files).`);
    } catch (e) {
      showToast(`Network error inspecting project: ${e.message}`, "error");
    } finally {
      if (operatorSnapshotBtn) {
        operatorSnapshotBtn.disabled = false;
        operatorSnapshotBtn.textContent = "Inspect";
      }
    }
  }

  async function runOperatorDiagnoseAndPlan() {
    if (!operatorProjectPath) return;
    const path = operatorProjectPath.value.trim();
    const testCmd = operatorTestCommand ? operatorTestCommand.value.trim() : null;
    if (!path) {
      showToast("Please enter a project repository path", "error");
      return;
    }
    try {
      if (operatorDiagnoseBtn) {
        operatorDiagnoseBtn.disabled = true;
        operatorDiagnoseBtn.textContent = "Diagnosing & Planning...";
      }
      const res = await apiFetch("/api/operator/plan-fix", {
        method: "POST",
        body: JSON.stringify({ project_path: path, test_command: testCmd || undefined }),
      });
      if (!res.ok) {
        const err = await res.json();
        showToast(`Planning failed: ${err.detail || "Error"}`, "error");
        return;
      }
      const data = await res.json();
      const diag = data.diagnostic || {};
      if (operatorDiagnosticContainer) operatorDiagnosticContainer.style.display = "block";
      if (diagnosticSummaryBadge) {
        diagnosticSummaryBadge.className = diag.passed ? "badge-pass" : "badge-fail";
        diagnosticSummaryBadge.textContent = diag.passed ? "TESTS PASSING" : "TEST FAILURE DETECTED";
      }
      if (diagnosticOutputText) {
        diagnosticOutputText.textContent = diag.root_cause_trace || diag.stdout || diag.stderr || diag.error_summary || "No diagnostic trace recorded.";
      }

      showToast(`Plan staged: ${data.plan ? data.plan.plan_id : "Plan created"}!`, "success");
      await fetchPlans();
    } catch (e) {
      showToast(`Network error during plan synthesis: ${e.message}`, "error");
    } finally {
      if (operatorDiagnoseBtn) {
        operatorDiagnoseBtn.disabled = false;
        operatorDiagnoseBtn.textContent = "Diagnose & Plan Fix";
      }
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

    // 2. Setup Project Operator
    if (operatorDiagnoseBtn) {
      operatorDiagnoseBtn.addEventListener("click", runOperatorDiagnoseAndPlan);
    }
    if (operatorSnapshotBtn) {
      operatorSnapshotBtn.addEventListener("click", runOperatorSnapshot);
    }
    if (operatorProjectPath) {
      operatorProjectPath.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          runOperatorDiagnoseAndPlan();
        }
      });
    }

    // 3. Setup Memory Form
    if (addPrefBtn) {
      addPrefBtn.addEventListener("click", savePreference);
    }

    // 4. Initial Load
    await refreshAll();

    // 5. Polling loop every 3.5 seconds
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
