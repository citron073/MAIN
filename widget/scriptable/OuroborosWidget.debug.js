const BASE_URL = "http://192.168.3.52:8787";
const TOKEN = "";

async function run() {
  const suffix = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
  const statusUrl = `${BASE_URL.replace(/\/$/, "")}/widget-status.json${suffix}`;

  const out = {
    url: statusUrl,
    app: "Scriptable",
    now: new Date().toISOString(),
  };

  try {
    const req = new Request(statusUrl);
    req.timeoutInterval = 10;
    const res = await req.loadJSON();
    out.ok = true;
    out.status_level = res.status_level;
    out.headline = res.headline;
    out.generated_at = res.generated_at;
    out.sample = {
      trade_enabled: res.trade_enabled,
      runner_alive: res.runner_alive,
      drift: res.drift,
    };
  } catch (err) {
    out.ok = false;
    out.error = String(err);
  }

  QuickLook.present(JSON.stringify(out, null, 2));
}

await run();
Script.complete();
