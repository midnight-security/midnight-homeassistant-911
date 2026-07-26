/**
 * Sidebar panel for the Midnight 911 integration.
 *
 * Plain custom element (no build step) registered via panel_custom.
 * Home Assistant sets `hass`, `narrow`, `route`, and `panel` as properties
 * on this element directly.
 */

const DOMAIN = "midnight_alerts";

function navigate(path) {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
}

class MidnightAlertsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._render();
  }

  _findButtonEntityId() {
    const hass = this._hass;
    if (!hass) return null;

    if (hass.entities) {
      const match = Object.values(hass.entities).find(
        (e) => e.platform === DOMAIN && e.entity_id.startsWith("button.")
      );
      if (match) return match.entity_id;
    }

    return Object.keys(hass.states).find(
      (id) => id.startsWith("button.") && id.includes("midnight_911")
    ) || null;
  }

  async _triggerAlert(entityId) {
    if (!this._hass || !entityId) return;
    try {
      await this._hass.callService("button", "press", { entity_id: entityId });
    } catch (err) {
      console.error("Midnight 911: failed to trigger alert", err); // eslint-disable-line no-console
    }
  }

  _render() {
    const hass = this._hass;
    if (!hass || !this.shadowRoot) return;

    const entityId = this._findButtonEntityId();
    const state = entityId ? hass.states[entityId] : null;
    const configured = !!state && state.state !== "unavailable";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          background: var(--primary-background-color);
          box-sizing: border-box;
          padding: 16px;
        }
        .card {
          max-width: 600px;
          margin: 32px auto;
          background: var(--card-background-color, #fff);
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, none);
          border: 1px solid var(--divider-color);
          padding: 24px;
        }
        h1 {
          font-size: 24px;
          font-weight: 400;
          margin: 0 0 4px 0;
          color: var(--primary-text-color);
        }
        p.subtitle {
          margin: 0 0 20px 0;
          color: var(--secondary-text-color);
        }
        .status-row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 0;
          border-top: 1px solid var(--divider-color);
          border-bottom: 1px solid var(--divider-color);
          margin-bottom: 20px;
        }
        .status-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          flex: none;
        }
        .status-dot.ok { background: var(--success-color, #4caf50); }
        .status-dot.warn { background: var(--warning-color, #ff9800); }
        .status-text {
          color: var(--primary-text-color);
          flex: 1;
        }
        button {
          font: inherit;
          cursor: pointer;
          border: none;
          border-radius: 8px;
          padding: 10px 18px;
        }
        .configure-link {
          background: none;
          color: var(--primary-color);
          padding: 4px 8px;
        }
        .trigger-button {
          width: 100%;
          background: var(--error-color, #db4437);
          color: #fff;
          font-size: 16px;
          padding: 14px;
        }
        .trigger-button:disabled {
          background: var(--disabled-color, #bdbdbd);
          cursor: not-allowed;
        }
      </style>
      <div class="card">
        <h1>Midnight 911</h1>
        <p class="subtitle">Professional security monitoring, straight from Home Assistant.</p>
        <div class="status-row">
          <div class="status-dot ${configured ? "ok" : "warn"}"></div>
          <div class="status-text">
            ${configured ? "Connected – API key verified" : "Not configured yet"}
          </div>
          ${configured ? "" : '<button class="configure-link" id="configure">Configure</button>'}
        </div>
        <button class="trigger-button" id="trigger" ${configured ? "" : "disabled"}>
          Trigger Alert
        </button>
      </div>
    `;

    const configureBtn = this.shadowRoot.getElementById("configure");
    if (configureBtn) {
      configureBtn.addEventListener("click", () => {
        navigate(`/config/integrations/integration/${DOMAIN}`);
      });
    }

    const triggerBtn = this.shadowRoot.getElementById("trigger");
    if (triggerBtn) {
      triggerBtn.addEventListener("click", () => this._triggerAlert(entityId));
    }
  }
}

customElements.define("midnight-alerts-panel", MidnightAlertsPanel);
