const app = {

  // ---- who is using this device ---------------------------------------
  profile: null,

  // Every API call carries the signed-in profile, so two people sharing a
  // computer never see each other's tasks, settings or conversation.
  api: function(path, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = Object.assign({}, opts.headers || {}, { "X-Profile": this.profile || "default" });
    return fetch(path, opts);
  },

  loadProfile: function() {
    try { this.profile = localStorage.getItem("sn.profile"); } catch (e) { this.profile = null; }
    return this.profile;
  },

  setProfile: function(name) {
    this.profile = name;
    try { localStorage.setItem("sn.profile", name); } catch (e) { /* private mode */ }
    const el = document.getElementById("id-current-profile");
    if (el) el.innerText = name;
  },

  showSignIn: function() { document.getElementById("id-signin-overlay").classList.add("is-open"); },
  hideSignIn: function() { document.getElementById("id-signin-overlay").classList.remove("is-open"); },

  renderProfileList: async function() {
    const box = document.getElementById("id-profile-list");
    if (!box) return;
    let names = [];
    try {
      const r = await fetch("/api/profiles");
      names = (await r.json()).profiles || [];
    } catch (e) { /* offline: they can still create one */ }
    box.innerHTML = names.length
      ? names.map(n => `<button class="profile-chip" onclick="app.chooseProfile('${n}')">${n}</button>`).join("")
      : '<p class="signin-empty">No one set up yet. Add your name below.</p>';
  },

  chooseProfile: async function(name) {
    this.setProfile(name);
    this.hideSignIn();
    await this.refreshAll();
  },

  addProfile: async function(event) {
    if (event && event.preventDefault) event.preventDefault();
    const input = document.getElementById("id-new-profile");
    const name = input.value.trim();
    if (!name) return;
    const r = await fetch("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    });
    if (!r.ok) { alert("Could not add that name."); return; }
    const data = await r.json();
    input.value = "";
    await this.chooseProfile(data.profile);
  },

  switchProfile: async function() {
    await this.renderProfileList();
    this.showSignIn();
  },

  refreshAll: async function() {
    await this.fetchTasks();
    this.fetchStatus();
    this.checkDiagnostic();
    this.fetchNudges();
  },

  tasks: [],
  userEnergy: 8.0,
  currentDiagnosticQuestion: null,

  init: async function() {
    this.loadNudgePrefs();
    const who = this.loadProfile();
    if (!who) {
      // nobody chosen on this device yet - ask before loading anyone's data
      await this.renderProfileList();
      this.showSignIn();
      return;
    }
    this.setProfile(who);
    await this.refreshAll();
  },

  usePreset: function(presetNumber) {
    const textEl = document.getElementById("id-input-raw-tasks");
    if (presetNumber === 1) {
      textEl.value = `Move lawnmower then clear doorway
Clean garage after moving lawnmower
Clean garden tools
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
      const res = await this.api("/api/ingest", {
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
      const res = await this.api("/api/tasks");
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

    // The solver's utility score is a relative number, meaningless on its own to a
    // person. Turn position in the sorted list into a phrase they can act on.
    const open = sorted.filter(t => !t.completed);
    const rank = {};
    open.forEach((t, i) => {
      const third = Math.max(1, Math.ceil(open.length / 3));
      rank[t.id] = i < third ? { label: 'Do first', cls: 'p-high' }
                 : i < third * 2 ? { label: 'Next up', cls: 'p-mid' }
                                 : { label: 'Can wait', cls: 'p-low' };
    });

    container.innerHTML = sorted.map(t => `
      <div class="task-item ${t.completed ? 'completed' : ''}" id="task-card-${t.id}">
        <div class="task-info">
          <div class="task-title">${t.title}</div>
          <div class="task-meta">
            <span>Takes about <strong>${this.formatMinutes(t.effort || 30)}</strong></span>
            <span><strong>${this.drainWord(t.required_energy)}</strong></span>
            ${t.prerequisites && t.prerequisites.length > 0 ? `<span>Do after: ${t.prerequisites.map(id => this.taskTitle(id)).join(', ')}</span>` : ''}
          </div>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
          <span class="priority-badge ${(rank[t.id] || {}).cls || ''}"
                title="Where this sits against everything else on your list right now">${t.completed ? 'Done' : ((rank[t.id] || {}).label || 'Can wait')}</span>
          <button class="btn-secondary" style="padding: 4px 10px; font-size: 12px;" onclick="app.toggleComplete('${t.id}')">
            ${t.completed ? '✓ Completed' : 'Mark Done'}
          </button>
        </div>
      </div>
    `).join("");
  },

  // Task effort is minutes. Show it as time a person recognises.
  formatMinutes: function(mins) {
    const m = Math.round(parseFloat(mins) || 0);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), r = m % 60;
    if (r === 0) return h === 1 ? "1 hour" : `${h} hours`;
    return `${h}h ${r}m`;
  },

  DRAIN_WORDS: { 3: "easy going", 5: "middling", 8: "heavy going" },
  drainWord: function(v) {
    const n = parseFloat(v) || 5;
    return n <= 3.5 ? this.DRAIN_WORDS[3] : (n >= 7 ? this.DRAIN_WORDS[8] : this.DRAIN_WORDS[5]);
  },

  taskTitle: function(id) {
    const t = (this.tasks || []).find(x => x.id === id);
    return t ? t.title : id;
  },

  ENERGY_WORDS: {
    1: "very little energy", 2: "very little energy", 3: "pretty drained",
    4: "a bit low",          5: "somewhere in the middle", 6: "doing okay",
    7: "pretty good",        8: "good energy", 9: "lots of energy",
    10: "very much energy"
  },

  userTime: 8,
  userEnergy: 8,

  updateTime: function(val) {
    this.userTime = parseFloat(val);
    const h = this.userTime;
    document.getElementById("id-val-user-time").innerText =
      h === 1 ? "1 hour" : (h < 1 ? `${h * 60} minutes` : `${h} hours`);
    this.pushUserState();
  },

  updateEnergy: function(val) {
    this.userEnergy = parseInt(val, 10);
    document.getElementById("id-val-user-energy").innerText =
      `${this.userEnergy} / 10 — ${this.ENERGY_WORDS[this.userEnergy]}`;
    this.pushUserState();
  },

  pushUserState: function() {
    clearTimeout(this._energyTimer);
    this._energyTimer = setTimeout(async () => {
      await this.api("/api/user-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // hours available drive the planner; energy 1-10 becomes the 0-1
        // receptivity the helper reads when deciding how hard to push
        body: JSON.stringify({ energy: this.userTime, receptivity: this.userEnergy / 10 })
      });
      await this.fetchTasks();
      await this.runILPSolver();
    }, 300);
  },

  // ---- nudge controls --------------------------------------------------
  nudgesEnabled: true,
  nudgeMinutes: 1,
  _nudgeTimer: null,

  loadNudgePrefs: function() {
    try {
      const on = localStorage.getItem("sn.nudgesOn");
      const mins = localStorage.getItem("sn.nudgeMins");
      if (on !== null) this.nudgesEnabled = on === "1";
      if (mins !== null) this.nudgeMinutes = Math.min(10, Math.max(1, parseInt(mins, 10) || 1));
    } catch (e) { /* private browsing, keep defaults */ }

    const box = document.getElementById("id-nudges-on");
    if (box) box.checked = this.nudgesEnabled;
    const range = document.getElementById("id-range-nudge-mins");
    if (range) range.value = this.nudgeMinutes;
    this.renderNudgeInterval();
    this.applyNudgeSchedule();
  },

  saveNudgePrefs: function() {
    try {
      localStorage.setItem("sn.nudgesOn", this.nudgesEnabled ? "1" : "0");
      localStorage.setItem("sn.nudgeMins", String(this.nudgeMinutes));
    } catch (e) { /* nothing we can do, and nothing that should break the page */ }
  },

  renderNudgeInterval: function() {
    const el = document.getElementById("id-val-nudge-mins");
    if (el) el.innerText = this.nudgeMinutes === 1 ? "1 minute" : `${this.nudgeMinutes} minutes`;
    const rate = document.getElementById("id-nudge-rate");
    if (rate) rate.style.opacity = this.nudgesEnabled ? "1" : "0.45";
    const range = document.getElementById("id-range-nudge-mins");
    if (range) range.disabled = !this.nudgesEnabled;
  },

  applyNudgeSchedule: function() {
    if (this._nudgeTimer) clearInterval(this._nudgeTimer);
    this._nudgeTimer = null;
    if (!this.nudgesEnabled) return;
    this._nudgeTimer = setInterval(() => this.fetchNudges(), this.nudgeMinutes * 60 * 1000);
  },

  setNudgesEnabled: function(on) {
    this.nudgesEnabled = !!on;
    this.saveNudgePrefs();
    this.renderNudgeInterval();
    this.applyNudgeSchedule();
  },

  setNudgeInterval: function(mins) {
    this.nudgeMinutes = Math.min(10, Math.max(1, parseInt(mins, 10) || 1));
    this.saveNudgePrefs();
    this.renderNudgeInterval();
    this.applyNudgeSchedule();
  },

  runILPSolver: async function() {
    try {
      const res = await this.api("/api/solve", { method: "POST" });
      const data = await res.json();

      const solveTimePill = document.getElementById("id-cloud-run-solve-time");
      if (solveTimePill) solveTimePill.innerText = `Solver: ${data.solve_time_ms}ms`;

      const resultsDiv = document.getElementById("id-solver-results");
      resultsDiv.style.display = "flex";

      document.getElementById("id-res-total-utility").innerText = data.total_priority || 0.0;
      // both come back in minutes from the solver
      document.getElementById("id-res-effort-used").innerText = this.formatMinutes(data.total_effort_used || 0);
      document.getElementById("id-res-energy-cap").innerText =
        this.formatMinutes(data.energy_capacity || this.userTime * 60);
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
              <div class="task-meta">Takes about ${app.formatMinutes(t.effort)}</div>
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
      await this.api("/api/complete-task", {
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
      const res = await this.api("/api/status");
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
      const res = await this.api("/api/diagnostic");
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
      await this.api("/api/diagnostic/answer", {
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
      const res = await this.api("/api/nudges");
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
  },

  // ---- Ask your helper -------------------------------------------------
  chatOpen: false,
  chatSession: 'web-' + Math.random().toString(36).slice(2, 10),

  toggleChat: function() {
    this.chatOpen = !this.chatOpen;
    document.getElementById('id-chat-panel').hidden = !this.chatOpen;
    if (this.chatOpen) document.getElementById('id-chat-text').focus();
  },

  askSuggested: function(btn) {
    document.getElementById('id-chat-text').value = btn.textContent;
    this.sendChat(new Event('submit'));
  },

  addChatMsg: function(text, who, extraClass) {
    const log = document.getElementById('id-chat-log');
    const el = document.createElement('div');
    el.className = 'chat-msg ' + who + (extraClass ? ' ' + extraClass : '');
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  },

  sendChat: async function(event) {
    if (event && event.preventDefault) event.preventDefault();
    const input = document.getElementById('id-chat-text');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    const chips = document.querySelector('.chat-chips');
    if (chips) chips.remove();
    this.addChatMsg(text, 'me');
    const pending = this.addChatMsg('thinking…', 'bot', 'thinking');
    try {
      const res = await this.api('/api/partner/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: this.chatSession })
      });
      const data = await res.json();
      pending.remove();
      if (!res.ok) {
        this.addChatMsg(data.detail || 'Your helper is unavailable right now.', 'bot');
        return;
      }
      this.addChatMsg(data.reply || 'Sorry, nothing came back. Try again?', 'bot');
    } catch (e) {
      pending.remove();
      this.addChatMsg('Could not reach your helper. Check your connection and try again.', 'bot');
    }
  },

  // ---- Subscription ----------------------------------------------------
  openPlans: function() { document.getElementById('id-plans-overlay').classList.add('is-open'); },
  closePlans: function() { document.getElementById('id-plans-overlay').classList.remove('is-open'); },

  // Only a click on the backdrop itself closes; clicks inside the box bubble
  // up to the same handler, so the target check is what keeps it open.
  closePlansFromOverlay: function(e) { if (e.target.id === 'id-plans-overlay') this.closePlans(); },

  startCheckout: function(e) {
    if (e && e.preventDefault) e.preventDefault();
    // Point PRO_CHECKOUT_URL at your payment provider when billing is live.
    const url = this.PRO_CHECKOUT_URL;
    if (url) { window.open(url, '_blank', 'noopener'); return false; }
    this.closePlans();
    if (!this.chatOpen) this.toggleChat();
    this.addChatMsg('Pro is not open for sign-ups just yet. Tell me what you would want it to '
      + 'remember about you, and I will make sure it is on the list.', 'bot');
    return false;
  },

  PRO_CHECKOUT_URL: null
};

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    app.closePlans();
    if (app.chatOpen) app.toggleChat();
  }
});

document.addEventListener("DOMContentLoaded", () => app.init());
