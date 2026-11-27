window.__ModuleLoader__.load({
  id: "@hugoxk/janus-dsh",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;

    const React = require("react");
    const h = React.createElement;

    const DEFAULT_BASE_URL = "http://127.0.0.1:8766";
    const REFRESH_MS = 5 * 60 * 1000;
    const TABS = ["market", "sector", "stock", "thesis", "calibration"];

    const C = {
      primary: "var(--dsw-alias-label-primary, #1f2328)",
      secondary: "var(--dsw-alias-label-secondary, #6e7781)",
      tertiary: "var(--dsw-alias-label-tertiary, #8c959f)",
      border: "var(--dsw-alias-border-l2, rgba(0, 0, 0, 0.12))",
      bg: "var(--dsw-alias-bg-l1, rgba(0, 0, 0, 0.03))",
      panel: "var(--dsw-specific-tip, rgba(0, 0, 0, 0.02))",
      danger: "var(--dsw-alias-state-error-primary, #d9534f)",
      ok: "var(--dsw-alias-state-success-primary, #2e7d32)",
      link: "var(--dsw-alias-link, #0969da)",
    };

    const S = {
      root: { margin: "0 auto 8px", padding: "0 16px", maxWidth: 860, color: C.primary, font: "inherit" },
      panel: { border: `1px solid ${C.border}`, borderRadius: 12, background: C.panel, overflow: "hidden" },
      bar: {
        display: "flex", alignItems: "center", gap: 8, width: "100%", minHeight: 38,
        padding: "4px 12px", background: "none", border: "none", color: "inherit",
        font: "inherit", cursor: "pointer", textAlign: "left",
      },
      title: { fontSize: 13, fontWeight: 600 },
      muted: { color: C.secondary, fontSize: 12 },
      meta: { color: C.tertiary, fontSize: 12, marginLeft: "auto", whiteSpace: "nowrap" },
      body: { borderTop: `1px solid ${C.border}`, padding: 12 },
      tabs: { display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 },
      tab: {
        border: `1px solid ${C.border}`, borderRadius: 999, background: "transparent",
        color: C.secondary, cursor: "pointer", font: "inherit", fontSize: 12, padding: "3px 10px",
      },
      activeTab: { borderColor: C.link, color: C.link },
      error: { color: C.danger, fontSize: 12, marginBottom: 8 },
      empty: { color: C.secondary, fontSize: 12, padding: "8px 0" },
      grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 },
      card: { border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 8px", background: C.bg },
      label: { color: C.tertiary, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 },
      value: { fontSize: 13, marginTop: 2, overflowWrap: "anywhere" },
      row: { display: "flex", justifyContent: "space-between", gap: 12, padding: "5px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 },
      code: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11, color: C.secondary },
      button: {
        border: `1px solid ${C.border}`, borderRadius: 6, background: "transparent",
        color: C.link, cursor: "pointer", font: "inherit", fontSize: 12, padding: "2px 8px",
      },
      select: {
        border: `1px solid ${C.border}`, borderRadius: 6, background: "transparent",
        color: C.primary, font: "inherit", fontSize: 12, padding: "1px 4px",
      },
    };

    function readConfig() {
      const globalConfig = (typeof window !== "undefined" && window.__JANUS_DSH_CONFIG__) || {};
      let stored = {};
      try {
        stored = JSON.parse(window.localStorage?.getItem("janus.dsh.config") || "{}");
      } catch {
        stored = {};
      }
      const rawWatchlist = globalConfig.watchlist || stored.watchlist || [];
      const watchlist = Array.isArray(rawWatchlist)
        ? rawWatchlist.map((item) => String(item).trim()).filter(Boolean)
        : [];
      return {
        baseUrl: String(globalConfig.baseUrl || stored.baseUrl || DEFAULT_BASE_URL).replace(/\/$/, ""),
        watchlist,
        token: globalConfig.token || stored.token ? String(globalConfig.token || stored.token) : "",
      };
    }

    function formatNumber(value) {
      if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "—");
      return Math.abs(value) >= 1000 ? value.toFixed(1) : value.toFixed(3);
    }

    function renderValue(value) {
      if (value === null || value === undefined) return "—";
      if (typeof value === "number") return formatNumber(value);
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }

    async function getJson(baseUrl, path, token) {
      const controller = typeof AbortController === "function" ? new AbortController() : null;
      const timer = controller ? setTimeout(() => controller.abort(), 15000) : null;
      try {
        const response = await fetch(`${baseUrl}${path}`, {
          signal: controller?.signal,
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`Janus API ${response.status}: ${text.slice(0, 200)}`);
        }
        return await response.json();
      } finally {
        if (timer !== null) clearTimeout(timer);
      }
    }

    function ErrorLine({ error, onRetry }) {
      if (!error) return null;
      return h(
        "div",
        { style: S.error, role: "alert" },
        error,
        onRetry ? h("button", { style: { ...S.button, marginLeft: 8 }, onClick: onRetry }, "Retry") : null,
      );
    }

    function Card({ label, value }) {
      return h("div", { style: S.card }, h("div", { style: S.label }, label), h("div", { style: S.value }, renderValue(value)));
    }

    function DataGrid({ data, keys }) {
      const entries = keys ? keys.map((key) => [key, data?.[key]]) : Object.entries(data || {});
      if (entries.length === 0) return h("div", { style: S.empty }, "No data.");
      return h("div", { style: S.grid }, entries.map(([key, value]) => h(Card, { key, label: key, value })));
    }

    function NotMaterialized({ payload }) {
      return h(
        "div",
        { style: S.empty },
        h("div", { style: { color: C.secondary, fontWeight: 600, marginBottom: 4 } }, "Not materialized"),
        h("div", null, payload?.hint || "Build features before opening this panel."),
      );
    }

    function MarketView({ data }) {
      if (data?.status === "not_materialized") return h(NotMaterialized, { payload: data });
      return h(
        "div",
        null,
        h(Card, { label: "regime", value: data?.regime }),
        h("div", { style: { height: 8 } }),
        h(DataGrid, { data: data?.indices, keys: Object.keys(data?.indices || {}) }),
        h("div", { style: { height: 8 } }),
        h(DataGrid, { data: data?.breadth, keys: Object.keys(data?.breadth || {}) }),
        h("div", { style: { height: 8 } }),
        h(DataGrid, { data: data?.volatility, keys: Object.keys(data?.volatility || {}) }),
        h("div", { style: { ...S.code, marginTop: 8 } }, `as_of ${data?.as_of || "—"} · ${data?.features_hash || "—"}`),
      );
    }

    function SectorView({ data }) {
      if (data?.status === "not_materialized") return h(NotMaterialized, { payload: data });
      const rows = Array.isArray(data?.sectors) ? data.sectors : [];
      if (rows.length === 0) return h("div", { style: S.empty }, "No sector rows.");
      return h(
        "div",
        null,
        rows.map((row) =>
          h(
            "div",
            { key: row.sector, style: S.row },
            h("span", { style: { fontWeight: 600 } }, row.sector),
            h("span", { style: S.muted }, `${row.quadrant} · RS ${formatNumber(row.rs_ratio)} · mom ${formatNumber(row.rs_momentum)} · breadth ${formatNumber(row.breadth)}`),
          ),
        ),
        h("div", { style: { ...S.code, marginTop: 8 } }, `benchmark ${data?.benchmark || "—"} · as_of ${data?.as_of || "—"}`),
      );
    }

    function StockView({ data }) {
      if (data?.status === "not_materialized") return h(NotMaterialized, { payload: data });
      const features = data?.features || {};
      return h(
        "div",
        null,
        h("div", { style: S.grid }, [
          h(Card, { key: "entity", label: "entity", value: data?.entity_id }),
          h(Card, { key: "close", label: "close", value: data?.close }),
        ]),
        h("div", { style: { height: 8 } }),
        h(DataGrid, { data: features, keys: Object.keys(features).slice(0, 12) }),
        h("div", { style: { ...S.code, marginTop: 8 } }, `as_of ${data?.as_of || "—"} · ${data?.features_hash || "—"}`),
      );
    }

    function ThesisView({ brief }) {
      const theses = Array.isArray(brief?.theses) ? brief.theses : [];
      if (theses.length === 0) return h("div", { style: S.empty }, "No theses yet.");
      return h(
        "div",
        null,
        theses.slice(0, 8).map((thesis) =>
          h(
            "div",
            { key: thesis.id, style: { padding: "6px 0", borderBottom: `1px solid ${C.border}` } },
            h("div", { style: { fontSize: 12, fontWeight: 600 } }, `${thesis.entity_id} · ${thesis.horizon} · ${thesis.status}`),
            h("div", { style: { fontSize: 12, color: C.secondary, marginTop: 2 } }, thesis.statement),
            Array.isArray(thesis.falsifiers) && thesis.falsifiers.length > 0
              ? h("div", { style: { ...S.code, marginTop: 4 } }, `falsifiers: ${thesis.falsifiers.join("; ")}`)
              : null,
          ),
        ),
      );
    }

    function CalibrationView({ brief }) {
      const report = brief?.calibration || {};
      return h(
        "div",
        null,
        h("div", { style: S.grid }, [
          h(Card, { key: "n", label: "settled", value: report.n }),
          h(Card, { key: "brier", label: "brier", value: report.brier }),
          h(Card, { key: "ece", label: "ece", value: report.ece }),
          h(Card, { key: "logloss", label: "log loss", value: report.log_loss }),
        ]),
        h("div", { style: { height: 8 } }),
        h(DataGrid, { data: brief?.observations?.length ? { observations: brief.observations.length, forecasts: brief.forecasts?.length || 0 } : {}, keys: ["observations", "forecasts"] }),
      );
    }

    function useBrief(baseUrl, entity, token) {
      const [state, setState] = React.useState({ loading: true, data: null, error: null, updatedAt: null });
      const load = React.useCallback(async () => {
        setState((current) => ({ ...current, loading: true, error: null }));
        try {
          const data = await getJson(
            baseUrl,
            `/api/brief?entity_id=${encodeURIComponent(entity)}`,
            token,
          );
          setState({ loading: false, data, error: null, updatedAt: new Date().toISOString() });
        } catch (error) {
          setState((current) => ({ ...current, loading: false, error: String(error?.message ?? error) }));
        }
      }, [baseUrl, entity, token]);
      React.useEffect(() => {
        let disposed = false;
        const safeLoad = () => {
          if (!disposed) void load();
        };
        safeLoad();
        const timer = setInterval(safeLoad, REFRESH_MS);
        return () => {
          disposed = true;
          clearInterval(timer);
        };
      }, [load]);
      return { ...state, reload: load };
    }

    function usePanel(baseUrl, tab, entity, active, token) {
      const [state, setState] = React.useState({ loading: false, data: null, error: null });
      const load = React.useCallback(async () => {
        setState({ loading: true, data: null, error: null });
        const query = tab === "stock" ? `?entity_id=${encodeURIComponent(entity)}` : "";
        try {
          const data = await getJson(baseUrl, `/api/panels/${tab}${query}`, token);
          setState({ loading: false, data, error: null });
        } catch (error) {
          setState({ loading: false, data: null, error: String(error?.message ?? error) });
        }
      }, [baseUrl, tab, entity]);
      React.useEffect(() => {
        if (!active || !["market", "sector", "stock"].includes(tab)) return;
        void load();
      }, [active, tab, load]);
      return { ...state, reload: load };
    }

    function JanusDock() {
      const config = React.useMemo(readConfig, []);
      const [entity, setEntity] = React.useState(config.watchlist[0] || "");
      const [expanded, setExpanded] = React.useState(false);
      const [tab, setTab] = React.useState("market");
      const brief = useBrief(config.baseUrl, entity, config.token);
      const panel = usePanel(config.baseUrl, tab, entity, expanded, config.token);
      const calibration = brief.data?.calibration || {};

      const headerMeta = brief.loading
        ? "loading…"
        : brief.error
          ? "unavailable"
          : `Brier ${formatNumber(calibration.brier)} · ${brief.data?.theses?.length || 0} theses · ${brief.updatedAt?.slice(11, 16) || "—"}`;

      return h(
        "div",
        { style: S.root, "data-janus-panel": "" },
        h(
          "div",
          { style: S.panel },
          h(
            "button",
            { style: S.bar, onClick: () => setExpanded((value) => !value), "aria-expanded": expanded },
            h("span", { style: S.title }, "JANUS"),
            config.watchlist.length > 1
              ? h(
                  "select",
                  {
                    style: S.select,
                    value: entity,
                    onClick: (event) => event.stopPropagation(),
                    onChange: (event) => setEntity(event.target.value),
                  },
                  config.watchlist.map((item) => h("option", { key: item, value: item }, item)),
                )
              : h("span", { style: S.muted }, entity || "no watchlist"),
            h("span", { style: S.meta }, headerMeta),
          ),
          expanded
            ? h(
                "div",
                { style: S.body },
                h(ErrorLine, { error: brief.error, onRetry: brief.reload }),
                h(
                  "div",
                  { style: S.tabs },
                  TABS.map((id) =>
                    h(
                      "button",
                      {
                        key: id,
                        style: { ...S.tab, ...(tab === id ? S.activeTab : {}) },
                        onClick: () => setTab(id),
                      },
                      id,
                    ),
                  ),
                  h(
                    "button",
                    {
                      style: { ...S.button, marginLeft: "auto" },
                      onClick: () => {
                        brief.reload();
                        if (["market", "sector", "stock"].includes(tab)) panel.reload();
                      },
                    },
                    "Refresh",
                  ),
                ),
                tab === "market" ? h(MarketView, { data: panel.data }) : null,
                tab === "sector" ? h(SectorView, { data: panel.data }) : null,
                tab === "stock" ? h(StockView, { data: panel.data }) : null,
                tab === "thesis" ? h(ThesisView, { brief: brief.data }) : null,
                tab === "calibration" ? h(CalibrationView, { brief: brief.data }) : null,
                ["market", "sector", "stock"].includes(tab)
                  ? h(ErrorLine, { error: panel.error, onRetry: panel.reload })
                  : null,
                panel.loading ? h("div", { style: S.empty }, "Loading…") : null,
                h("div", { style: { ...S.code, marginTop: 8 } }, `source ${config.baseUrl}`),
              )
            : null,
        ),
      );
    }

    function apply(ctx) {
      try {
        ctx.slots.inject("conversation.input.dock", () =>
          ctx.slots.register(
            {
              name: "conversation.input.dock",
              id: "janus",
              order: 10,
            },
            JanusDock,
          ),
        );
      } catch (error) {
        console.warn("[janus] failed to register conversation.input.dock:", error);
      }
    }

    exports.name = "janus";
    exports.inject = ["slots"];
    exports.apply = apply;
    return module.exports;
  },
});
