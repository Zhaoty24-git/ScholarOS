import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import test from "node:test";
import ts from "typescript";

// Compile the real helper with Vite's development env substituted; no server,
// browser credentials, storage or network is involved.
const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText.replaceAll("import.meta.env", "({ DEV: true })");
const api = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  return { ok: true, json: async () => ({ status: "ready" }) };
};

test("owner GET, POST and multipart carry the token only in the header", async () => {
  const synthetic = "synthetic-".repeat(5);
  api.setAccessToken(synthetic);
  await api.apiGet("/api/settings/status");
  await api.apiPost("/api/settings/local", { learn_username: "synthetic" });
  const form = new FormData();
  form.append("file", new Blob(["synthetic"]), "sample.md");
  await api.apiFetch("/api/upload", { method: "POST", body: form });
  for (const { url, init } of calls) {
    assert.equal(init.headers.get("Authorization"), `Bearer ${synthetic}`);
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    assert.ok(!url.includes(synthetic));
  }
  assert.equal(calls[1].init.headers.get("Content-Type"), "application/json");
  assert.equal(calls[2].init.headers.get("Content-Type"), null);
  assert.equal(calls[2].init.body, form);
});

test("locking clears the in-memory token", async () => {
  api.setAccessToken("");
  const before = calls.length;
  await assert.rejects(api.apiGet("/api/settings/status"));
  assert.equal(calls.length, before);
  assert.equal(api.authHeaders().Authorization, undefined);
});

test("locking must not send a caller-supplied stale Authorization header", async () => {
  api.setAccessToken("");
  const before = calls.length;
  await assert.rejects(api.apiFetch("/api/settings/status", { headers: { Authorization: "Bearer synthetic-stale" } }));
  assert.equal(calls.length, before);
});

test("a rejected backend token clears frontend authorization", async () => {
  const saved = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 401 });
  try {
    api.setAccessToken("synthetic-revoked");
    await assert.rejects(api.apiGet("/api/settings/status"));
    assert.equal(api.authHeaders().Authorization, undefined);
  } finally { globalThis.fetch = saved; }
});

test("locking invalidates an in-flight response", async () => {
  const saved = globalThis.fetch;
  let finish;
  globalThis.fetch = () => new Promise((resolve) => { finish = resolve; });
  try {
    api.setAccessToken("synthetic-pending");
    const pending = api.apiGet("/api/settings/status");
    api.setAccessToken("");
    finish({ ok: true, json: async () => ({ private: "synthetic" }) });
    await assert.rejects(pending);
  } finally { globalThis.fetch = saved; }
});

test("old business work cannot reuse a newly authorized owner's token", async () => {
  api.setAccessToken("synthetic-first-owner");
  const old = api.createSessionClient();
  api.setAccessToken("synthetic-second-owner");
  const before = calls.length;
  await assert.rejects(async () => old.apiPost("/api/sync/run", { allow_network: true }));
  assert.equal(calls.length, before);
});

test("stale unauthorized response cannot revoke a newer session", async () => {
  const saved = globalThis.fetch;
  let finish;
  globalThis.fetch = () => new Promise((resolve) => { finish = resolve; });
  try {
    api.setAccessToken("synthetic-first");
    const pending = api.apiGet("/api/settings/status");
    api.setAccessToken("synthetic-newer");
    finish({ ok: false, status: 401 });
    await assert.rejects(pending);
    assert.equal(api.authHeaders().Authorization, "Bearer synthetic-newer");
  } finally { globalThis.fetch = saved; }
});

test("locking while JSON is read invalidates its contents", async () => {
  const saved = globalThis.fetch;
  let finish, entered;
  const reading = new Promise((resolve) => { entered = resolve; });
  globalThis.fetch = async () => ({ ok: true, json: () => {
    entered(); return new Promise((resolve) => { finish = resolve; });
  } });
  try {
    api.setAccessToken("synthetic-body");
    const pending = api.apiGet("/api/settings/status");
    await reading;
    api.setAccessToken("");
    finish({ private: "synthetic" });
    await assert.rejects(pending);
  } finally { globalThis.fetch = saved; }
});

test("a reloaded module starts locked", async () => {
  const fresh = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}#fresh-profile`);
  assert.equal(fresh.authHeaders().Authorization, undefined);
});
