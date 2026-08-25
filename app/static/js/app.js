const app = {
  tasks: [],
  userEnergy: 8.0,
  currentDiagnosticQuestion: null,

  init: function() {
    this.fetchTasks();
    this.fetchStatus();
    this.checkDiagnostic();
    this.fetchNudges();

    // Periodic refresh of status & agent nudges
    setInterval(() => this.fetchNudges(), 8000);
  },

  usePreset: function(presetNumber) {
    const textEl = document.getElementById("id-input-raw-tasks");
    if (presetNumber === 1) {
      textEl.value = `Move lawnmower then clear doorway
Clean garage after moving lawnmower
Sanitize garden tools
Water lawn & backyard plants`;
    } else if (presetNumber === 2) {
      textEl.value = `Audit monthly receipts
Organize physical desk drawers
Draft quarterly project status email
Review administrative budget breakdown`;
    }
  },

  ingestTasks: async function() {
    const textEl = document.getElementById("id-input-raw-tasks");
    const rawText = textEl.value.trim();
    if (!rawText) {
      alert("Please enter at least one task or select a preset.");
      return;
    }

    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: rawText })
      });
      const data = await res.json();

      if (data.status === "success") {
        // Render DAG Resolutions if present
        const logBox = document.getElementById("id-dag-resolution-log");
        const logBody = document.getElementById("id-resolution-log-body");
        if (data.resolutions && data.resolutions.length > 0) {
          logBody.innerHTML = data.resolutions.map(r => `<div>• ${r}</div>`).join("");
          logBox.style.display = "block";
        } else {
          logBox.style.display = "none";
        }

        textEl.value = "";
        await this.fetchTasks();
        await this.runILPSolver();
        await this.checkDiagnostic();
      }
    } catch (e) {
      console.error("Task ingestion error:", e);
    }
  },

  fetchTasks: async function() {
    try {
      const res = await fetch("/api/tasks");
      const data = await res.json();
      this.tasks = data.tasks || [];
      this.renderTaskList();
      this.fetchStatus();
    } catch (e) {
      console.error("Fetch tasks error:", e);
    }
  },

  renderTaskList: function() {
    const container = document.getElementById("id-all-task-list");
    const badge = document.getElementById("id-task-count-badge");
    const docCountEl = document.getElementById("id-firestore-doc-count");

    if (badge) badge.innerText = `${this.tasks.length} Tasks`;
    if (docCountEl) docCountEl.innerText = `${this.tasks.length} docs synced`;

    if (!this.tasks || this.tasks.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; color: var(--text-muted); padding: 30px 0;">
          No tasks ingested yet. Enter tasks on the left to activate optimization.
        </div>
      `;
      return;
    }

    // Sort by priority descending
    const sorted = [...this.tasks].sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0));

    container.innerHTML = sorted.map(t => `
      <div class="task-item ${t.completed ? 'completed' : ''}" id="task-card-${t.id}">
        <div class="task-info">
          <div class="task-title">${t.title}</div>
          <div class="task-meta">
            <span>Effort (E_i): <strong>${t.effort || 5}</strong></span>
            <span>Req Energy: <strong>${t.required_energy || 5}</strong></span>
            ${t.prerequisites && t.prerequisites.length > 0 ? `<span>Prereqs: ${t.prerequisites.join(', ')}</span>` : ''}
          </div>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
          <span class="priority-badge">P_i: ${t.priority_score !== undefined ? t.priority_score : '0.0'}</span>
          <button class="btn-secondary" style="padding: 4px 10px; font-size: 12px;" onclick="app.toggleComplete('${t.id}')">
            ${t.completed ? '✓ Completed' : 'Mark Done'}
          </button>
        </div>
      </div>
    `).join("");
  },

  updateEnergy: function(val) {
    this.userEnergy = parseFloat(val);
    document.getElementById("id-val-user-energy").innerText = `${this.userEnergy} / 10`;

    // Debounce server user state update
    clearTimeout(this._energyTimer);
    this._energyTimer = setTimeout(async () => {
      await fetch("/api/user-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ energy: this.userEnergy, receptivity: 0.8 })
      });
      await this.fetchTasks();
      await this.runILPSolver();
    }, 300);
  },

  runILPSolver: async function() {
    try {
      const res = await fetch("/api/solve", { method: "POST" });
      const data = await res.json();

      const solveTimePill = document.getElementById("id-cloud-run-solve-time");
      if (solveTimePill) solveTimePill.innerText = `Solver: ${data.solve_time_ms}ms`;

      const resultsDiv = document.getElementById("id-solver-results");
      resultsDiv.style.display = "flex";

      document.getElementById("id-res-total-utility").innerText = data.total_priority || 0.0;
      document.getElementById("id-res-effort-used").innerText = data.total_effort_used || 0.0;
      document.getElementById("id-res-energy-cap").innerText = data.energy_capacity || this.userEnergy;
      document.getElementById("id-res-solve-time").innerText = `${data.solve_time_ms}ms`;

      const optList = document.getElementById("id-optimal-task-list");
      const selected = data.selected_tasks || [];

      if (selected.length === 0) {
        optList.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">No tasks selectable given energy envelope capacity ${this.userEnergy}. Try increasing energy slider.</div>`;
      } else {
        optList.innerHTML = selected.map((t, idx) => `
          <div class="task-item" style="border-left: 3px solid var(--accent-cyan);">
            <div class="task-info">
              <div class="task-title"><strong>#${idx + 1}</strong> ${t.title}</div>
              <div class="task-meta">Effort: ${t.effort} | Priority Utility Score: ${t.priority_score}</div>
            </div>
            <button class="btn-primary" style="padding: 6px 12px; font-size: 12px;" onclick="app.toggleComplete('${t.id}')">Start Task</button>
          </div>
        `).join("");
      }
    } catch (e) {
      console.error("Solver error:", e);
    }
  },

  toggleComplete: async function(taskId) {
    try {
      await fetch("/api/complete-task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId })
      });
      await this.fetchTasks();
      await this.runILPSolver();
      await this.fetchNudges();
    } catch (e) {
      console.error("Complete task error:", e);
    }
  },

  fetchStatus: async function() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();

      const fsMode = document.getElementById("id-firestore-mode");
      if (fsMode) {
        fsMode.innerText = data.services.cloud_firestore.native_gcp ? "Native GCP Firestore" : "Simulated NoSQL Sync";
      }
    } catch (e) {
      console.error("Fetch status error:", e);
    }
  },

  checkDiagnostic: async function() {
    try {
      const res = await fetch("/api/diagnostic");
      const data = await res.json();

      const modal = document.getElementById("id-diagnostic-modal");
      if (data.requires_diagnostic && data.question) {
        this.currentDiagnosticQuestion = data.question;
        document.getElementById("id-diag-question-text").innerText = data.question.question;

        const optionsContainer = document.getElementById("id-diag-options-container");
        optionsContainer.innerHTML = data.question.options.map(opt => `
          <button class="option-btn" onclick="app.answerDiagnostic('${data.question.id}', '${opt.value}')">
            ${opt.label}
          </button>
        `).join("");

        modal.style.display = "flex";
      } else {
        modal.style.display = "none";
      }
    } catch (e) {
      console.error("Diagnostic error:", e);
    }
  },

  answerDiagnostic: async function(questionId, value) {
    try {
      await fetch("/api/diagnostic/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: questionId, value: value })
      });
      document.getElementById("id-diagnostic-modal").style.display = "none";
      await this.fetchTasks();
      await this.runILPSolver();
    } catch (e) {
      console.error("Answer diagnostic error:", e);
    }
  },

  fetchNudges: async function() {
    try {
      const res = await fetch("/api/nudges");
      const data = await res.json();

      const nudges = data.nudges || [];
      const stream = document.getElementById("id-agent-nudge-stream");
      if (nudges.length > 0) {
        stream.innerHTML = nudges.map(n => `
          <div class="nudge-card">
            <span>${n.message}</span>
            <span style="font-size: 11px; opacity: 0.7;">${n.timestamp || 'Just now'}</span>
          </div>
        `).join("");

        const last = nudges[nudges.length - 1];
        if (last.feedback_density !== undefined) {
          document.getElementById("id-val-feedback-density").innerText = `${last.feedback_density} msg/min`;
        }
      }
    } catch (e) {
      console.error("Fetch nudges error:", e);
    }
  }
};

document.addEventListener("DOMContentLoaded", () => app.init());
