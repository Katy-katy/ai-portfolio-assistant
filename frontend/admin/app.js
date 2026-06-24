const API_BASE = "http://localhost:8000";

const refreshBtn = document.getElementById("refresh-btn");

document.addEventListener("DOMContentLoaded", () => {
    refreshBtn.addEventListener("click", () => loadDashboard());
    loadDashboard();
});

async function loadDashboard() {
    refreshBtn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/admin/overview?limit=10`);
        if (!response.ok) {
            throw new Error("Failed to load admin metrics");
        }

        const data = await response.json();
        renderSummary(data.summary || {});
        renderTopQuestions(data.top_questions || []);
        renderTopIntents(data.top_intents || []);
        renderTopSkills(data.top_skills || []);
        renderFailedRejected(data.recent_failed_or_rejected || []);
    } catch (err) {
        console.error("Admin dashboard error:", err);
        renderErrorState();
    } finally {
        refreshBtn.disabled = false;
    }
}

function renderSummary(summary) {
    setText("kpi-total-questions", String(summary.total_questions ?? 0));
    setText("kpi-avg-latency", `${Math.round(summary.avg_latency_ms ?? 0)} ms`);
    setText("kpi-feedback-submission", formatPct(summary.feedback_submission_rate ?? 0));
    setText("kpi-feedback-positive", formatPct(summary.positive_feedback_rate ?? 0));
}

function renderTopQuestions(rows) {
    renderTableRows("top-questions-body", rows, (row) => `
        <tr>
            <td>${escapeHtml(row.question || "-")}</td>
            <td>${Number(row.count || 0)}</td>
        </tr>
    `);
}

function renderTopIntents(rows) {
    renderTableRows("top-intents-body", rows, (row) => `
        <tr>
            <td>${escapeHtml(row.intent || "-")}</td>
            <td>${Number(row.count || 0)}</td>
        </tr>
    `);
}

function renderTopSkills(rows) {
    renderTableRows("top-skills-body", rows, (row) => `
        <tr>
            <td>${escapeHtml(row.skill || "-")}</td>
            <td>${Number(row.count || 0)}</td>
        </tr>
    `);
}

function renderFailedRejected(rows) {
    renderTableRows("failed-questions-body", rows, (row) => {
        const reasons = Array.isArray(row.reasons)
            ? row.reasons.map((reason) => `<span class="reason-pill">${escapeHtml(reason)}</span>`).join("")
            : "";

        return `
            <tr>
                <td>${formatDate(row.created_at)}</td>
                <td>${escapeHtml(row.question || "-")}</td>
                <td>${escapeHtml(row.intent || "-")}</td>
                <td>${Number(row.latency_ms || 0)} ms</td>
                <td>${reasons || "-"}</td>
            </tr>
        `;
    });
}

function renderTableRows(bodyId, rows, rowRenderer) {
    const body = document.getElementById(bodyId);
    if (!body) {
        return;
    }

    if (!rows.length) {
        body.innerHTML = `<tr><td class="empty" colspan="5">No data yet</td></tr>`;
        return;
    }

    body.innerHTML = rows.map((row) => rowRenderer(row)).join("");
}

function renderErrorState() {
    ["top-questions-body", "top-intents-body", "top-skills-body", "failed-questions-body"].forEach((id) => {
        const body = document.getElementById(id);
        if (body) {
            body.innerHTML = `<tr><td class="empty" colspan="5">Failed to load data</td></tr>`;
        }
    });
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
    }
}

function formatPct(value) {
    const pct = Number(value || 0) * 100;
    return `${pct.toFixed(1)}%`;
}

function formatDate(value) {
    if (!value) {
        return "-";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return "-";
    }

    return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function escapeHtml(str) {
    return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
